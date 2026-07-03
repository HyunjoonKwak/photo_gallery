import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api/client";
import type { Space } from "./api/types";
import { useAuthStore } from "./store/auth";
import { useTimelineStore, type ViewMode } from "./store/timeline";
import { LoginForm } from "./components/LoginForm";
import { ApiInfoPanel } from "./components/ApiInfoPanel";
import { TimelineScreen } from "./components/TimelineScreen";
import { OperationsPanel } from "./components/OperationsPanel";
import { BulkProgress } from "./components/BulkProgress";
import { Toasts } from "./components/Toasts";

// 범위(어느 저장소) — '폴더'라는 단어와 충돌하지 않도록 스코프 이름만 사용.
const SCOPES: { space: Space; label: string }[] = [
  { space: "team", label: "공용" },
  { space: "personal", label: "개인" },
];

// 보기(무엇을 볼지) — 주 메뉴. 아이콘으로 성격을 구분.
const VIEWS: { mode: ViewMode; label: string; icon: string }[] = [
  { mode: "timeline", label: "타임라인", icon: "📅" },
  { mode: "folders", label: "폴더", icon: "📁" },
  { mode: "classify", label: "분류", icon: "✨" },
  { mode: "dedup", label: "중복 정리", icon: "🔁" },
];

/** 주 메뉴: 보기 방식(타임라인/폴더/중복 정리) 전환.
 * 모바일: 아이콘만(라벨은 sm 이상) — 좁은 화면에서 텍스트가 꺾이지 않게. */
function ViewToggle() {
  const viewMode = useTimelineStore((s) => s.viewMode);
  const setViewMode = useTimelineStore((s) => s.setViewMode);
  return (
    <nav className="flex shrink-0 gap-0.5 sm:gap-1">
      {VIEWS.map((v) => (
        <button
          key={v.mode}
          onClick={() => setViewMode(v.mode)}
          title={v.label}
          className={`flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-2 py-1.5 text-sm font-medium transition-colors sm:px-3 ${
            viewMode === v.mode
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
  const [value, setValue] = useState("");
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

/** 스코프 전환: 현재 보기를 어느 저장소(공용/개인)에 적용할지. 보기 메뉴와
 * 성격이 다르므로 '범위:' 라벨 + 구분된 세그먼트로 위계를 드러낸다. 폴더 보기는
 * 공용·개인 트리를 동시에 보여줘 스코프가 무의미하므로 숨긴다. */
function ScopeSwitcher() {
  const space = useTimelineStore((s) => s.space);
  const setSpace = useTimelineStore((s) => s.setSpace);
  const viewMode = useTimelineStore((s) => s.viewMode);
  if (viewMode === "folders") return null;
  return (
    <div className="flex shrink-0 items-center gap-2">
      <div className="hidden h-6 w-px bg-slate-200 sm:block" aria-hidden />
      <span className="hidden text-xs font-medium text-slate-400 sm:inline">
        범위
      </span>
      <nav className="flex gap-1 rounded-xl bg-slate-100 p-1">
        {SCOPES.map((s) => (
          <button
            key={s.space}
            onClick={() => setSpace(s.space)}
            className={`whitespace-nowrap rounded-lg px-2 py-1 text-sm font-medium transition-colors sm:px-3 ${
              space === s.space
                ? "bg-white text-slate-800 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {s.label}
          </button>
        ))}
      </nav>
    </div>
  );
}

/** Admin-only member picker (spec 4.5): choose whose photos to organize.
 * Actions taken while impersonating are audit-logged with target_user.
 */
function MemberSelect({ account }: { account: string }) {
  const viewedOwner = useTimelineStore((s) => s.viewedOwner);
  const setViewedOwner = useTimelineStore((s) => s.setViewedOwner);
  const membersQuery = useQuery({ queryKey: ["members"], queryFn: api.members });
  const members = membersQuery.data?.members ?? [];

  return (
    <select
      value={viewedOwner ?? account}
      onChange={(e) =>
        setViewedOwner(e.target.value === account ? null : e.target.value)
      }
      title="가족 구성원 선택"
      className="rounded-lg border border-slate-300 px-2 py-1 text-sm text-slate-700"
    >
      <option value={account}>내 사진</option>
      {members
        .filter((m) => m !== account)
        .map((m) => (
          <option key={m} value={m}>
            {m}의 사진
          </option>
        ))}
    </select>
  );
}

/** High-contrast persistent banner while organizing someone else's photos —
 * the standard impersonation pattern (IMPROVEMENTS B-7): always visible,
 * one-click return.
 */
function ImpersonationBanner() {
  const viewedOwner = useTimelineStore((s) => s.viewedOwner);
  const setViewedOwner = useTimelineStore((s) => s.setViewedOwner);
  if (!viewedOwner) return null;
  return (
    <div className="flex items-center justify-center gap-3 bg-amber-500 px-4 py-1.5 text-sm font-medium text-white">
      <span>보는 중: {viewedOwner}의 개인 폴더 — 모든 작업이 기록됩니다</span>
      <button
        onClick={() => setViewedOwner(null)}
        className="rounded-lg bg-amber-600 px-2 py-0.5 text-xs hover:bg-amber-700"
      >
        내 보기로 돌아가기
      </button>
    </div>
  );
}

export default function App() {
  const { user, setUser } = useAuthStore();
  const queryClient = useQueryClient();
  const [showApiInfo, setShowApiInfo] = useState(false);
  const [showOps, setShowOps] = useState(false);

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
          <ViewToggle />
          <ScopeSwitcher />
          <SearchBox />
          {user.role === "admin" && <MemberSelect account={user.account} />}
          {user.mock_mode && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
              MOCK
            </span>
          )}
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
              className="whitespace-nowrap rounded-lg border border-slate-300 px-2 py-1 hover:bg-slate-50 sm:px-3"
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

      <div className="min-h-0 flex-1">
        <TimelineScreen />
      </div>
      {showOps && <OperationsPanel onClose={() => setShowOps(false)} />}
      <BulkProgress />
      <Toasts />
    </div>
  );
}
