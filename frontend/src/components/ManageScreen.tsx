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

  return (
    <div className="flex h-full flex-col">
      {manageTab !== "search" && (
        <div
          data-no-boxselect
          className="flex shrink-0 flex-wrap items-center gap-1 border-b border-slate-200 bg-white px-3 py-1.5 sm:px-4"
        >
          {MANAGE_TABS.map((t) => (
            <button
              key={t.tab}
              onClick={() => setManageTab(t.tab)}
              title={t.hint}
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
        </div>
      )}

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
