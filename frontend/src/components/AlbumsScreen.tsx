import { useToastStore } from "../store/toast";

/** 앨범(큐레이션 전용) — 사용자가 직접 만드는 Synology 네이티브 앨범.
 *
 * IA 재편(2026-07-07): 사람·장소·비디오는 AI 자동 그룹이라 "앨범"이 아닌 감상
 * 렌즈로 사진 뷰어(ViewerScreen)로 옮겼고, 이 영역은 사용자 큐레이션 전용이 됐다.
 * 앨범 "생성/추가"는 DSM Photo Album API 연동이 선행(실 NAS 프로브)이라 2단계에서
 * 붙인다. 지금은 방향을 드러내는 빈 상태 + 안내(생성 버튼은 준비 중). */
export function AlbumsScreen() {
  const pushToast = useToastStore((s) => s.push);
  return (
    <div className="flex h-full flex-col">
      <div
        data-no-boxselect
        className="flex shrink-0 items-center justify-between gap-2 border-b border-slate-200 bg-white px-3 py-1.5 sm:px-4"
      >
        <span className="text-sm font-semibold text-slate-700">내 앨범</span>
        <button
          onClick={() =>
            pushToast("앨범 만들기는 준비 중입니다 (DSM 앨범 연동 예정).")
          }
          title="준비 중 — DSM 앨범 API 연동 후 활성화"
          className="cursor-not-allowed rounded-lg border border-dashed border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-400"
        >
          ＋ 앨범 만들기
        </button>
      </div>

      <div className="flex min-h-0 flex-1 items-center justify-center p-6">
        <div className="max-w-sm text-center">
          <div className="mb-3 text-5xl">📔</div>
          <h2 className="mb-1 text-base font-semibold text-slate-700">
            내가 만드는 앨범
          </h2>
          <p className="text-sm leading-relaxed text-slate-500">
            직접 고른 사진을 모아 앨범으로 만드는 기능을 준비하고 있습니다.
            만든 앨범은 Synology Photos 앱에도 그대로 보입니다.
          </p>
          <p className="mt-3 text-xs text-slate-400">
            사람·장소·비디오는 <b>사진</b> 메뉴의 렌즈로 옮겼습니다.
          </p>
        </div>
      </div>
    </div>
  );
}
