import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useToastStore } from "../../store/toast";

/** 선택한 사진들을 기존 앨범에 담거나 새 앨범을 만들어 담는 모달.
 * 앨범은 개인 공간 전용이라, 호출부(SelectionActionBar)에서 1차 구역·타인
 * 라이브러리일 때는 노출하지 않는다. */
export function AlbumPickerDialog({
  count,
  itemIds,
  onClose,
  onDone,
}: {
  count: number;
  itemIds: string[];
  onClose: () => void;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const pushToast = useToastStore((s) => s.push);
  const q = useQuery({ queryKey: ["albums"], queryFn: api.albums });
  const albums = q.data?.albums ?? [];

  const finish = (msg: string) => {
    qc.invalidateQueries({ queryKey: ["albums"] });
    qc.invalidateQueries({ queryKey: ["album-items"] });
    pushToast(msg);
    onDone();
    onClose();
  };

  const addMut = useMutation({
    mutationFn: (albumId: string) => api.addToAlbum(albumId, itemIds),
    onSuccess: (res) => finish(`앨범에 ${res.added}장을 담았습니다.`),
    onError: () => pushToast("앨범에 담지 못했습니다."),
  });
  const createMut = useMutation({
    mutationFn: (name: string) => api.createAlbum(name, itemIds),
    onSuccess: (res) =>
      finish(`"${res.album?.name}" 앨범을 만들고 ${res.added}장을 담았습니다.`),
    onError: () => pushToast("앨범 생성에 실패했습니다."),
  });
  const busy = addMut.isPending || createMut.isPending;

  const newAlbum = () => {
    const name = window.prompt(`${count}장을 담을 새 앨범 이름`);
    if (name?.trim()) createMut.mutate(name.trim());
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[80vh] w-full max-w-sm flex-col rounded-2xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-800">
            {count}장을 앨범에 담기
          </h3>
          <button
            onClick={onClose}
            className="rounded-full px-2 py-0.5 text-slate-400 hover:bg-slate-100"
          >
            ✕
          </button>
        </div>

        <button
          onClick={newAlbum}
          disabled={busy}
          className="m-2 shrink-0 rounded-lg border border-dashed border-slate-300 px-3 py-2 text-sm font-medium text-slate-600 hover:border-slate-400 hover:text-slate-800 disabled:opacity-40"
        >
          ＋ 새 앨범 만들어 담기
        </button>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {q.isPending ? (
            <p className="p-4 text-center text-sm text-slate-400">불러오는 중…</p>
          ) : albums.length === 0 ? (
            <p className="p-4 text-center text-sm text-slate-400">
              기존 앨범이 없습니다. 위에서 새 앨범을 만들어 담아 보세요.
            </p>
          ) : (
            <ul className="flex flex-col">
              {albums.map((a) => (
                <li key={a.id}>
                  <button
                    onClick={() => addMut.mutate(a.id)}
                    disabled={busy}
                    className="flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-100 disabled:opacity-40"
                  >
                    <span className="min-w-0 flex-1 truncate text-slate-700">
                      📔 {a.name}
                    </span>
                    <span className="shrink-0 text-xs text-slate-400">
                      {a.item_count != null ? `${a.item_count}장` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
