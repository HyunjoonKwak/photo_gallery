import { useEffect, useRef, useState, type ReactNode } from "react";
import { create } from "zustand";

/** 공용 모달 셸 — window.prompt/confirm 대체(안드로이드 PWA에서 네이티브
 * 다이얼로그는 이질적 + 메인 스레드 정지). Esc/배경 클릭 닫기, role=dialog,
 * 열릴 때 포커스 이동까지 한 곳에서 처리한다. */
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const boxRef = useRef<HTMLDivElement | null>(null);
  // onClose는 렌더마다 새 함수 — deps에 넣으면 키 입력(재렌더)마다 effect가
  // 재실행돼 box.focus()가 입력창의 포커스를 강탈했다(2026-07-12 보고: 새 폴더
  // 이름이 한 글자마다 끊김). 마운트 1회만 실행하고 최신 onClose는 ref로.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    // 내부(입력창 autoFocus)가 이미 포커스를 가졌으면 뺏지 않는다.
    if (!boxRef.current?.contains(document.activeElement)) {
      boxRef.current?.focus();
    }
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div
      data-no-boxselect
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      onClick={onClose}
    >
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="w-full max-w-sm rounded-2xl bg-white p-5 shadow-xl outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <h4 className="text-sm font-bold text-slate-800">{title}</h4>
        {children}
      </div>
    </div>
  );
}

interface AskState {
  kind: "confirm" | "prompt";
  title: string;
  body?: string;
  initial?: string;
  placeholder?: string;
  confirmLabel: string;
  danger: boolean;
  resolve: (v: string | boolean | null) => void;
}

const useAskStore = create<{ pending: AskState | null; ask: (a: AskState) => void; clear: () => void }>()(
  (set) => ({ pending: null, ask: (pending) => set({ pending }), clear: () => set({ pending: null }) }),
);

/** window.confirm 대체 — true/false를 resolve하는 Promise. */
export function askConfirm(opts: {
  title: string;
  body?: string;
  confirmLabel?: string;
  danger?: boolean;
}): Promise<boolean> {
  return new Promise((resolve) => {
    useAskStore.getState().ask({
      kind: "confirm",
      title: opts.title,
      body: opts.body,
      confirmLabel: opts.confirmLabel ?? "확인",
      danger: opts.danger ?? false,
      resolve: (v) => resolve(v === true),
    });
  });
}

/** window.prompt 대체 — 입력 문자열(취소 시 null)을 resolve. */
export function askPrompt(opts: {
  title: string;
  body?: string;
  initial?: string;
  placeholder?: string;
  confirmLabel?: string;
}): Promise<string | null> {
  return new Promise((resolve) => {
    useAskStore.getState().ask({
      kind: "prompt",
      title: opts.title,
      body: opts.body,
      initial: opts.initial,
      placeholder: opts.placeholder,
      confirmLabel: opts.confirmLabel ?? "확인",
      danger: false,
      resolve: (v) => resolve(typeof v === "string" ? v : null),
    });
  });
}

/** App 루트에 한 번 마운트 — askConfirm/askPrompt의 렌더 호스트. */
export function AskDialogHost() {
  const pending = useAskStore((s) => s.pending);
  const clear = useAskStore((s) => s.clear);
  const [value, setValue] = useState("");
  useEffect(() => {
    setValue(pending?.initial ?? "");
  }, [pending]);
  if (!pending) return null;
  const done = (v: string | boolean | null) => {
    pending.resolve(v);
    clear();
  };
  return (
    <Modal title={pending.title} onClose={() => done(null)}>
      {pending.body && (
        <p className="mt-1.5 whitespace-pre-line text-sm leading-relaxed text-slate-600">
          {pending.body}
        </p>
      )}
      {pending.kind === "prompt" && (
        <input
          autoFocus
          value={value}
          placeholder={pending.placeholder}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && value.trim()) done(value);
          }}
          className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      )}
      <div className="mt-4 flex justify-end gap-2">
        <button
          onClick={() => done(null)}
          className="rounded-lg px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100"
        >
          취소
        </button>
        <button
          onClick={() => done(pending.kind === "prompt" ? value : true)}
          disabled={pending.kind === "prompt" && !value.trim()}
          className={`rounded-lg px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40 ${
            pending.danger ? "bg-red-600 hover:bg-red-700" : "bg-blue-600 hover:bg-blue-700"
          }`}
        >
          {pending.confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
