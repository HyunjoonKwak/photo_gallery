import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api/client";
import type { Space } from "./api/types";
import { useAuthStore } from "./store/auth";
import { useTimelineStore } from "./store/timeline";
import { LoginForm } from "./components/LoginForm";
import { ApiInfoPanel } from "./components/ApiInfoPanel";
import { TimelineScreen } from "./components/TimelineScreen";
import { Toasts } from "./components/Toasts";

const TABS: { space: Space; label: string }[] = [
  { space: "team", label: "공용 폴더" },
  { space: "personal", label: "내 개인 폴더" },
];

function SpaceTabs() {
  const space = useTimelineStore((s) => s.space);
  const setSpace = useTimelineStore((s) => s.setSpace);
  return (
    <nav className="flex gap-1 rounded-xl bg-slate-100 p-1">
      {TABS.map((tab) => (
        <button
          key={tab.space}
          onClick={() => setSpace(tab.space)}
          className={`rounded-lg px-3 py-1 text-sm font-medium transition-colors ${
            space === tab.space
              ? "bg-white text-slate-800 shadow-sm"
              : "text-slate-500 hover:text-slate-700"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}

export default function App() {
  const { user, setUser } = useAuthStore();
  const queryClient = useQueryClient();
  const [showApiInfo, setShowApiInfo] = useState(false);

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
        <div className="flex items-center gap-4 px-4 py-2">
          <h1 className="text-sm font-bold text-slate-800">NAS 사진 정리</h1>
          <SpaceTabs />
          {user.mock_mode && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
              MOCK 데이터
            </span>
          )}
          <div className="ml-auto flex items-center gap-3 text-sm">
            <button
              onClick={() => setShowApiInfo((v) => !v)}
              title="DSM API 연결 정보"
              className={`rounded-lg px-2 py-1 text-xs ${
                showApiInfo
                  ? "bg-slate-200 text-slate-700"
                  : "text-slate-400 hover:text-slate-600"
              }`}
            >
              DSM 정보
            </button>
            <span className="text-slate-600">
              {user.account}
              <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                {user.role === "admin" ? "관리자" : "일반"}
              </span>
            </span>
            <button
              onClick={() => logout.mutate()}
              className="rounded-lg border border-slate-300 px-3 py-1 hover:bg-slate-50"
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

      <div className="min-h-0 flex-1">
        <TimelineScreen />
      </div>
      <Toasts />
    </div>
  );
}
