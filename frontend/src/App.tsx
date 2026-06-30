import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api/client";
import { useAuthStore } from "./store/auth";
import { LoginForm } from "./components/LoginForm";
import { ApiInfoPanel } from "./components/ApiInfoPanel";

export default function App() {
  const { user, setUser } = useAuthStore();
  const queryClient = useQueryClient();

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
      <div className="min-h-screen flex items-center justify-center text-slate-500">
        세션 확인 중...
      </div>
    );
  }

  if (!user) {
    return <LoginForm />;
  }

  return (
    <div className="min-h-screen bg-slate-100">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between">
          <h1 className="font-semibold text-slate-800">NAS 사진 정리</h1>
          <div className="flex items-center gap-3 text-sm">
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
      </header>

      <main className="max-w-4xl mx-auto px-4 py-6 space-y-4">
        <section className="bg-white rounded-2xl shadow-sm p-5">
          <h2 className="text-lg font-semibold text-slate-800 mb-1">
            DSM API 연결 확인
          </h2>
          <p className="text-sm text-slate-500 mb-4">
            로그인 성공. 아래는 실제 NAS의 SYNO.API.Info 프로브 결과입니다 (1단계
            검증).
          </p>
          <ApiInfoPanel />
        </section>
      </main>
    </div>
  );
}
