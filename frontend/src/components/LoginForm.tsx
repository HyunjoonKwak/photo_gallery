import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { useAuthStore } from "../store/auth";

export function LoginForm() {
  const setUser = useAuthStore((s) => s.setUser);
  const [account, setAccount] = useState("");
  const [passwd, setPasswd] = useState("");
  const [otp, setOtp] = useState("");

  const login = useMutation({
    mutationFn: () =>
      api.login({ account, passwd, otp_code: otp || undefined }),
    onSuccess: (user) => setUser(user),
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate();
  };

  const errorMessage =
    login.error instanceof ApiError ? login.error.message : null;

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100 p-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm bg-white rounded-2xl shadow p-6 space-y-4"
      >
        <div>
          <h1 className="text-xl font-semibold text-slate-800">NAS 사진 정리</h1>
          <p className="text-sm text-slate-500 mt-1">
            DSM 계정으로 로그인하세요.
          </p>
        </div>

        <label className="block">
          <span className="text-sm text-slate-600">계정</span>
          <input
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            autoComplete="username"
            required
          />
        </label>

        <label className="block">
          <span className="text-sm text-slate-600">비밀번호</span>
          <input
            type="password"
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={passwd}
            onChange={(e) => setPasswd(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        <label className="block">
          <span className="text-sm text-slate-600">
            OTP (2단계 인증, 선택)
          </span>
          <input
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={otp}
            onChange={(e) => setOtp(e.target.value)}
            inputMode="numeric"
            placeholder="사용 중일 때만 입력"
          />
        </label>

        {errorMessage && (
          <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">
            {errorMessage}
          </p>
        )}

        <button
          type="submit"
          disabled={login.isPending}
          className="w-full rounded-lg bg-blue-600 text-white py-2 font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {login.isPending ? "로그인 중..." : "로그인"}
        </button>
      </form>
    </div>
  );
}
