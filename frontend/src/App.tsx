import { useEffect, useState } from "react";
import {
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { api, AUTH_EXPIRED_EVENT } from "./api/client";
import type { Space } from "./api/types";
import { useAuthStore } from "./store/auth";
import { useToastStore } from "./store/toast";
import {
  activeSection,
  SHOW_MANAGE,
  useTimelineStore,
  type Section,
} from "./store/timeline";
import { useBackTrap } from "./hooks/useBackTrap";
import { LoginForm } from "./components/LoginForm";
import {
  clearLegacyThumbnailCaches,
  clearThumbnailCaches,
  setThumbnailCacheOwner,
} from "./lib/thumbnailCache";

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
import { TimelineScreen } from "./components/TimelineScreen";
import { BottomTabBar } from "./components/BottomTabBar";
import { BulkProgress } from "./components/BulkProgress";
import { Toasts } from "./components/Toasts";
import { PwaUpdater } from "./components/PwaUpdater";
import { NavControls } from "./components/NavControls";
import { ConflictDialogHost } from "./components/ConflictDialog";
import { AskDialogHost, Modal } from "./components/Dialog";

// 주 메뉴 4영역 — 감상(사진/앨범)·정리·더보기(관리 허브). 데스크톱 토글과
// 모바일 하단 탭이 같은 목록을 쓴다(IA 개편 2단계).
export const ALL_SECTIONS: { section: Section; label: string; icon: string }[] = [
  { section: "viewer", label: "사진", icon: "🖼" },
  { section: "albums", label: "앨범", icon: "📔" },
  { section: "manage", label: "정리", icon: "🗂" },
  { section: "more", label: "더보기", icon: "⋯" },
];
export const SECTIONS = ALL_SECTIONS.filter((t) => SHOW_MANAGE || t.section !== "manage");

/** 주 메뉴: 4영역 전환 — 헤더 2줄 구조(A안)의 아래 줄, 언더라인 탭.
 * 위 줄의 라이브러리 셀렉터(무엇을)와 시각 언어를 분리해 "다섯 번째 탭"으로
 * 오독되지 않게 한다. 모바일은 하단 탭 바가 대신하므로 md 이상에서만 표시. */
function SectionToggle() {
  const section = useTimelineStore((s) => s.section);
  const setSection = useTimelineStore((s) => s.setSection);
  const goHome = useTimelineStore((s) => s.goHome);
  // 목록에 없는 영역(감춘 「정리」)에 들어가 있어도 불은 남긴다.
  const current = activeSection(section);
  return (
    <nav className="hidden gap-1 px-2 sm:px-4 md:flex">
      {SECTIONS.map((v) => {
        const active = current === v.section;
        return (
          <button
            key={v.section}
            aria-current={active ? "page" : undefined}
            onClick={() => {
              if (v.section === "viewer" && section === "viewer") goHome();
              else setSection(v.section);
            }}
            className={`relative flex shrink-0 items-center gap-1.5 whitespace-nowrap px-3 pb-2 pt-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
              active
                ? "font-bold text-blue-700"
                : "font-medium text-slate-500 hover:text-slate-700"
            }`}
          >
            <span className="text-base leading-none">{v.icon}</span>
            {v.label}
            {active && (
              <span className="absolute inset-x-2.5 bottom-0 h-[3px] rounded-t-full bg-blue-700" />
            )}
          </button>
        );
      })}
    </nav>
  );
}

/** 사진 검색창: 파일명·폴더명·태그 키워드 — Enter로 검색 뷰 진입.
 * 기기 백업(FileStation)·타인 라이브러리는 DSM 검색 인덱스 밖이라 빈 결과만
 * 나온다 → 숨기는 대신 비활성 + 이유 표시(IA 개편 3단계: 컨트롤이 사라지면
 * 고장으로 오인). */
function SearchBox() {
  const runSearch = useTimelineStore((s) => s.runSearch);
  const activeQuery = useTimelineStore((s) => s.searchQuery);
  const activeZone = useTimelineStore((s) => s.activeZone);
  const viewedOwner = useTimelineStore((s) => s.viewedOwner);
  const [value, setValue] = useState("");
  useEffect(() => {
    setValue(activeQuery);
  }, [activeQuery]);
  const disabledReason = activeZone
    ? "기기 백업 폴더는 검색 대상이 아니에요 (Photos 색인 밖)"
    : viewedOwner
      ? "구성원 사진 열람 중에는 검색할 수 없어요"
      : null;
  const submit = () => {
    const q = value.trim();
    if (q) runSearch(q);
  };
  return (
    <div
      title={disabledReason ?? undefined}
      className={`flex items-center gap-1 rounded-xl bg-slate-100 px-2 py-1 ${
        disabledReason ? "opacity-50" : ""
      }`}
    >
      <span aria-hidden className="text-sm text-slate-400">
        🔍
      </span>
      <input
        aria-label="사진 검색"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
        }}
        disabled={disabledReason != null}
        placeholder={disabledReason ? "검색 불가" : "사진 검색"}
        className="w-24 bg-transparent text-sm text-slate-700 outline-none placeholder:text-slate-400 focus:w-40 sm:w-32 sm:focus:w-48 transition-[width] disabled:cursor-not-allowed"
      />
      {value && !disabledReason && (
        <button
          type="button"
          aria-label="검색어 지우기"
          onClick={() => {
            setValue("");
            if (activeQuery) history.back();
          }}
          className="flex h-7 w-7 items-center justify-center rounded-full text-xs text-slate-400 hover:bg-slate-200 hover:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        >
          ✕
        </button>
      )}
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
  // 타인/기기 백업은 정리에서만 — 감상 영역엔 가족/내사진만.
  const section = useTimelineStore((s) => s.section);
  const selectLibrary = useTimelineStore((s) => s.selectLibrary);
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
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
        ? "📚 가족 사진"
        : "👤 내 사진";

  const pick = (lib: {
    space: Space;
    owner: string | null;
    zone?: { id: string; label: string } | null;
  }) => {
    setOpen(false);
    // 기기 백업/구성원은 정리 전용 → 감상 영역에서 고르면 자동 이동을 예고
    // (3단계: 암묵적 화면 전환을 명시로).
    if ((lib.zone || lib.owner) && section !== "manage") {
      useToastStore
        .getState()
        .push(
          lib.zone
            ? "기기 백업은 정리 화면에서 열려요."
            : "구성원 사진은 정리 화면에서 열려요.",
        );
    }
    selectLibrary(lib);
    if (lib.zone) {
      // 구역을 열었으니 신규 유입 뱃지 리셋(백업 앱 유입분 확인 처리).
      void api.zoneSeen(lib.zone.id).then(() => {
        queryClient.invalidateQueries({ queryKey: ["zones"] });
      });
    }
    // 라이브러리가 통째로 바뀜 — 스코프 데이터만 제거(세션·메타는 유지)
    dropScopedQueries(queryClient);
  };

  const itemCls = (active: boolean) =>
    `flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm ${
      active ? "bg-slate-100 font-semibold text-slate-800" : "text-slate-600 hover:bg-slate-50"
    }`;

  // 앨범은 개인 공간 전용(DSM NormalAlbum) — 라이브러리 전환이 무의미하므로
  // 셀렉터를 고정 표시로 바꿔 죽은 컨트롤을 없앤다.
  if (section === "albums") {
    return (
      <div
        title="앨범은 내 사진 전용입니다"
        className="flex shrink-0 cursor-default items-center gap-1.5 whitespace-nowrap px-2.5 py-1 text-base font-extrabold text-slate-400"
      >
        👤 내 사진
      </div>
    );
  }

  return (
    <div className="relative shrink-0">
      {/* A안: 기본 상태는 제목 스타일(배경 없음) — 탭과 다른 시각 언어.
       * 기기 백업(인디고)/타인(주황)은 상태 신호가 우선이라 색 필 유지. */}
      <button
        onClick={() => setOpen((v) => !v)}
        className={`relative flex items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 py-1 text-base font-extrabold transition-colors ${
          activeZone
            ? "bg-indigo-600 text-white hover:bg-indigo-700"
            : viewedOwner
              ? "bg-amber-500 text-white hover:bg-amber-600"
              : "text-slate-900 hover:bg-slate-100"
        }`}
      >
        {label}
        <span className="text-xs opacity-60">▾</span>
        {zones.some((z) => (z.new_count ?? 0) > 0 && activeZone?.id !== z.id) && (
          <span
            title="기기 백업에 새로 들어온 사진이 있습니다"
            className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-amber-500"
          />
        )}
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
              📚 가족 사진
              <span className="ml-auto text-[10px] text-slate-400">공유 공간</span>
            </button>
            <button
              onClick={() => pick({ space: "personal", owner: null })}
              className={itemCls(!viewedOwner && !activeZone && space === "personal")}
            >
              👤 내 사진
            </button>
            {/* 기기 백업/구성원은 정리 전용이지만 목록엔 항상 노출(3단계:
             * 같은 버튼은 항상 같은 목록). 감상 중 선택 시 pick이 예고 토스트
             * 후 정리로 이동시킨다. */}
            {isAdmin && members.length > 0 && (
              <>
                <p className="px-3 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  관리자 · 구성원 사진
                  {section !== "manage" && (
                    <span className="ml-1 font-normal normal-case text-slate-300">
                      · {SHOW_MANAGE ? "정리에서 열림" : "폴더 보기로 열림"}
                    </span>
                  )}
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
            {zones.length > 0 && (
              <>
                <p className="px-3 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  기기 백업
                  {section !== "manage" && (
                    <span className="ml-1 font-normal normal-case text-slate-300">
                      · {SHOW_MANAGE ? "정리에서 열림" : "폴더 보기로 열림"}
                    </span>
                  )}
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
                    {(z.new_count ?? 0) > 0 && (
                      <span className="ml-auto rounded-full bg-amber-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                        +{z.new_count!.toLocaleString()}
                      </span>
                    )}
                  </button>
                ))}
              </>
            )}
          </div>
        </>
      )}
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
        보는 중: {viewedOwner}의 개인 폴더 (폴더 화면에서만 지원 · 타임라인/
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
        기기 백업: {activeZone.label} · 타임라인에 나오지 않는 백업 폴더입니다 —
        고른 사진을 <b>내 사진으로 이동/복사</b>하세요
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

/** 로그인 계정 칩 — 한 기기를 가족이 돌려 쓰므로 "지금 누구로 로그인했는지"를
 * 헤더에 상시 표시. 누르면 계정·로그아웃이 있는 더보기로 간다. */
function AccountChip({ account, role }: { account: string; role: string }) {
  const setSection = useTimelineStore((s) => s.setSection);
  return (
    <button
      onClick={() => setSection("more")}
      title={`${account} · ${role === "admin" ? "관리자" : "일반 구성원"} — 계정·로그아웃은 더보기에서`}
      className="flex max-w-36 items-center gap-1 whitespace-nowrap rounded-lg px-2 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-700"
    >
      <span aria-hidden>👤</span>
      <span className="truncate">{account}</span>
      {role === "admin" && (
        <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500">
          관리자
        </span>
      )}
    </button>
  );
}

/** 첫 로그인 1회 안내(IA 4단계) — 2축 구조(무엇을 × 어떻게)와 되돌리기
 * 안전망을 한 장으로. 확인하면 다시 안 뜬다(localStorage, 계정별 —
 * 가족이 한 기기를 돌려 써도 각자 한 번씩 본다). 더보기의 "처음 안내
 * 다시 보기"(firstRunTipTick)로 1회 재표시할 수 있다. */
function FirstRunTip({ account }: { account: string }) {
  const storageKey = `nasphoto.firstRunSeen.${account}`;
  const [seen, setSeen] = useState(() => {
    try {
      return localStorage.getItem(storageKey) === "1";
    } catch {
      return true; // private mode 등 — 안내 없이 진행
    }
  });
  // 첫 불릿의 라이브러리 목록은 이 계정이 실제 보는 메뉴와 일치시킨다 —
  // 기기 백업은 계정별 등록제라 처음 로그인한 구성원 메뉴엔 없는 경우가
  // 대부분(안내가 없는 항목을 가리키면 "내 화면이 잘못됐나" 혼란).
  const zonesQuery = useQuery({ queryKey: ["zones"], queryFn: api.listZones });
  const hasBackup = (zonesQuery.data?.zones.length ?? 0) > 0;
  // 더보기 → 처음 안내 다시 보기: 틱이 오르면 이번 1회만 다시 연다.
  const tick = useTimelineStore((s) => s.firstRunTipTick);
  useEffect(() => {
    if (tick > 0) setSeen(false);
  }, [tick]);
  if (seen) return null;
  const dismiss = () => {
    try {
      localStorage.setItem(storageKey, "1");
    } catch {
      // ignore
    }
    setSeen(true);
  };
  return (
    <Modal title="처음 오셨나요? 세 가지만 기억하세요" onClose={dismiss}>
      <ul className="mt-3 space-y-2.5 text-sm leading-relaxed text-slate-600">
        <li>
          📚 <b>왼쪽 위 메뉴</b>에서 <b>무엇을 볼지</b> 골라요 — 가족 사진 ·
          내 사진{hasBackup && " · 기기 백업(휴대폰 백업)"}.
        </li>
        <li>
          🖼 화면 <b><span className="md:hidden">아래</span>
            <span className="hidden md:inline">위</span> 탭</b>에서{" "}
          <b>어떻게 볼지</b> 골라요 — 사진(감상) · 앨범 · 정리(이동/삭제) ·
          더보기.
        </li>
        <li>
          ↩️ 실수해도 괜찮아요 — 삭제·이동은 전부 <b>되돌리기</b>가 돼요
          (더보기 → 휴지통·작업 기록).
        </li>
      </ul>
      <button
        data-autofocus="true"
        onClick={dismiss}
        className="mt-4 w-full rounded-xl bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
      >
        시작하기
      </button>
    </Modal>
  );
}

export default function App() {
  const { user, setUser } = useAuthStore();
  const queryClient = useQueryClient();

  // 뒤로가기 트랩 — 로그인/세션 확인 게이팅보다 먼저(조기 반환 위) 걸어야
  // 앱을 열자마자 누른 첫 뒤로가기도 종료 확인이 동작한다.
  useBackTrap();

  // A DSM/session 401 can happen long after the initial /me bootstrap. Drop
  // decoded photo data and CacheStorage immediately instead of leaving the
  // prior account's gallery visible behind a stale authenticated UI.
  useEffect(() => {
    const expire = () => {
      setThumbnailCacheOwner(null);
      setUser(null);
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== "me",
      });
      void clearThumbnailCaches();
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, expire);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, expire);
  }, [queryClient, setUser]);

  // Restore session on load (cookie may still be valid after a refresh).
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: false,
  });

  useEffect(() => {
    if (meQuery.isSuccess) {
      setThumbnailCacheOwner(meQuery.data.thumbnail_cache_scope);
      // Old builds used one unpartitioned runtime cache. Remove it once while
      // retaining the new account-keyed cache across ordinary reloads.
      void clearLegacyThumbnailCaches();
      setUser(meQuery.data);
    }
    if (meQuery.isError) {
      setThumbnailCacheOwner(null);
      void clearThumbnailCaches();
      setUser(null);
    }
  }, [meQuery.isSuccess, meQuery.isError, meQuery.data, setUser]);

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
        {/* 헤더 2줄 구조(A안): 1줄 = 무엇을 보는지(라이브러리 제목 + 검색),
         * 2줄 = 무엇을 하는지(언더라인 탭, md 이상 — 모바일은 하단 탭 바).
         * 계정·작업 기록·DSM 정보·빌드 진단·로그아웃은 전부 "더보기" 소관. */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-2 pt-2 pb-2 sm:px-4 md:pb-1">
          <h1 className="hidden items-center gap-2 text-lg font-extrabold tracking-tight text-slate-800 lg:flex">
            <span aria-hidden className="text-xl leading-none">
              📷
            </span>
            우리집 사진관
          </h1>
          <div className="hidden h-6 w-px bg-slate-200 lg:block" aria-hidden />
          <LibrarySelector account={user.account} isAdmin={user.role === "admin"} />
          <div className="ml-auto flex shrink-0 items-center gap-1.5 sm:gap-2">
            <SearchBox />
            <AccountChip account={user.account} role={user.role} />
            {user.mock_mode && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
                MOCK
              </span>
            )}
          </div>
        </div>
        <SectionToggle />
      </header>

      <ImpersonationBanner />
      <ZoneBanner />
      {/* key=account: 로그아웃→다른 계정 로그인 시 안내 상태 재평가 */}
      <FirstRunTip key={user.account} account={user.account} />

      {/* pb-14: 모바일 하단 탭 바 높이만큼 콘텐츠 영역 확보 */}
      <div className="min-h-0 flex-1 pb-14 md:pb-0">
        <TimelineScreen />
      </div>
      <BottomTabBar />
      <BulkProgress />
      <Toasts />
      <ConflictDialogHost />
      <AskDialogHost />
      <PwaUpdater />
      <NavControls />
    </div>
  );
}
