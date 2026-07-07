import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, thumbnailUrl } from "../api/client";
import type { AlbumInfo } from "../api/types";
import { useTimelineStore } from "../store/timeline";
import { useToastStore } from "../store/toast";
import { UniformPhotoGrid } from "./timeline/UniformPhotoGrid";

/** 앨범(큐레이션 전용) — 사용자가 직접 만드는 Synology 네이티브 앨범(개인 공간).
 *
 * IA 재편(2026-07-07): 사람·장소·비디오는 감상 렌즈로 사진 뷰어로 옮겼고, 이
 * 영역은 사용자 큐레이션 전용. 앨범 생성/추가/삭제는 DSM NormalAlbum API로
 * 수행한다(write 경로는 실 NAS 검증 대기 — mock으론 완전 동작). */
export function AlbumsScreen() {
  const [open, setOpen] = useState<{ id: string; name: string } | null>(null);
  const setScreenBackDepth = useTimelineStore((s) => s.setScreenBackDepth);
  const registerBack = useTimelineStore((s) => s.registerBack);

  // 앨범 열람은 화면-로컬 드릴 → 뒤로가기 깊이에 보고 + 뒤로 핸들러 등록.
  useEffect(() => {
    setScreenBackDepth(open ? 1 : 0);
    if (!open) return;
    return registerBack(() => setOpen(null));
  }, [open, setScreenBackDepth, registerBack]);
  useEffect(() => () => setScreenBackDepth(0), [setScreenBackDepth]);

  return open ? (
    <AlbumDetail id={open.id} name={open.name} onBack={() => setOpen(null)} />
  ) : (
    <AlbumList onOpen={(a) => setOpen({ id: a.id, name: a.name })} />
  );
}

function AlbumList({ onOpen }: { onOpen: (a: AlbumInfo) => void }) {
  const qc = useQueryClient();
  const pushToast = useToastStore((s) => s.push);
  const q = useQuery({ queryKey: ["albums"], queryFn: api.albums });
  const albums = q.data?.albums ?? [];

  const createMut = useMutation({
    mutationFn: (name: string) => api.createAlbum(name),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["albums"] });
      pushToast(`앨범 "${res.album?.name}"을(를) 만들었습니다.`);
    },
    onError: () => pushToast("앨범 생성에 실패했습니다."),
  });

  const create = () => {
    const name = window.prompt("새 앨범 이름");
    if (name?.trim()) createMut.mutate(name.trim());
  };

  return (
    <div className="flex h-full flex-col">
      <div
        data-no-boxselect
        className="flex shrink-0 items-center justify-between gap-2 border-b border-slate-200 bg-white px-3 py-1.5 sm:px-4"
      >
        <span className="text-sm font-semibold text-slate-700">
          내 앨범{albums.length > 0 && ` (${albums.length})`}
        </span>
        <button
          onClick={create}
          disabled={createMut.isPending}
          className="rounded-lg border border-dashed border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-600 hover:border-slate-400 hover:text-slate-800 disabled:opacity-40"
        >
          ＋ 앨범 만들기
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {q.isPending ? (
          <p className="p-6 text-center text-sm text-slate-400">불러오는 중…</p>
        ) : albums.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="mb-3 text-5xl">📔</div>
            <h2 className="mb-1 text-base font-semibold text-slate-700">
              아직 앨범이 없습니다
            </h2>
            <p className="max-w-sm text-sm leading-relaxed text-slate-500">
              직접 고른 사진을 모아 앨범을 만들어 보세요. 만든 앨범은 Synology
              Photos 앱에도 그대로 보입니다. 사진은 폴더 분류에서 선택해 앨범에
              담을 수 있습니다.
            </p>
            <button
              onClick={create}
              className="mt-4 rounded-lg bg-slate-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
            >
              ＋ 첫 앨범 만들기
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap gap-3">
            {albums.map((a) => (
              <AlbumCard key={a.id} album={a} onOpen={() => onOpen(a)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function AlbumCard({
  album,
  onOpen,
}: {
  album: AlbumInfo;
  onOpen: () => void;
}) {
  const qc = useQueryClient();
  const pushToast = useToastStore((s) => s.push);
  const delMut = useMutation({
    mutationFn: () => api.deleteAlbum(album.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["albums"] });
      pushToast(`앨범 "${album.name}"을(를) 삭제했습니다.`);
    },
    onError: () => pushToast("앨범 삭제에 실패했습니다."),
  });
  const del = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (window.confirm(`앨범 "${album.name}"을(를) 삭제할까요?\n(사진 자체는 지워지지 않습니다.)`))
      delMut.mutate();
  };
  return (
    <button
      onClick={onOpen}
      title={album.name}
      className="group relative flex w-40 flex-col gap-1.5 rounded-xl p-2 text-left hover:bg-slate-100"
    >
      <div className="aspect-square w-full overflow-hidden rounded-lg bg-slate-200">
        {album.cover_item_id ? (
          <img
            src={thumbnailUrl(
              "personal",
              album.cover_item_id,
              album.cover_cache_key ?? "",
              "sm",
            )}
            alt={album.name}
            className="h-full w-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-4xl">
            📔
          </div>
        )}
      </div>
      <div className="flex items-center justify-between gap-1">
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-700">
          {album.name}
        </span>
        <span
          onClick={del}
          title="앨범 삭제"
          className="hidden shrink-0 rounded px-1 text-xs text-slate-400 hover:text-red-500 group-hover:inline"
        >
          🗑
        </span>
      </div>
      <span className="text-[10px] text-slate-400">
        {album.item_count != null ? `${album.item_count.toLocaleString()}장` : " "}
      </span>
    </button>
  );
}

function AlbumDetail({
  id,
  name,
  onBack,
}: {
  id: string;
  name: string;
  onBack: () => void;
}) {
  const q = useQuery({
    queryKey: ["album-items", id],
    queryFn: () => api.albumItems(id),
  });
  const items = (q.data?.items ?? []).map((it) => ({
    ...it,
    space: "personal" as const,
  }));
  return (
    <div className="flex h-full flex-col">
      <div
        data-no-boxselect
        className="flex shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-3 py-1.5 sm:px-4"
      >
        <button
          onClick={onBack}
          className="rounded px-1.5 py-0.5 text-sm text-blue-600 hover:bg-slate-100"
        >
          ‹ 뒤로
        </button>
        <span className="text-sm font-semibold text-slate-700">{name}</span>
        {!q.isPending && (
          <span className="text-xs text-slate-400">({items.length})</span>
        )}
      </div>
      <div className="min-h-0 flex-1">
        {q.isPending ? (
          <p className="p-6 text-center text-sm text-slate-400">불러오는 중…</p>
        ) : items.length === 0 ? (
          <p className="p-6 text-center text-sm text-slate-400">
            이 앨범에는 아직 사진이 없습니다. 폴더 분류에서 사진을 선택해
            앨범에 담아 보세요.
          </p>
        ) : (
          <UniformPhotoGrid items={items} space="personal" />
        )}
      </div>
    </div>
  );
}
