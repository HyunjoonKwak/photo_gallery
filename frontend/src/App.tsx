import { useEffect, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { api } from "./api/client";
import type { Space } from "./api/types";
import { useAuthStore } from "./store/auth";
import { selectBackDepth, useTimelineStore, type Section } from "./store/timeline";
import { useBackTrap } from "./hooks/useBackTrap";
import { LoginForm } from "./components/LoginForm";

// 라이브러리(공용/내사진/1차구역/타인) 전환 시: 스코프가 붙는 데이터 캐시만 버리고
// 세션·메타(me/system-info/zones/members/ops/trash)는 유지 — clear() 전체 초기화는
// 전환 복귀 때마다 모든 화면을 콜드로 만들었다.
const SCOPE_FREE_KEYS = new Set([
  "me",
  "system-info",
  "zones",
  "members",
  "ops",
  "trash",
]);

function dropScopedQueries(qc: QueryClient) {
  qc.removeQueries({
    predicate: (q) => !SCOPE_FREE_KEYS.has(String(q.queryKey[0])),
  });
}
import { ApiInfoPanel } from "./components/ApiInfoPanel";
import { TimelineScreen } from "./components/TimelineScreen";
import { OperationsPanel } from "./components/OperationsPanel";
import { BottomTabBar } from "./components/BottomTabBar";
import { BulkProgress } from "./components/BulkProgress";
import { Toasts } from "./components/Toasts";
import { PwaUpdater } from "./components/PwaUpdater";
import { NavControls } from "./components/NavControls";
import { ConflictDialogHost } from "./components/ConflictDialog";
import { ZoneManager } from "./components/ZoneManager";

// 상위 3영역 — 주 메뉴. 감상(사진/앨범)과 정리(폴더 분류)를 가른다.
export const SECTIONS: { section: Section; label: string; icon: string }[] = [
  { section: "viewer", label: "사진", icon: "🖼" },
  { section: "albums", label: "앨범", icon: "📔" },
  { section: "manage", label: "폴더 분류", icon: "🗂" },
];

/** 주 메뉴: 3영역 전환. 모바일은 하단 탭 바가 대신하므로 md 이상에서만 표시. */
function SectionToggle() {
  const section = useTimelineStore((s) => s.section);
  const setSection = useTimelineStore((s) => s.setSection);
  return (
    <nav className="hidden shrink-0 gap-0.5 sm:gap-1 md:flex">
      {SECTIONS.map((v) => (
        <button
          key={v.section}
          onClick={() => setSection(v.section)}
          title={v.label}
          className={`flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-2 py-1.5 text-sm font-medium transition-colors sm:px-3 ${
            section === v.section
              ? "bg-slate-800 text-white"
              : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
          }`}
        >
          <span className="text-base leading-none">{v.icon}</span>
          <span className="hidden md:inline">{v.label}</span>
        </button>
      ))}
    </nav>
  );
}

/** 사진 검색창: 파일명·폴더명·태그 키워드 — Enter로 검색 뷰 진입. */
function SearchBox() {
  const runSearch = useTimelineStore((s) => s.runSearch);
  const activeZone = useTimelineStore((s) => s.activeZone);
  const [value, setValue] = useState("");
  // 1차 구역은 Photos 검색 인덱스 밖이라 검색이 무의미 — 숨김.
  const viewedOwner = useTimelineStore((s) => s.viewedOwner);
  // 1차 구역(FileStation)과 타인 라이브러리는 DSM 검색 인덱스 대상이 아니어서
  // 빈 결과만 나온다(오해 소지) → 검색창 자체를 숨긴다.
  if (activeZone || viewedOwner) return null;
  const submit = () => {
    const q = value.trim();
    if (q) runSearch(q);
  };
  return (
    <div className="flex items-center gap-1 rounded-xl bg-slate-100 px-2 py-1">
      <span aria-hidden className="text-sm text-slate-400">
        🔍
      </span>
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
        }}
        placeholder="사진 검색"
        className="w-24 bg-transparent text-sm text-slate-700 outline-none placeholder:text-slate-400 focus:w-40 sm:w-32 sm:focus:w-48 transition-[width]"
      />
    </div>
  );
}

/** 라이브러리 셀렉터 (메뉴 재편 A안): "무엇을 볼지"를 한 축으로 —
 * 공용 사진 / 내 사진 / (관리자) 타인 사진. 기존의 범위(공용/개인) 칩과
 * 사용자 드롭다운을 통합해, 뷰에 따라 컨트롤이 사라지는 어색함을 없앤다.
 * 타인 라이브러리 선택 시 버튼이 주황색으로 바뀌어 배너와 함께 상태를 알린다.
 */
function LibrarySelector({ account, isAdmin }: { account: string; isAdmin: boolean }) {
  const space = useTimelineStore((s) => s.space);
  const viewedOwner = useTimelineStore((s) => s.viewedOwner);
  const activeZone = useTimelineStore((s) => s.activeZone);
  // 타인/1차 구역은 폴더 분류(정리)에서만 — 감상 영역엔 공용/내사진만.
  const section = useTimelineStore((s) => s.section);
  const selectLibrary = useTimelineStore((s) => s.selectLibrary);
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const membersQuery = useQuery({
    queryKey: ["members"],
    queryFn: api.members,
    enabled: isAdmin,
  });
  const members = (membersQuery.data?.members ?? []).filter(
    (m) => m.name !== account,
  );
  const zonesQuery = useQuery({ queryKey: ["zones"], queryFn: api.listZones });
  const zones = zonesQuery.data?.zones ?? [];

  const label = activeZone
    ? `📦 ${activeZone.label}`
    : viewedOwner
      ? `👥 ${viewedOwner}의 사진`
      : space === "team"
        ? "📚 공용 사진"
        : "👤 내 사진";

  const pick = (lib: {
    space: Space;
    owner: string | null;
    zone?: { id: string; label: string } | null;
  }) => {
    setOpen(false);
    selectLibrary(lib);
    // 라이브러리가 통째로 바뀜 — 스코프 데이터만 제거(세션·메타는 유지)
    dropScopedQueries(queryClient);
  };

  const itemCls = (active: boolean) =>
    `flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm ${
      active ? "bg-slate-100 font-semibold text-slate-800" : "text-slate-600 hover:bg-slate-50"
    }`;

  return (
    <div className="relative shrink-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-1.5 whitespace-nowrap rounded-xl px-3 py-1.5 text-sm font-semibold transition-colors ${
          activeZone
            ? "bg-indigo-600 text-white hover:bg-indigo-700"
            : viewedOwner
              ? "bg-amber-500 text-white hover:bg-amber-600"
              : "bg-slate-100 text-slate-800 hover:bg-slate-200"
        }`}
      >
        {label}
        <span className="text-xs opacity-60">▾</span>
      </button>
      {open && (
        <>
          {/* click-away layer */}
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-40 mt-1 w-56 rounded-xl border border-slate-200 bg-white p-1.5 shadow-lg">
            <button
              onClick={() => pick({ space: "team", owner: null })}
              className={itemCls(!viewedOwner && !activeZone && space === "team")}
            >
              📚 공용 사진
              <span className="ml-auto text-[10px] text-slate-400">가족 공유</span>
            </button>
            <button
              onClick={() => pick({ space: "personal", owner: null })}
              className={itemCls(!viewedOwner && !activeZone && space === "personal")}
            >
              👤 내 사진
            </button>
            {/* 타인/1차 구역/구역 관리는 폴더 분류에서만 (정리 전용 축) */}
            {section === "manage" && isAdmin && members.length > 0 && (
              <>
                <p className="px-3 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  관리자 · 구성원 사진
                </p>
                {members.map((m) => (
                  <button
                    key={m.name}
                    onClick={() => pick({ space: "personal", owner: m.name })}
                    className={itemCls(viewedOwner === m.name)}
                  >
                    👥 {m.name}의 사진
                    {!m.has_photos && (
                      <span className="ml-auto text-[10px] text-slate-400">
                        사진 없음
                      </span>
                    )}
                  </button>
                ))}
              </>
            )}
            {section === "manage" && (
              <>
                <p className="px-3 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  1차 구역 · 기기 백업
                </p>
                {zones.map((z) => (
                  <button
                    key={z.id}
                    onClick={() =>
                      pick({
                        space: "personal",
                        owner: null,
                        zone: { id: z.id, label: z.label },
                      })
                    }
                    className={itemCls(activeZone?.id === z.id)}
                  >
                    📦 {z.label}
                  </button>
                ))}
                <button
                  onClick={() => {
                    setOpen(false);
                    setManageOpen(true);
                  }}
                  className="mt-0.5 flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-xs text-indigo-600 hover:bg-indigo-50"
                >
                  ⚙️ 구역 관리…
                </button>
              </>
            )}
          </div>
        </>
      )}
      {manageOpen && <ZoneManager onClose={() => setManageOpen(false)} />}
    </div>
  );
}

/** High-contrast persistent banner while organizing someone else's photos —
 * the standard impersonation pattern (IMPROVEMENTS B-7): always visible,
 * one-click return.
 */
function ImpersonationBanner() {
  const viewedOwner = useTimelineStore((s) => s.viewedOwner);
  const selectLibrary = useTimelineStore((s) => s.selectLibrary);
  const queryClient = useQueryClient();
  if (!viewedOwner) return null;
  return (
    <div className="flex items-center justify-center gap-3 bg-amber-500 px-4 py-1.5 text-sm font-medium text-white">
      <span>
        보는 중: {viewedOwner}의 개인 폴더 (폴더 보기에서 지원 · 타임라인/분류/
        검색 제외) — 모든 작업이 기록됩니다
      </span>
      <button
        onClick={() => {
          selectLibrary({ space: "personal", owner: null });
          // 타인 데이터가 캐시에 남아 내 폴더가 사라져 보이는 문제 방지.
          dropScopedQueries(queryClient);
        }}
        className="rounded-lg bg-amber-600 px-2 py-0.5 text-xs hover:bg-amber-700"
      >
        내 사진으로 돌아가기
      </button>
    </div>
  );
}

/** 1차 구역(기기 백업) 열람 중임을 알리는 배너 — 임퍼소네이션(주황)과 구분되는
 * 인디고. "고른 사진을 내 타임라인(2차)으로 옮기세요" 안내 + 복귀. */
function ZoneBanner() {
  const activeZone = useTimelineStore((s) => s.activeZone);
  const selectLibrary = useTimelineStore((s) => s.selectLibrary);
  const queryClient = useQueryClient();
  if (!activeZone) return null;
  return (
    <div className="flex items-center justify-center gap-3 bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white">
      <span>
        1차 구역: {activeZone.label} · 타임라인에 안 나오는 백업 폴더입니다 —
        고른 사진을 <b>내 타임라인(2차)으로 이동/복사</b>하세요
      </span>
      <button
        onClick={() => {
          selectLibrary({ space: "personal", owner: null });
          dropScopedQueries(queryClient);
        }}
        className="rounded-lg bg-indigo-700 px-2 py-0.5 text-xs hover:bg-indigo-800"
      >
        내 사진으로 돌아가기
      </button>
    </div>
  );
}

/** 빌드 표식 + 뒤로가기 트랩 진단. 탭하면 현재 history 길이·센티넬 유무·
 * 스토어 뒤로가기 상태를 보여줘, 실기기에서 트랩이 왜 안 걸리는지 파악한다. */
function BuildBadge() {
  const [diag, setDiag] = useState<string | null>(null);
  const read = () => {
    const s = useTimelineStore.getState();
    const sentinel = Boolean(
      (history.state as { __nav?: boolean } | null)?.__nav,
    );
    let log: string[] = [];
    try {
      log = JSON.parse(localStorage.getItem("nav.dbg") || "[]") as string[];
    } catch {
      // ignore
    }
    setDiag(
      `build ${__BUILD_ID__}\n` +
        `history.length=${history.length}\n` +
        `sentinel=${sentinel}\n` +
        `backDepth=${selectBackDepth(s)}\n` +
        `navHistory=${s._navHistory.length} screen=${s.screenBackDepth}\n` +
        `standalone=${window.matchMedia("(display-mode: standalone)").matches}\n` +
        `── 이벤트 로그 ──\n` +
        (log.slice(-12).join("\n") || "(없음)"),
    );
  };
  return (
    <>
      <button
        onClick={() => (diag ? setDiag(null) : read())}
        title="빌드 버전 · 탭하면 뒤로가기 진단"
        className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-400"
      >
        {__BUILD_ID__}
      </button>
      {diag && (
        <div className="fixed inset-x-3 bottom-24 z-[60] mx-auto max-w-xs rounded-xl bg-slate-900/95 px-4 py-3 font-mono text-xs text-slate-100 shadow-xl">
          <div className="whitespace-pre-wrap text-left">{diag}</div>
          <div className="mt-2 flex justify-center gap-2">
            <button
              onClick={() => {
                try {
                  localStorage.removeItem("nav.dbg");
                } catch {
                  // ignore
                }
                setDiag(null);
              }}
              className="rounded bg-slate-700 px-2 py-1 text-[11px] text-slate-200"
            >
              로그 지우기
            </button>
            <button
              onClick={() => setDiag(null)}
              className="rounded bg-slate-700 px-2 py-1 text-[11px] text-slate-200"
            >
              닫기
            </button>
          </div>
        </div>
      )}
    </>
  );
}

export default function App() {
  const { user, setUser } = useAuthStore();
  const queryClient = useQueryClient();
  const [showApiInfo, setShowApiInfo] = useState(false);
  const [showOps, setShowOps] = useState(false);

  // 뒤로가기 트랩 — 로그인/세션 확인 게이팅보다 먼저(조기 반환 위) 걸어야
  // 앱을 열자마자 누른 첫 뒤로가기도 종료 확인이 동작한다.
  useBackTrap();

  // Restore session on load (cookie may still be valid after a refresh).
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: false,
  });

  useEffect(() => {
    if (meQuery.isSuccess) setUser(meQuery.data);
    if (meQuery.isError) setUser(null);
  }, [meQuery.isSuccess, meQuery.isError, meQuery.data, setUser]);

  const logout = useMutation({
    mutationFn: api.logout,
    onSettled: () => {
      setUser(null);
      queryClient.clear();
    },
  });

  if (meQuery.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-500">
        세션 확인 중...
      </div>
    );
  }

  if (!user) {
    return <LoginForm />;
  }

  return (
    <div className="flex h-screen flex-col bg-slate-50">
      <header
        data-no-boxselect
        className="shrink-0 border-b border-slate-200 bg-white"
      >
        {/* flex-wrap: 좁은 화면에서 두 줄로 자연 배치 (가로 스크롤 금지) */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-2 py-2 sm:px-4">
          <h1 className="hidden text-sm font-bold text-slate-800 lg:block">
            NAS 사진 정리
          </h1>
          <div className="hidden h-6 w-px bg-slate-200 lg:block" aria-hidden />
          <LibrarySelector account={user.account} isAdmin={user.role === "admin"} />
          <div className="hidden h-6 w-px bg-slate-200 sm:block" aria-hidden />
          <SectionToggle />
          <SearchBox />
          {user.mock_mode && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
              MOCK
            </span>
          )}
          {/* 빌드 표식 — 기기가 최신 코드를 받았는지 즉시 확인(캐시 진단).
           * 탭하면 뒤로가기 트랩 진단(히스토리/센티넬 상태)을 보여준다. */}
          <BuildBadge />
          <div className="ml-auto flex shrink-0 items-center gap-2 text-sm sm:gap-3">
            <button
              onClick={() => setShowOps((v) => !v)}
              className={`whitespace-nowrap rounded-lg px-2 py-1 text-xs ${
                showOps
                  ? "bg-slate-200 text-slate-700"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              작업 기록
            </button>
            <button
              onClick={() => setShowApiInfo((v) => !v)}
              title="DSM API 연결 정보"
              className={`hidden whitespace-nowrap rounded-lg px-2 py-1 text-xs lg:block ${
                showApiInfo
                  ? "bg-slate-200 text-slate-700"
                  : "text-slate-400 hover:text-slate-600"
              }`}
            >
              DSM 정보
            </button>
            <span className="hidden text-slate-600 md:inline">
              {user.account}
              <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                {user.role === "admin" ? "관리자" : "일반"}
              </span>
            </span>
            <button
              onClick={() => logout.mutate()}
              className="whitespace-nowrap rounded-lg border border-slate-300 bg-white px-2 py-1 text-slate-700 hover:bg-slate-50 sm:px-3"
            >
              로그아웃
            </button>
          </div>
        </div>
        {showApiInfo && (
          <div className="max-h-72 overflow-auto border-t border-slate-100 px-4 py-3">
            <ApiInfoPanel />
          </div>
        )}
      </header>

      <ImpersonationBanner />
      <ZoneBanner />

      {/* pb-14: 모바일 하단 탭 바 높이만큼 콘텐츠 영역 확보 */}
      <div className="min-h-0 flex-1 pb-14 md:pb-0">
        <TimelineScreen />
      </div>
      <BottomTabBar />
      {showOps && <OperationsPanel onClose={() => setShowOps(false)} />}
      <BulkProgress />
      <Toasts />
      <ConflictDialogHost />
      <PwaUpdater />
      <NavControls />
    </div>
  );
}
