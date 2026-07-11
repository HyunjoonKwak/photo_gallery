import { useTimelineStore, type ManageTab } from "../store/timeline";
import { FolderView } from "./FolderView";
import { DedupView } from "./DedupView";
import { OrganizeView } from "./organize/OrganizeView";
import { SearchView } from "./SearchView";
import { FolderPanel } from "./FolderPanel";

/** 폴더 분류(정리) 영역 — 우리 앱의 특색. 폴더 이동/복사/삭제 + 중복 정리 +
 * (헤더 검색으로 진입하는) 검색 결과. 공용/내사진/1차백업/타인 라이브러리를
 * 모두 여기서 다룬다. DnD·선택 액션바는 상위(TimelineScreen)가 소유. */
const MANAGE_TABS: { tab: ManageTab; label: string; icon: string }[] = [
  { tab: "folders", label: "폴더", icon: "📁" },
  { tab: "dedup", label: "중복 정리", icon: "🔁" },
  { tab: "junk", label: "정리", icon: "✨" },
];

export function ManageScreen() {
  const manageTab = useTimelineStore((s) => s.manageTab);
  const setManageTab = useTimelineStore((s) => s.setManageTab);
  const space = useTimelineStore((s) => s.space);

  return (
    <div className="flex h-full flex-col">
      <div
        data-no-boxselect
        className="flex shrink-0 items-center gap-1 border-b border-slate-200 bg-white px-3 py-1.5 sm:px-4"
      >
        {MANAGE_TABS.map((t) => (
          <button
            key={t.tab}
            onClick={() => setManageTab(t.tab)}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors sm:text-sm ${
              manageTab === t.tab
                ? "bg-slate-800 text-white"
                : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
            }`}
          >
            <span>{t.icon}</span>
            {t.label}
          </button>
        ))}
        {manageTab === "search" && (
          <span className="ml-1 rounded-lg bg-blue-50 px-2 py-1 text-xs text-blue-600">
            🔍 검색 결과
          </span>
        )}
      </div>

      <div className="min-h-0 flex-1">
        {manageTab === "folders" && <FolderView />}
        {manageTab === "dedup" && <DedupView key={space} />}
        {manageTab === "junk" && <OrganizeView />}
        {manageTab === "search" && (
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
