import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuthStore } from "../store/auth";
import { selectBackDepth, useTimelineStore } from "../store/timeline";
import { OperationsPanel } from "./OperationsPanel";
import { ZoneManager } from "./ZoneManager";
import { ApiInfoPanel } from "./ApiInfoPanel";
import {
  clearThumbnailCaches,
  setThumbnailCacheOwner,
} from "../lib/thumbnailCache";

/** 더보기 허브 (IA 개편 2단계) — 흩어져 있던 관리 기능의 단일 진입점.
 * 휴지통(일급 승격)·작업 기록·기기 백업 관리·DSM 정보·빌드 진단·계정/로그아웃.
 * 덕분에 헤더는 라이브러리·영역·검색만 남는다. */

function Row({
  icon,
  label,
  desc,
  badge,
  onClick,
  active = false,
}: {
  icon: string;
  label: string;
  desc: string;
  badge?: string;
  onClick: () => void;
  active?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left transition-colors ${
        active ? "bg-slate-100" : "hover:bg-slate-50"
      }`}
    >
      <span className="text-xl leading-none">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2 text-sm font-semibold text-slate-800">
          {label}
          {badge && (
            <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[11px] font-bold text-slate-600">
              {badge}
            </span>
          )}
        </span>
        <span className="block truncate text-xs text-slate-400">{desc}</span>
      </span>
      <span className="text-slate-300">›</span>
    </button>
  );
}

function GroupLabel({ children }: { children: string }) {
  return (
    <p className="px-4 pb-1 pt-5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
      {children}
    </p>
  );
}

/** 빌드·뒤로가기 진단 — 기기가 최신 코드를 받았는지(PWA 캐시)와 히스토리
 * 트랩 상태를 보여준다. 헤더 상주 배지에서 더보기로 이사. */
function BuildDiag() {
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
      <Row
        icon="🧪"
        label="빌드·진단"
        desc="기기가 최신 버전인지 확인 (캐시·뒤로가기 문제 진단)"
        badge={__BUILD_ID__}
        onClick={() => (diag ? setDiag(null) : read())}
        active={diag != null}
      />
      {diag && (
        <div className="mx-4 mb-2 rounded-xl bg-slate-900/95 px-4 py-3 font-mono text-xs text-slate-100">
          <div className="whitespace-pre-wrap">{diag}</div>
          <div className="mt-2 flex gap-2">
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

export function MoreScreen() {
  const { user, setUser } = useAuthStore();
  const queryClient = useQueryClient();
  // ops 패널 재사용: "휴지통"은 같은 패널을 휴지통이 펼쳐진 채로 연다.
  const [panel, setPanel] = useState<"ops" | "trash" | null>(null);
  const [zonesOpen, setZonesOpen] = useState(false);
  const [apiOpen, setApiOpen] = useState(false);

  const trashQ = useQuery({ queryKey: ["trash"], queryFn: api.trashStats });
  const trashItems = trashQ.data?.items ?? 0;

  const logout = useMutation({
    mutationFn: api.logout,
    onSettled: async () => {
      setThumbnailCacheOwner(null);
      setUser(null);
      queryClient.clear();
      await clearThumbnailCaches();
    },
  });

  if (!user) return null;

  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-lg px-3 py-5 sm:px-4">
        {/* 계정 카드 */}
        <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3.5 shadow-sm">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-lg">
            👤
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-bold text-slate-800">{user.account}</p>
            <p className="text-xs text-slate-400">
              {user.role === "admin" ? "관리자" : "일반 구성원"}
              {user.mock_mode && " · MOCK 모드"}
            </p>
          </div>
          <button
            onClick={() => logout.mutate()}
            disabled={logout.isPending}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            로그아웃
          </button>
        </div>

        <GroupLabel>보관함</GroupLabel>
        <Row
          icon="🗑"
          label="휴지통"
          desc="삭제한 사진 보기·선택 복원 (7일 보관)"
          badge={trashItems > 0 ? `${trashItems.toLocaleString()}장` : undefined}
          onClick={() => setPanel("trash")}
        />
        <Row
          icon="🕘"
          label="작업 기록"
          desc="이동·복사·삭제 내역과 되돌리기"
          onClick={() => setPanel("ops")}
        />

        <GroupLabel>관리</GroupLabel>
        <Row
          icon="📲"
          label="기기 백업 관리"
          desc="타임라인 밖 백업 폴더 등록·삭제"
          onClick={() => setZonesOpen(true)}
        />

        <GroupLabel>정보</GroupLabel>
        <Row
          icon="💡"
          label="처음 안내 다시 보기"
          desc="무엇을·어떻게 볼지, 되돌리기 안내 한 장"
          onClick={() => useTimelineStore.getState().showFirstRunTip()}
        />
        <Row
          icon="🖥"
          label="DSM 연결 정보"
          desc="NAS API 경로·버전 (문제 진단용)"
          onClick={() => setApiOpen((v) => !v)}
          active={apiOpen}
        />
        {apiOpen && (
          <div className="scroll-thin mx-1 mb-2 max-h-72 overflow-auto rounded-xl border border-slate-200 bg-white px-4 py-3">
            <ApiInfoPanel />
          </div>
        )}
        <BuildDiag />
      </div>

      {panel && (
        <OperationsPanel
          initialTrashOpen={panel === "trash"}
          onClose={() => setPanel(null)}
        />
      )}
      {zonesOpen && <ZoneManager onClose={() => setZonesOpen(false)} />}
    </div>
  );
}
