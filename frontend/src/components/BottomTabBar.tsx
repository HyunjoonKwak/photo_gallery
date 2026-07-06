import { useTimelineStore, type Section } from "../store/timeline";

const TABS: { section: Section; label: string; icon: string }[] = [
  { section: "viewer", label: "사진", icon: "🖼" },
  { section: "albums", label: "앨범", icon: "📔" },
  { section: "manage", label: "폴더 분류", icon: "🗂" },
];

/** Mobile-only bottom tab bar (사진앱 표준): 3영역 전환을 엄지가 닿는 하단에.
 * 데스크톱은 헤더의 SectionToggle을 그대로 사용한다. safe-area 패딩으로
 * iPhone 홈 인디케이터와 겹치지 않는다.
 */
export function BottomTabBar() {
  const section = useTimelineStore((s) => s.section);
  const setSection = useTimelineStore((s) => s.setSection);
  return (
    <nav
      data-no-boxselect
      className="fixed inset-x-0 bottom-0 z-30 flex border-t border-slate-200 bg-white/95 backdrop-blur md:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      {TABS.map((t) => (
        <button
          key={t.section}
          onClick={() => setSection(t.section)}
          className={`flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium ${
            section === t.section ? "text-blue-600" : "text-slate-400"
          }`}
        >
          <span className="text-lg leading-none">{t.icon}</span>
          {t.label}
        </button>
      ))}
    </nav>
  );
}
