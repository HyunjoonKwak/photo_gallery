import {
  SHOW_MANAGE_TOOLS,
  useTimelineStore,
  type ManageTab,
} from "../store/timeline";
import { FolderView } from "./FolderView";
import { DedupView } from "./DedupView";
import { OrganizeView } from "./organize/OrganizeView";
import { SearchView } from "./SearchView";
import { FolderPanel } from "./FolderPanel";
import { useGalleryCapabilities } from "../hooks/useGalleryCapabilities";

/** 정리 영역 — 우리 앱의 특색. 폴더 이동/복사/삭제 + 정리 도우미(마법사) +
 * 중복 정리 + (헤더 검색으로 진입하는) 검색 결과. 가족/내사진/기기백업/타인
 * 라이브러리를 모두 여기서 다룬다. DnD·선택 액션바는 상위(TimelineScreen) 소유.
 * 탭 순서 = 위계(IA 4단계): 도우미가 대표 정리 흐름, 중복 정리는 고급 도구. */
const ALL_MANAGE_TABS: {
  tab: ManageTab;
  label: string;
  icon: string;
  hint?: string;
}[] = [
  { tab: "folders", label: "폴더", icon: "📁" },
  { tab: "junk", label: "정리 도우미", icon: "✨" },
  {
    tab: "dedup",
    label: "중복 정리",
    icon: "🔁",
    hint: "중복 사진만 따로 정리 — 정리 도우미 1단계와 같은 기능(가족 공간도 지원)",
  },
];

// NAS 웹앱에는 폴더 정리만 남긴다. 무거운 판정 — 잡동사니·중복 — 은 전량
// 사본이 있는 맥의 Photo Desk 몫이다(ECOSYSTEM.md 5절).
const MANAGE_TABS = ALL_MANAGE_TABS.filter(
  (t) => SHOW_MANAGE_TOOLS || t.tab === "folders",
);

export function ManageScreen() {
  const manageTab = useTimelineStore((s) => s.manageTab);
  const setManageTab = useTimelineStore((s) => s.setManageTab);
  const space = useTimelineStore((s) => s.space);
  const { capabilities, galleryWriteMode, isError } = useGalleryCapabilities();
  const visibleTabs = MANAGE_TABS.filter(
    (t) => capabilities.physical_mutations || t.tab === "folders",
  );
  const effectiveTab =
    !capabilities.physical_mutations && manageTab !== "search"
      ? "folders"
      : manageTab;

  return (
    <div className="flex h-full flex-col">
      {!capabilities.physical_mutations && (
        <div className="shrink-0 border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800">
          {isError
            ? "서버 권한을 확인할 수 없어 파일 작업을 안전하게 숨겼습니다."
            : galleryWriteMode === "drain"
              ? "전환 유예 중입니다. 새 파일·폴더 작업은 Photo Desk에서 하고, 기존 작업 복구만 가능합니다."
              : "원본 읽기 전용입니다. 이 화면에서는 폴더를 열람할 수만 있습니다."}
        </div>
      )}
      {manageTab !== "search" && (
        <div
          data-no-boxselect
          className="flex shrink-0 flex-wrap items-center gap-1 border-b border-slate-200 bg-white px-3 py-1.5 sm:px-4"
        >
          {visibleTabs.map((t) => (
            <button
              key={t.tab}
              onClick={() => setManageTab(t.tab)}
              title={t.hint}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors sm:text-sm ${
                effectiveTab === t.tab
                  ? "bg-slate-800 text-white"
                  : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
              }`}
            >
              <span>{t.icon}</span>
              {t.label}
            </button>
          ))}
        </div>
      )}

      <div className="min-h-0 flex-1">
        {effectiveTab === "folders" && <FolderView />}
        {effectiveTab === "dedup" && <DedupView key={space} />}
        {effectiveTab === "junk" && <OrganizeView />}
        {effectiveTab === "search" && (
          <div className="flex h-full">
            <FolderPanel />
            <main className="relative min-w-0 flex-1">
              <SearchView key={space} />
            </main>
          </div>
        )}
      </div>
    </div>
  );
}
