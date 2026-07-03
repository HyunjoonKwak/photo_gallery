import { useTimelineStore, type ViewMode } from "../store/timeline";

const TABS: { mode: ViewMode; label: string; icon: string }[] = [
  { mode: "timeline", label: "타임라인", icon: "📅" },
  { mode: "folders", label: "폴더", icon: "📁" },
  { mode: "classify", label: "분류", icon: "✨" },
  { mode: "dedup", label: "중복", icon: "🔁" },
];

/** Mobile-only bottom tab bar (사진앱 표준): 뷰 전환을 엄지가 닿는 하단에.
 * 데스크톱은 헤더의 ViewToggle을 그대로 사용한다. safe-area 패딩으로
 * iPhone 홈 인디케이터와 겹치지 않는다.
 */
export function BottomTabBar() {
  const viewMode = useTimelineStore((s) => s.viewMode);
  const setViewMode = useTimelineStore((s) => s.setViewMode);
  return (
    <nav
      data-no-boxselect
      className="fixed inset-x-0 bottom-0 z-30 flex border-t border-slate-200 bg-white/95 backdrop-blur md:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      {TABS.map((t) => (
        <button
          key={t.mode}
          onClick={() => setViewMode(t.mode)}
          className={`flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium ${
            viewMode === t.mode ? "text-blue-600" : "text-slate-400"
          }`}
        >
          <span className="text-lg leading-none">{t.icon}</span>
          {t.label}
        </button>
      ))}
    </nav>
  );
}
