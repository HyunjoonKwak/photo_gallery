import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, thumbnailUrl } from "../api/client";
import type { PersonInfo, Space } from "../api/types";
import { useTimelineStore, type AlbumKind } from "../store/timeline";
import { useToastStore } from "../store/toast";
import { UniformPhotoGrid } from "./timeline/UniformPhotoGrid";
import { DateGroupedGrid } from "./timeline/DateGroupedGrid";
import { PlacesRegionView } from "./PlacesRegionView";

/** 앨범(감상) — 사람/장소/비디오. Synology Photos 내장 AI 그룹(얼굴·GPS)과
 * 라이브러리 전체 비디오를 순수 뷰어로 브라우즈. 정리는 폴더 분류에서. */
const KINDS: { k: AlbumKind; label: string; icon: string }[] = [
  { k: "people", label: "사람", icon: "👤" },
  { k: "places", label: "장소", icon: "📍" },
  { k: "videos", label: "비디오", icon: "🎬" },
];

// 인물(얼굴 인식)은 Synology Photos가 개인 공간에서만 그룹핑한다(공유 공간엔
// 얼굴 그룹이 없어 FotoTeam.Browse.Person이 항상 빈 결과). 그래서 공식 앱처럼
// 라이브러리(공용/내사진) 토글과 무관하게 항상 개인 공간을 본다. 장소(지오
// 코딩)·비디오는 공용/개인 각각 존재하므로 토글(space)을 따른다.
const PEOPLE_SPACE: Space = "personal";

export function AlbumsScreen() {
  const space = useTimelineStore((s) => s.space);
  const albumKind = useTimelineStore((s) => s.albumKind);
  const setAlbumKind = useTimelineStore((s) => s.setAlbumKind);
  const groupId = useTimelineStore((s) => s.groupId);
  const groupLabel = useTimelineStore((s) => s.groupLabel);
  const openGroup = useTimelineStore((s) => s.openGroup);
  const closeGroup = useTimelineStore((s) => s.closeGroup);

  return (
    <div className="flex h-full flex-col">
      <div
        data-no-boxselect
        className="flex shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-3 py-1.5 sm:px-4"
      >
        <nav className="flex gap-0.5 rounded-lg bg-slate-100 p-0.5">
          {KINDS.map((v) => (
            <button
              key={v.k}
              onClick={() => setAlbumKind(v.k)}
              className={`flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                albumKind === v.k
                  ? "bg-white text-slate-800 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              <span>{v.icon}</span>
              {v.label}
            </button>
          ))}
        </nav>
        {groupId && (
          <>
            <button
              onClick={closeGroup}
              className="rounded px-1.5 py-0.5 text-sm text-blue-600 hover:bg-slate-100"
            >
              ‹ 뒤로
            </button>
            <span className="text-sm font-semibold text-slate-700">
              {groupLabel}
            </span>
          </>
        )}
      </div>

      <div className="min-h-0 flex-1">
        {albumKind === "people" &&
          (groupId ? (
            <GroupGrid space={PEOPLE_SPACE} kind="person" id={groupId} />
          ) : (
            <PeopleGrid space={PEOPLE_SPACE} onOpen={openGroup} />
          ))}
        {albumKind === "places" && <PlacesRegionView space={space} />}
        {albumKind === "videos" && <VideosGrid space={space} />}
      </div>
    </div>
  );
}

function PeopleGrid({
  space,
  onOpen,
}: {
  space: Space;
  onOpen: (id: string, label: string) => void;
}) {
  const q = useQuery({
    queryKey: ["persons", space],
    queryFn: () => api.persons(space),
    staleTime: 5 * 60_000,
  });
  const persons = q.data?.persons ?? [];
  // 기존에 지정된 이름들 — 이름 입력 시 선택지로 제공(선택=병합, 새로 입력=신규).
  const existingNames = useMemo(
    () => [...new Set(persons.map((p) => p.name).filter(Boolean))],
    [persons],
  );
  if (q.isPending)
    return <p className="p-6 text-sm text-slate-400">불러오는 중…</p>;
  if (persons.length === 0)
    return (
      <p className="p-6 text-sm text-slate-400">
        인식된 인물이 없습니다 — Synology Photos에서 "인물" 기능을 확인해 보세요.
      </p>
    );
  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="flex flex-wrap gap-1">
        {persons.map((p) => (
          <PersonCard
            key={p.id}
            person={p}
            space={space}
            existingNames={existingNames}
            onOpen={() => onOpen(p.id, p.name || "이름 없는 인물")}
          />
        ))}
      </div>
    </div>
  );
}

function PersonCard({
  person,
  space,
  existingNames,
  onOpen,
}: {
  person: PersonInfo;
  space: Space;
  existingNames: string[];
  onOpen: () => void;
}) {
  const label = person.name || "이름 없는 인물";
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(person.name);
  const listId = `names-${person.id}`;
  const qc = useQueryClient();
  const pushToast = useToastStore((s) => s.push);

  const mutation = useMutation({
    mutationFn: (name: string) => api.namePerson(person.id, name),
    onSuccess: (res) => {
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["persons", space] });
      qc.invalidateQueries({ queryKey: ["album-items", space] });
      pushToast(
        res.merged_into
          ? `"${res.name}"(으)로 병합했습니다.`
          : `이름을 "${res.name}"(으)로 지정했습니다.`,
      );
    },
    onError: () =>
      pushToast("이름 지정에 실패했습니다. 잠시 후 다시 시도해 주세요."),
  });

  const submit = () => {
    const n = value.trim();
    if (n && n !== person.name) mutation.mutate(n);
    else setEditing(false);
  };

  return (
    <div className="flex w-24 flex-col items-center gap-1.5 rounded-xl p-2 hover:bg-slate-100">
      <button onClick={onOpen} title={label} className="outline-none">
        {person.cover_item_id ? (
          <img
            src={thumbnailUrl(
              person.space,
              person.cover_item_id,
              person.cover_cache_key ?? "",
              "sm",
            )}
            alt={label}
            className="h-16 w-16 rounded-full bg-slate-200 object-cover"
            loading="lazy"
          />
        ) : (
          <span className="flex h-16 w-16 items-center justify-center rounded-full bg-slate-200 text-2xl">
            👤
          </span>
        )}
      </button>

      {editing ? (
        <div className="flex w-full flex-col items-stretch gap-1">
          <input
            autoFocus
            list={listId}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
              if (e.key === "Escape") {
                setEditing(false);
                setValue(person.name);
              }
            }}
            placeholder="이름 입력/선택"
            className="w-full rounded border border-slate-300 px-1 py-0.5 text-center text-xs outline-none focus:border-blue-400"
          />
          <datalist id={listId}>
            {existingNames
              .filter((n) => n !== person.name)
              .map((n) => (
                <option key={n} value={n} />
              ))}
          </datalist>
          <div className="flex gap-1">
            <button
              onClick={submit}
              disabled={mutation.isPending}
              className="flex-1 rounded bg-blue-500 py-0.5 text-[10px] font-medium text-white disabled:opacity-50"
            >
              {mutation.isPending ? "…" : "확인"}
            </button>
            <button
              onClick={() => {
                setEditing(false);
                setValue(person.name);
              }}
              className="flex-1 rounded bg-slate-200 py-0.5 text-[10px] text-slate-600"
            >
              취소
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => {
            setValue(person.name);
            setEditing(true);
          }}
          title="이름 지정/변경"
          className="flex w-full items-center justify-center gap-0.5 outline-none"
        >
          <span
            className={`truncate text-xs ${
              person.name ? "text-slate-700" : "italic text-slate-400"
            }`}
          >
            {label}
          </span>
          <span className="shrink-0 text-[10px] text-slate-400">✏️</span>
        </button>
      )}
      {!editing && person.item_count != null && (
        <span className="-mt-1 text-[10px] text-slate-400">
          {person.item_count.toLocaleString()}장
        </span>
      )}
    </div>
  );
}

function GroupGrid({
  space,
  kind,
  id,
}: {
  space: Space;
  kind: "person";
  id: string;
}) {
  const q = useQuery({
    queryKey: ["album-items", space, kind, id],
    queryFn: () => api.personItems(space, id),
  });
  const items = useMemo(
    () => (q.data?.items ?? []).map((it) => ({ ...it, space })),
    [q.data, space],
  );
  if (q.isPending)
    return <p className="p-6 text-sm text-slate-400">불러오는 중…</p>;
  if (items.length === 0)
    return <p className="p-6 text-sm text-slate-400">사진이 없습니다.</p>;
  return <UniformPhotoGrid items={items} space={space} />;
}

function VideosGrid({ space }: { space: Space }) {
  const q = useQuery({
    queryKey: ["videos", space],
    queryFn: () => api.videos(space),
    staleTime: 5 * 60_000,
  });
  const items = useMemo(
    () => (q.data?.items ?? []).map((it) => ({ ...it, space })),
    [q.data, space],
  );
  if (q.isPending)
    return <p className="p-6 text-sm text-slate-400">불러오는 중…</p>;
  if (items.length === 0)
    return <p className="p-6 text-sm text-slate-400">비디오가 없습니다.</p>;
  // 일자별 헤더 + 우측 날짜 스크러버(사진 뷰어 일 뷰와 동일 감상 형태).
  return <DateGroupedGrid items={items} space={space} />;
}
