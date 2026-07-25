import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { EventSuggestion } from "../../api/types";
import { useFileOps } from "../../hooks/useFileOps";
import { useToastStore } from "../../store/toast";
import { Thumb } from "../timeline/Thumb";

/** 정리 마법사 Step 3 — 시간 갭 클러스터 이벤트를 공용 앨범(폴더)으로.
 *
 * 공용 반영은 '복사'가 기본(명세 4장 — 개인 원본 보존). 폴더는 공용의
 * /{연도} 아래에 만들어 기존 /YYYY/이벤트명 컨벤션을 따른다(연도 폴더가
 * 없으면 루트에). 실행은 기존 createFolder+move(copy) 재사용 — 진행바·undo
 * 포함. (ORGANIZE_WIZARD.md Phase 2) */
export function EventStep({
  onCreated,
}: {
  /** 앨범 생성 완료 콜백(마법사 통계 집계용): (앨범 수 증가분, 복사 장수). */
  onCreated?: (albums: number, photos: number) => void;
}) {
  const ops = useFileOps();
  const qc = useQueryClient();
  const pushToast = useToastStore((s) => s.push);
  const [gapHours, setGapHours] = useState(4);
  const [minPhotos, setMinPhotos] = useState(8);
  const [hideCopied, setHideCopied] = useState(true);
  // 562건 전량 마운트 방지 — 30개씩 증분 렌더(제안은 최신순이라 위에서부터 처리).
  const PAGE = 30;
  const [visible, setVisible] = useState(PAGE);
  const q = useQuery({
    queryKey: ["event-suggestions", gapHours, minPhotos, hideCopied],
    queryFn: () => api.eventSuggestions(gapHours, minPhotos, hideCopied),
    staleTime: 60_000,
  });
  const [open, setOpen] = useState<string | null>(null); // start 키
  const [names, setNames] = useState<Record<string, string>>({});
  const [excluded, setExcluded] = useState<Record<string, Set<string>>>({});
  const [doneKeys, setDoneKeys] = useState<Set<string>>(new Set());

  const events = q.data?.events ?? [];

  const toggleExclude = (key: string, id: string) =>
    setExcluded((prev) => {
      const cur = new Set(prev[key] ?? []);
      if (cur.has(id)) cur.delete(id);
      else cur.add(id);
      return { ...prev, [key]: cur };
    });

  /** 공용 /{연도} 아래(없으면 루트)에 이벤트 폴더를 만들고 id를 돌려준다. */
  const ensureEventFolder = async (ev: EventSuggestion, name: string) => {
    const year = ev.start.slice(0, 4);
    const tops = (await api.folders()).folders;
    const yearFolder = tops.find(
      (f) => f.space === "team" && f.name === `/${year}`,
    );
    const parentId = yearFolder?.id;
    const listIn = async () =>
      (await api.folders(parentId)).folders.filter((f) => f.space === "team");
    let sub = (await listIn()).find((f) => f.name.split("/").pop() === name);
    if (!sub) {
      await api.createFolder({
        space: "team",
        name,
        parent_id: parentId,
      });
      sub = (await listIn()).find((f) => f.name.split("/").pop() === name);
    }
    if (!sub) throw new Error(`가족 공간에 '${name}' 폴더를 만들지 못했습니다.`);
    return sub.id;
  };

  const createAlbum = async (ev: EventSuggestion) => {
    const key = ev.start;
    const defaultName = ev.place ? `${ev.name_hint} ${ev.place}` : ev.name_hint;
    const name = (names[key] ?? defaultName).trim();
    if (!name) return;
    const skip = excluded[key] ?? new Set<string>();
    const ids = ev.item_ids.filter((id) => !skip.has(id));
    if (ids.length === 0) return;
    try {
      const dest = await ensureEventFolder(ev, name);
      ops.move(ids, dest, true); // 복사 — 진행바·충돌·undo 기존 경로
      setDoneKeys((prev) => new Set(prev).add(key));
      void api.recordCopied(ids); // '이미 복사됨' 제외용 기록(best-effort)
      onCreated?.(1, ids.length);
      pushToast(`'${name}' — ${ids.length}장을 가족 공간으로 복사합니다.`);
      qc.invalidateQueries({ queryKey: ["folders"] });
    } catch (err) {
      pushToast((err as Error).message);
    }
  };

  return (
    <div className="h-full overflow-y-auto px-4 pb-24 pt-3">
      <div
        data-no-boxselect
        className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600"
      >
        <label className="flex items-center gap-2">
          이벤트 간격 {gapHours}시간
          <input
            type="range"
            min={1}
            max={24}
            value={gapHours}
            onChange={(e) => {
              setGapHours(Number(e.target.value));
              setVisible(PAGE);
            }}
          />
        </label>
        <label className="flex items-center gap-2">
          최소 {minPhotos}장
          <input
            type="range"
            min={3}
            max={50}
            value={minPhotos}
            onChange={(e) => {
              setMinPhotos(Number(e.target.value));
              setVisible(PAGE);
            }}
          />
        </label>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={hideCopied}
            onChange={(e) => {
              setHideCopied(e.target.checked);
              setVisible(PAGE);
            }}
          />
          복사한 이벤트 숨기기
        </label>
        {q.data && (
          <span className="text-slate-400">
            {q.data.scanned.toLocaleString()}장 → 제안 {events.length}건
            {(q.data.hidden_copied ?? 0) > 0 &&
              ` (복사됨 ${q.data.hidden_copied}건 숨김)`}
          </span>
        )}
      </div>

      {q.isPending && (
        <p className="p-6 text-center text-sm text-slate-400">이벤트 묶는 중…</p>
      )}
      {q.isError && (
        <p className="p-6 text-center text-sm text-red-500">
          제안을 불러오지 못했습니다.
        </p>
      )}
      {!q.isPending && !q.isError && events.length === 0 && (
        <p className="p-8 text-center text-sm text-slate-500">
          조건에 맞는 이벤트가 없습니다 — 간격/최소 장수를 조절해 보세요.
        </p>
      )}

      {events.slice(0, visible).map((ev) => {
        const key = ev.start;
        const defaultName = ev.place ? `${ev.name_hint} ${ev.place}` : ev.name_hint;
        const name = names[key] ?? defaultName;
        const skip = excluded[key] ?? new Set<string>();
        const pickCount = ev.item_ids.length - skip.size;
        const done = doneKeys.has(key);
        return (
          <section
            key={key}
            className={`mb-4 rounded-xl border p-3 ${
              done ? "border-green-200 bg-green-50/50" : "border-slate-200"
            }`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex gap-0.5">
                {ev.preview.map((it) => (
                  <div
                    key={it.id}
                    className="h-12 w-12 overflow-hidden rounded"
                  >
                    <Thumb item={it} space="personal" />
                  </div>
                ))}
              </div>
              <div className="min-w-0">
                <input
                  value={name}
                  onChange={(e) =>
                    setNames((p) => ({ ...p, [key]: e.target.value }))
                  }
                  className="w-56 rounded-lg border border-slate-200 px-2 py-1 text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-400"
                />
                <p className="mt-0.5 text-xs text-slate-400">
                  {ev.start.slice(0, 16).replace("T", " ")} ~{" "}
                  {ev.end.slice(5, 16).replace("T", " ")} · {ev.count}장
                  {ev.place && ` · 📍${ev.place}`}
                  {(ev.copied_count ?? 0) > 0 &&
                    ` · 복사됨 ${ev.copied_count}`}
                  {skip.size > 0 && ` (제외 ${skip.size})`}
                </p>
              </div>
              <span className="ml-auto flex gap-1.5">
                <button
                  onClick={() => setOpen(open === key ? null : key)}
                  className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs text-slate-500 hover:bg-slate-100"
                >
                  {open === key ? "접기" : "살펴보기"}
                </button>
                <button
                  onClick={() => createAlbum(ev)}
                  disabled={done || pickCount === 0 || ops.isBusy}
                  className="rounded-lg bg-blue-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-40"
                >
                  {done ? "복사됨 ✓" : `가족에 앨범 만들기 (${pickCount}장)`}
                </button>
              </span>
            </div>
            {open === key && (
              <OpenGrid ev={ev} skip={skip} onToggle={(id) => toggleExclude(key, id)} />
            )}
          </section>
        );
      })}
      {events.length > visible && (
        <div className="pb-6 text-center">
          <button
            onClick={() => setVisible((v) => v + PAGE)}
            className="rounded-lg border border-slate-200 px-4 py-1.5 text-sm text-slate-600 hover:bg-slate-100"
          >
            더 보기 ({events.length - visible}건 남음)
          </button>
        </div>
      )}
    </div>
  );
}

/** 펼침 그리드 — 이벤트 아이템을 로드해 개별 제외(베스트컷 선별). */
function OpenGrid({
  ev,
  skip,
  onToggle,
}: {
  ev: EventSuggestion;
  skip: Set<string>;
  onToggle: (id: string) => void;
}) {
  // 미리보기 4장 외의 썸네일 메타는 아이템 id·cache_key가 photo_cache 기반이라
  // 서버 제안에 없음 — 이벤트 기간의 일자 버킷으로 로드하는 대신, id만으로
  // 썸네일 URL을 만들 수 없어 v1은 preview에 포함된 항목만 그리드에 보여주고
  // 나머지는 개수로 표기한다(제외는 전체 id 대상 아님을 안내).
  return (
    <div className="mt-3">
      <div
        className="grid gap-1"
        style={{ gridTemplateColumns: "repeat(auto-fill, minmax(96px, 1fr))" }}
      >
        {ev.preview.map((it) => {
          const off = skip.has(it.id);
          return (
            <button
              key={it.id}
              onClick={() => onToggle(it.id)}
              title={it.filename}
              className={`relative aspect-square overflow-hidden rounded-sm ${
                off ? "opacity-30" : ""
              }`}
            >
              <Thumb item={it} space="personal" />
              {off && (
                <span className="absolute inset-0 flex items-center justify-center text-xl">
                  🚫
                </span>
              )}
            </button>
          );
        })}
      </div>
      <p className="mt-1 text-xs text-slate-400">
        대표 {ev.preview.length}장 표시 — 세부 선별은 복사 후 가족 폴더에서
        지워도 됩니다(휴지통·되돌리기 지원).
      </p>
    </div>
  );
}
