import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useFileOps } from "../../hooks/useFileOps";
import { useToastStore } from "../../store/toast";
import { Thumb } from "../timeline/Thumb";

/** 정리 마법사 Step 2 — 잡동사니 후보(사유 태그별) 검토·일괄 처리.
 *
 * 판별은 서버(photo_cache 기반, organize/junk.py), 실행은 기존 이동/삭제 +
 * undo를 그대로 재사용한다(ORGANIZE_WIZARD.md Phase 1). 기본 처분은 보관 이동
 * (`_정리/<사유>`) — 삭제는 명시적 선택. */
export function JunkStep() {
  const ops = useFileOps();
  const pushToast = useToastStore((s) => s.push);
  const q = useQuery({
    queryKey: ["junk-candidates"],
    queryFn: api.junkCandidates,
    staleTime: 60_000,
  });
  const [sel, setSel] = useState<Set<string>>(new Set());
  const groups = q.data?.groups ?? [];

  const toggle = (id: string) =>
    setSel((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleGroup = (ids: string[], on: boolean) =>
    setSel((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });

  /** `_정리/<라벨>` 폴더(개인 공간)를 찾거나 만들어 Foto id를 돌려준다. */
  const ensureJunkFolder = async (label: string): Promise<string> => {
    const findIn = (
      folders: { id: string; name: string; space: string }[],
      base: string,
    ) =>
      folders.find(
        (f) => f.space === "personal" && f.name.split("/").pop() === base,
      );
    let tops = (await api.folders()).folders;
    let root = findIn(tops, "_정리");
    if (!root) {
      await api.createFolder({ space: "personal", name: "_정리" });
      tops = (await api.folders()).folders;
      root = findIn(tops, "_정리");
    }
    if (!root) throw new Error("_정리 폴더를 만들지 못했습니다.");
    let subs = (await api.folders(root.id)).folders;
    let sub = findIn(subs, label);
    if (!sub) {
      await api.createFolder({
        space: "personal",
        name: label,
        parent_id: root.id,
      });
      subs = (await api.folders(root.id)).folders;
      sub = findIn(subs, label);
    }
    if (!sub) throw new Error(`_정리/${label} 폴더를 만들지 못했습니다.`);
    return sub.id;
  };

  const moveSelected = async (label: string, ids: string[]) => {
    const picked = ids.filter((id) => sel.has(id));
    if (picked.length === 0) return;
    try {
      const dest = await ensureJunkFolder(label);
      ops.move(picked, dest, false); // 진행바·충돌·undo 전부 기존 경로
      setSel((prev) => {
        const next = new Set(prev);
        for (const id of picked) next.delete(id);
        return next;
      });
    } catch (err) {
      pushToast((err as Error).message);
    }
  };

  const removeSelected = (ids: string[]) => {
    const picked = ids.filter((id) => sel.has(id));
    if (picked.length === 0) return;
    ops.remove(picked);
    setSel((prev) => {
      const next = new Set(prev);
      for (const id of picked) next.delete(id);
      return next;
    });
  };

  if (q.isPending)
    return <p className="p-6 text-center text-sm text-slate-400">후보 찾는 중…</p>;
  if (q.isError)
    return (
      <p className="p-6 text-center text-sm text-red-500">
        후보를 불러오지 못했습니다.
      </p>
    );
  if ((q.data?.scanned ?? 0) === 0)
    return (
      <div className="p-8 text-center text-sm leading-relaxed text-slate-500">
        아직 개인 공간 스캔 데이터가 없습니다.
        <br />
        먼저 <b>중복 정리</b> 탭에서 개인 공간 스캔을 한 번 실행하세요 — 그
        결과(photo_cache)를 여기서 재사용합니다.
      </div>
    );
  if (groups.length === 0)
    return (
      <div className="p-8 text-center text-sm text-slate-500">
        ✨ 잡동사니 후보가 없습니다. ({(q.data?.scanned ?? 0).toLocaleString()}장
        검사)
      </div>
    );

  return (
    <div className="h-full overflow-y-auto px-4 pb-24 pt-3">
      <p className="mb-3 text-xs leading-relaxed text-slate-500">
        개인 공간 {q.data!.scanned.toLocaleString()}장 중 후보{" "}
        {groups.reduce((a, g) => a + g.items.length, 0).toLocaleString()}장 —
        사유별로 검토 후 <b>보관 이동(_정리/…)</b> 또는 휴지통으로 보내세요. 모두
        되돌리기 가능합니다.
      </p>
      {groups.map((g) => {
        const ids = g.items.map((i) => i.id);
        const pickedCount = ids.filter((id) => sel.has(id)).length;
        const allOn = pickedCount === ids.length;
        return (
          <section key={g.reason} className="mb-6">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-bold text-slate-800">
                {g.label}{" "}
                <span className="text-slate-400">
                  {g.items.length.toLocaleString()}장
                </span>
              </h3>
              <button
                onClick={() => toggleGroup(ids, !allOn)}
                className="rounded-lg border border-slate-200 px-2 py-0.5 text-xs text-slate-500 hover:bg-slate-100"
              >
                {allOn ? "모두 해제" : "모두 선택"}
              </button>
              <span className="ml-auto flex gap-1.5">
                <button
                  onClick={() => moveSelected(g.label, ids)}
                  disabled={pickedCount === 0 || ops.isBusy}
                  className="rounded-lg bg-blue-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-40"
                >
                  {pickedCount}장 → _정리/{g.label}
                </button>
                <button
                  onClick={() => removeSelected(ids)}
                  disabled={pickedCount === 0 || ops.isBusy}
                  className="rounded-lg border border-red-200 px-2.5 py-1 text-xs text-red-600 hover:bg-red-50 disabled:opacity-40"
                >
                  휴지통
                </button>
              </span>
            </div>
            <div
              className="grid gap-1"
              style={{
                gridTemplateColumns: "repeat(auto-fill, minmax(96px, 1fr))",
              }}
            >
              {g.items.slice(0, 200).map((it) => {
                const on = sel.has(it.id);
                return (
                  <button
                    key={it.id}
                    onClick={() => toggle(it.id)}
                    title={`${it.filename}\n${it.taken_at}`}
                    className={`relative aspect-square overflow-hidden rounded-sm outline-none ${
                      on ? "ring-2 ring-blue-500" : "hover:ring-1 hover:ring-slate-300"
                    }`}
                  >
                    <Thumb item={it} space="personal" />
                    <span
                      className={`absolute left-1 top-1 flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${
                        on
                          ? "bg-blue-600 text-white"
                          : "bg-black/30 text-white/80"
                      }`}
                    >
                      ✓
                    </span>
                  </button>
                );
              })}
            </div>
            {g.items.length > 200 && (
              <p className="mt-1 text-xs text-slate-400">
                미리보기 200장 — 일괄 처리는 선택된 항목만 적용됩니다.
              </p>
            )}
          </section>
        );
      })}
    </div>
  );
}
