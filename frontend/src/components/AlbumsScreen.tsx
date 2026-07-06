import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, thumbnailUrl } from "../api/client";
import type { PersonInfo, Space } from "../api/types";
import { useTimelineStore, type AlbumKind } from "../store/timeline";
import { UniformPhotoGrid } from "./timeline/UniformPhotoGrid";
import { PlacesRegionView } from "./PlacesRegionView";

/** 앨범(감상) — 사람/장소/비디오. Synology Photos 내장 AI 그룹(얼굴·GPS)과
 * 라이브러리 전체 비디오를 순수 뷰어로 브라우즈. 정리는 폴더 분류에서. */
const KINDS: { k: AlbumKind; label: string; icon: string }[] = [
  { k: "people", label: "사람", icon: "👤" },
  { k: "places", label: "장소", icon: "📍" },
  { k: "videos", label: "비디오", icon: "🎬" },
];

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
            <GroupGrid space={space} kind="person" id={groupId} />
          ) : (
            <PeopleGrid space={space} onOpen={openGroup} />
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
            onOpen={() => onOpen(p.id, p.name || "이름 없는 인물")}
          />
        ))}
      </div>
    </div>
  );
}

function PersonCard({
  person,
  onOpen,
}: {
  person: PersonInfo;
  onOpen: () => void;
}) {
  const label = person.name || "이름 없는 인물";
  return (
    <button
      onClick={onOpen}
      title={label}
      className="flex w-24 flex-col items-center gap-1.5 rounded-xl p-2 hover:bg-slate-100"
    >
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
      <span
        className={`w-full truncate text-center text-xs ${
          person.name ? "text-slate-700" : "italic text-slate-400"
        }`}
      >
        {label}
      </span>
      {person.item_count != null && (
        <span className="-mt-1 text-[10px] text-slate-400">
          {person.item_count.toLocaleString()}장
        </span>
      )}
    </button>
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
  return <UniformPhotoGrid items={items} space={space} />;
}
