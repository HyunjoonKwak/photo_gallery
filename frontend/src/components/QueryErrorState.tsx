interface QueryErrorStateProps {
  message?: string;
  onRetry: () => void;
  compact?: boolean;
}

/** 조회 실패와 실제 빈 상태를 분리하는 공통 화면. */
export function QueryErrorState({
  message = "내용을 불러오지 못했습니다.",
  onRetry,
  compact = false,
}: QueryErrorStateProps) {
  return (
    <div
      role="alert"
      className={`flex flex-col items-center justify-center gap-2 px-5 text-center ${
        compact ? "py-5" : "h-full min-h-36 py-10"
      }`}
    >
      <span aria-hidden className="text-2xl">
        ⚠️
      </span>
      <p className="text-sm font-medium text-slate-600">{message}</p>
      <p className="max-w-sm text-xs leading-relaxed text-slate-400">
        NAS 연결과 네트워크 상태를 확인한 뒤 다시 시도해 주세요.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
      >
        다시 시도
      </button>
    </div>
  );
}
