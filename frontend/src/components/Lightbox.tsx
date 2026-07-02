import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, thumbnailUrl } from "../api/client";
import { useTimelineStore } from "../store/timeline";
import { useFileOps } from "../hooks/useFileOps";
import { formatBytes } from "../lib/dates";
import { FolderPickerDialog } from "./timeline/FolderPickerDialog";

/** EXIF field order + Korean labels for the info panel. */
const EXIF_LABELS: [string, string][] = [
  ["camera", "카메라"],
  ["lens", "렌즈"],
  ["aperture", "조리개"],
  ["exposure_time", "셔터 속도"],
  ["iso", "ISO"],
  ["focal_length", "초점 거리"],
];

const SHORTCUTS: [string, string][] = [
  ["← →", "이전 / 다음 사진"],
  ["i", "정보 패널 열기/닫기"],
  ["Delete", "휴지통으로 이동 (다음 사진으로 진행)"],
  ["ESC", "닫기"],
  ["Shift + ?", "단축키 도움말"],
];

/** Lightbox (spec 9.4, IMPROVEMENTS B-5):
 * ←/→ stepping, `i` info side panel (state persists across steps), Delete →
 * trash + auto-advance (continuous culling), Shift+? shortcut help, neighbor
 * prefetch, and in-viewer organize actions.
 */
export function Lightbox() {
  const item = useTimelineStore((s) =>
    s.lightboxId ? (s.itemsById.get(s.lightboxId) ?? null) : null,
  );
  const globalSpace = useTimelineStore((s) => s.space);
  const space = item?.space ?? globalSpace;
  const ops = useFileOps();
  const [showInfo, setShowInfo] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showMove, setShowMove] = useState(false);

  // Folder path / EXIF / location — fetched only while the panel is open
  // (list APIs stay light; details ride on Browse.Item "get").
  const detailQuery = useQuery({
    queryKey: ["item-detail", space, item?.id],
    queryFn: () => api.itemDetail(space, item!.id),
    enabled: showInfo && item != null,
    staleTime: 5 * 60_000,
  });
  const detail = detailQuery.data;

  const deleteAndAdvance = () => {
    const s = useTimelineStore.getState();
    const id = s.lightboxId;
    if (!id) return;
    // Pick the next photo before the current one disappears; fall back to the
    // previous one at the end of the list; close when it was the last photo.
    const idx = s.orderedIds.indexOf(id);
    const next = s.orderedIds[idx + 1] ?? s.orderedIds[idx - 1] ?? null;
    ops.remove([id], () => {
      const store = useTimelineStore.getState();
      if (next) store.openLightbox(next);
      else store.closeLightbox();
    });
  };

  // Keyboard: arrows / i / Delete / ? (ESC is handled at screen level).
  useEffect(() => {
    if (!item) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") useTimelineStore.getState().stepLightbox(1);
      else if (e.key === "ArrowLeft") useTimelineStore.getState().stepLightbox(-1);
      else if (e.key === "i" || e.key === "I") setShowInfo((v) => !v);
      else if (e.key === "Delete" || e.key === "Backspace") deleteAndAdvance();
      else if (e.key === "?") setShowHelp((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item]);

  // Prefetch neighbors so stepping feels instant.
  useEffect(() => {
    if (!item) return;
    const s = useTimelineStore.getState();
    const idx = s.orderedIds.indexOf(item.id);
    for (const i of [idx - 1, idx + 1]) {
      const neighbor = s.itemsById.get(s.orderedIds[i] ?? "");
      if (neighbor) {
        new Image().src = thumbnailUrl(
          neighbor.space ?? space,
          neighbor.id,
          neighbor.cache_key,
          "xl",
        );
      }
    }
  }, [item, space]);

  if (!item) return null;

  const close = () => useTimelineStore.getState().closeLightbox();
  const navBtn =
    "absolute top-1/2 -translate-y-1/2 rounded-full bg-black/50 p-3 text-2xl text-white/80 hover:text-white hover:bg-black/70";

  return (
    <div
      data-no-boxselect
      className="fixed inset-0 z-50 flex bg-black/95"
      onClick={close}
    >
      <div className="relative flex min-w-0 flex-1 items-center justify-center">
        <img
          src={thumbnailUrl(space, item.id, item.cache_key, "xl")}
          alt={item.filename}
          onClick={(e) => e.stopPropagation()}
          className="max-h-[90vh] max-w-[94%] object-contain"
        />
        <button
          aria-label="이전 사진"
          className={`${navBtn} left-4`}
          onClick={(e) => {
            e.stopPropagation();
            useTimelineStore.getState().stepLightbox(-1);
          }}
        >
          ‹
        </button>
        <button
          aria-label="다음 사진"
          className={`${navBtn} right-4`}
          onClick={(e) => {
            e.stopPropagation();
            useTimelineStore.getState().stepLightbox(1);
          }}
        >
          ›
        </button>

        {/* Top-right controls */}
        <div
          className="absolute right-4 top-4 flex gap-2"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => setShowMove(true)}
            title="폴더로 이동"
            className="rounded-full bg-black/50 px-3 py-2 text-sm text-white/80 hover:bg-black/70 hover:text-white"
          >
            이동
          </button>
          <button
            onClick={deleteAndAdvance}
            title="휴지통으로 이동 (Delete)"
            className="rounded-full bg-black/50 px-3 py-2 text-sm text-red-300 hover:bg-black/70 hover:text-red-200"
          >
            삭제
          </button>
          <button
            onClick={() => setShowInfo((v) => !v)}
            title="정보 (i)"
            className={`rounded-full px-3 py-2 text-sm ${
              showInfo
                ? "bg-white/90 text-slate-800"
                : "bg-black/50 text-white/80 hover:text-white"
            }`}
          >
            정보
          </button>
          <button
            aria-label="닫기"
            className="rounded-full bg-black/50 px-3 py-2 text-sm text-white/80 hover:text-white"
            onClick={close}
          >
            ✕
          </button>
        </div>

        <div
          className="absolute bottom-0 left-0 right-0 flex justify-center gap-4 bg-gradient-to-t from-black/80 to-transparent px-4 py-3 text-xs text-slate-300"
          onClick={(e) => e.stopPropagation()}
        >
          <span className="font-medium text-white">{item.filename}</span>
          <span className="text-slate-400">Shift+? 단축키</span>
        </div>
      </div>

      {/* EXIF/info side panel — slides in from the right, persists across steps */}
      {showInfo && (
        <aside
          className="w-72 shrink-0 overflow-y-auto bg-slate-900 px-5 py-6 text-sm text-slate-300"
          onClick={(e) => e.stopPropagation()}
        >
          <h3 className="mb-4 text-base font-semibold text-white">정보</h3>
          <dl className="space-y-3">
            <InfoRow label="파일명" value={item.filename} />
            <InfoRow label="촬영일시" value={item.taken_at.replace("T", " ")} />
            <InfoRow label="해상도" value={`${item.width} × ${item.height}`} />
            {item.size != null && (
              <InfoRow label="용량" value={formatBytes(item.size)} />
            )}
            <InfoRow label="공간" value={space === "team" ? "공용" : "개인"} />
            <InfoRow
              label="폴더"
              value={
                detail?.folder ??
                item.folder ??
                (detailQuery.isPending ? "불러오는 중…" : "(정보 없음)")
              }
            />
          </dl>

          {/* EXIF + location (on-demand) */}
          {detailQuery.isPending && (
            <p className="mt-5 text-xs text-slate-500">상세 정보 불러오는 중…</p>
          )}
          {detailQuery.isError && (
            <p className="mt-5 text-xs text-red-400">
              상세 정보를 불러오지 못했습니다.
            </p>
          )}
          {detail && (
            <>
              {Object.keys(detail.exif).length > 0 && (
                <>
                  <h4 className="mb-2 mt-6 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    촬영 정보
                  </h4>
                  <dl className="space-y-3">
                    {EXIF_LABELS.map(
                      ([key, label]) =>
                        detail.exif[key] && (
                          <InfoRow key={key} label={label} value={detail.exif[key]} />
                        ),
                    )}
                  </dl>
                </>
              )}
              {detail.address && (
                <>
                  <h4 className="mb-2 mt-6 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    위치
                  </h4>
                  <p className="text-sm text-slate-300">📍 {detail.address}</p>
                </>
              )}
              {Object.keys(detail.exif).length === 0 && !detail.address && (
                <p className="mt-5 text-xs text-slate-500">
                  이 사진에는 EXIF/위치 정보가 없습니다.
                </p>
              )}
            </>
          )}
        </aside>
      )}

      {/* In-viewer move (spec 9.4: 라이트박스에서도 정리 가능) */}
      {showMove && (
        <div onClick={(e) => e.stopPropagation()}>
          <FolderPickerDialog
            mode="move"
            count={1}
            onClose={() => setShowMove(false)}
            onConfirm={(folder, copyMode) => {
              setShowMove(false);
              ops.move([item.id], folder.id, copyMode);
            }}
          />
        </div>
      )}

      {/* Shortcut help overlay */}
      {showHelp && (
        <div
          className="absolute inset-0 z-10 flex items-center justify-center"
          onClick={(e) => {
            e.stopPropagation();
            setShowHelp(false);
          }}
        >
          <div className="rounded-2xl bg-slate-900/95 p-6 shadow-xl">
            <h3 className="mb-3 text-sm font-bold text-white">키보드 단축키</h3>
            <table className="text-sm text-slate-300">
              <tbody>
                {SHORTCUTS.map(([key, desc]) => (
                  <tr key={key}>
                    <td className="pr-6 font-mono text-blue-300">{key}</td>
                    <td className="py-0.5">{desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-0.5 break-all text-slate-200">{value}</dd>
    </div>
  );
}
