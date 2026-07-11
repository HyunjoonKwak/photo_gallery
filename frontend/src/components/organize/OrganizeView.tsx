import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { DedupView } from "../DedupView";
import { JunkStep } from "./JunkStep";
import { EventStep } from "./EventStep";

const STEPS = [
  { n: 1, label: "중복 정리" },
  { n: 2, label: "잡동사니" },
  { n: 3, label: "이벤트 → 공용" },
  { n: 4, label: "요약" },
];

/** ✨ 정리 마법사 셸 — 3단계 스테퍼 + 이어하기(서버 세션).
 *
 * Step1은 DedupView(개인 고정) 임베드, Step2/3는 Phase 1·2 화면. 각 단계는
 * 건너뛰기 가능하고 단계 이동 시 서버에 저장돼 다음 진입 때 이어한다.
 * (ORGANIZE_WIZARD.md Phase 3) */
export function OrganizeView() {
  const qc = useQueryClient();
  const sessionQ = useQuery({
    queryKey: ["organize-session"],
    queryFn: api.organizeSession,
    staleTime: Infinity,
  });
  const [step, setStep] = useState<number | null>(null);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [resumed, setResumed] = useState(false);

  // 서버 세션 로드 → 이어하기
  useEffect(() => {
    if (sessionQ.data && step === null) {
      setStep(sessionQ.data.step);
      setStats(sessionQ.data.stats ?? {});
      setResumed(sessionQ.data.step > 1);
    }
  }, [sessionQ.data, step]);

  const save = useMutation({
    mutationFn: (v: { step: number; stats: Record<string, number> }) =>
      api.saveOrganizeSession(v.step, v.stats),
  });

  const go = (n: number, nextStats?: Record<string, number>) => {
    const st = nextStats ?? stats;
    setStep(n);
    setStats(st);
    save.mutate({ step: n, stats: st });
  };

  const restart = async () => {
    await api.resetOrganizeSession();
    qc.invalidateQueries({ queryKey: ["organize-session"] });
    setStep(1);
    setStats({});
    setResumed(false);
  };

  if (step === null)
    return <p className="p-6 text-center text-sm text-slate-400">불러오는 중…</p>;

  return (
    <div className="flex h-full flex-col">
      <div
        data-no-boxselect
        className="flex shrink-0 flex-wrap items-center gap-2 border-b border-slate-100 bg-white px-4 py-2"
      >
        {STEPS.map((s, i) => (
          <button
            key={s.n}
            onClick={() => go(s.n)}
            className={`flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium ${
              step === s.n
                ? "bg-indigo-600 text-white"
                : step > s.n
                  ? "text-indigo-600 hover:bg-indigo-50"
                  : "text-slate-400 hover:bg-slate-100"
            }`}
          >
            {step > s.n ? "✓" : `${s.n}.`} {s.label}
            {i < STEPS.length - 1 && <span className="ml-1 opacity-40">›</span>}
          </button>
        ))}
        <span className="ml-auto flex items-center gap-2">
          {resumed && step > 1 && step < 4 && (
            <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] text-indigo-600">
              이어하는 중
            </span>
          )}
          {step < 4 && (
            <button
              onClick={() => go(step + 1)}
              className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-100"
            >
              {step === 3 ? "요약 보기" : "다음 단계 ›"}
            </button>
          )}
        </span>
      </div>

      <div className="min-h-0 flex-1">
        {step === 1 && (
          <div className="flex h-full flex-col">
            <p className="shrink-0 border-b border-slate-100 bg-indigo-50/50 px-4 py-1.5 text-xs text-indigo-700">
              Step 1 — 개인 공간의 중복부터 정리합니다. 스캔 결과는 다음
              단계(잡동사니·이벤트)의 데이터로도 재사용됩니다.
            </p>
            <div className="min-h-0 flex-1">
              <DedupView forceSpace="personal" />
            </div>
          </div>
        )}
        {step === 2 && <JunkStep />}
        {step === 3 && (
          <EventStep
            onCreated={(albums, photos) =>
              setStats((prev) => {
                const next = {
                  ...prev,
                  albums: (prev.albums ?? 0) + albums,
                  copied: (prev.copied ?? 0) + photos,
                };
                save.mutate({ step: 3, stats: next });
                return next;
              })
            }
          />
        )}
        {step === 4 && (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <p className="text-3xl">🎉</p>
            <p className="text-sm text-slate-700">
              이번 정리에서 공용 앨범 <b>{stats.albums ?? 0}개</b> ·{" "}
              <b>{(stats.copied ?? 0).toLocaleString()}장</b>을 복사했습니다.
            </p>
            <p className="text-xs text-slate-400">
              새 백업이 들어오면 언제든 다시 실행하세요 — 1차 구역 뱃지가
              알려줍니다.
            </p>
            <button
              onClick={restart}
              className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700"
            >
              새로 시작
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
