import { useEffect, useMemo, useRef, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PhotoItem, PlaceInfo, Space } from "../api/types";
import { useTimelineStore } from "../store/timeline";
import { Thumb } from "./timeline/Thumb";
import { PhotoGrid } from "./timeline/PhotoGrid";
import { PlacesMapView } from "./PlacesMapView";
import { useNearViewport } from "../hooks/useNearViewport";

/** 장소(지역별) 뷰어 — Synology Photos의 GPS 지오코딩 그룹(`places`)을 국가별
 * 섹션으로 한 화면에 펼치고, 각 국가 아래에 지역(first_level=도시) 카드를
 * 나열한다(폴더형 + 사진 4장 미리보기). 도시 탭 → 그 도시의 사진 썸네일
 * 그리드(라이트박스). 한 도시(first_level, 예 Seoul)에 지오코딩 그룹이
 * 여럿이면 합쳐 보여준다. 순수 뷰어. */

// 실 NAS 지오코딩 country는 영문("South Korea") — 흔한 국가만 한글 표기,
// 나머지는 원문 그대로.
const COUNTRY_KO: Record<string, string> = {
  "South Korea": "대한민국",
  Korea: "대한민국",
  Japan: "일본",
  China: "중국",
  "Hong Kong": "홍콩",
  Taiwan: "대만",
  "United States": "미국",
  USA: "미국",
  Australia: "호주",
  "United Kingdom": "영국",
  France: "프랑스",
  Germany: "독일",
  Italy: "이탈리아",
  Spain: "스페인",
  Thailand: "태국",
  Vietnam: "베트남",
  Singapore: "싱가포르",
  Canada: "캐나다",
};
const countryLabel = (c: string) => COUNTRY_KO[c] ?? c;

export interface RegionGroup {
  first_level: string;
  country: string; // 브레드크럼용(한글 라벨)
  total: number;
  placeIds: string[]; // item_count 내림차순
  coverId: string; // 미리보기용(가장 큰 그룹)
}

interface CountrySection {
  name: string;
  label: string;
  total: number;
  regions: RegionGroup[];
}

export function PlacesRegionView({ space }: { space: Space }) {
  const [region, setRegion] = useState<RegionGroup | null>(null);
  const [mode, setMode] = useState<"regions" | "map">("regions");
  const regionScrollRef = useRef<HTMLDivElement | null>(null);
  const registerBack = useTimelineStore((s) => s.registerBack);
  const setScreenBackDepth = useTimelineStore((s) => s.setScreenBackDepth);

  // 지역 사진을 열었으면 "뒤로"가 지역 목록으로.
  useEffect(() => {
    if (!region) return;
    return registerBack(() => setRegion(null));
  }, [region, registerBack]);
  // 뒤로 깊이 보고(히스토리 미러링용). 언마운트 시 0으로 리셋.
  useEffect(() => {
    setScreenBackDepth(region ? 1 : 0);
  }, [region, setScreenBackDepth]);
  useEffect(() => () => setScreenBackDepth(0), [setScreenBackDepth]);

  const q = useQuery({
    queryKey: ["places", space],
    queryFn: () => api.places(space),
    staleTime: 5 * 60_000,
  });
  const places = q.data?.places ?? [];

  // 국가별 섹션 → 각 국가의 지역(first_level) 그룹. 모두 개수 내림차순.
  const countries = useMemo<CountrySection[]>(() => {
    const byCountry = new Map<string, PlaceInfo[]>();
    for (const p of places) {
      const c = p.country || "기타";
      const list = byCountry.get(c);
      if (list) list.push(p);
      else byCountry.set(c, [p]);
    }
    return [...byCountry.entries()]
      .map(([name, group]) => {
        const label = countryLabel(name);
        const byRegion = new Map<string, PlaceInfo[]>();
        for (const p of group) {
          const key = p.first_level || p.name || "기타 지역";
          const list = byRegion.get(key);
          if (list) list.push(p);
          else byRegion.set(key, [p]);
        }
        const regions = [...byRegion.entries()]
          .map(([first_level, rg]) => {
            const sorted = [...rg].sort(
              (a, b) => (b.item_count ?? 0) - (a.item_count ?? 0),
            );
            return {
              first_level,
              country: label,
              total: sorted.reduce((s, r) => s + (r.item_count ?? 0), 0),
              placeIds: sorted.map((p) => p.id),
              coverId: sorted[0].id,
            };
          })
          .sort((a, b) => b.total - a.total);
        return {
          name,
          label,
          total: group.reduce((s, r) => s + (r.item_count ?? 0), 0),
          regions,
        };
      })
      .sort((a, b) => b.total - a.total);
  }, [places]);

  const allRegions = useMemo(
    () => countries.flatMap((c) => c.regions),
    [countries],
  );

  if (q.isPending)
    return <p className="p-6 text-sm text-slate-400">불러오는 중…</p>;
  if (places.length === 0)
    return (
      <p className="p-6 text-sm text-slate-400">
        위치 정보(GPS)가 있는 사진이 없습니다.
      </p>
    );

  return (
    <div className="flex h-full flex-col">
      {/* 브레드크럼 */}
      <div className="flex shrink-0 flex-wrap items-center gap-1 border-b border-slate-100 bg-white px-4 py-1.5 text-sm">
        <button
          onClick={() => setRegion(null)}
          className={`rounded px-1.5 py-0.5 ${
            region
              ? "text-blue-600 hover:bg-slate-100"
              : "font-semibold text-slate-700"
          }`}
        >
          🌏 장소
        </button>
        {region && (
          <span className="flex items-center gap-1">
            <span className="text-slate-300">/</span>
            <span className="text-slate-500">{region.country}</span>
            <span className="text-slate-300">/</span>
            <span className="px-1.5 py-0.5 font-semibold text-slate-800">
              {region.first_level}
            </span>
          </span>
        )}
        {!region && (
          <nav className="ml-auto flex gap-0.5 rounded-lg bg-slate-100 p-0.5">
            {(["regions", "map"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  mode === m
                    ? "bg-white text-slate-800 shadow-sm"
                    : "text-slate-500 hover:text-slate-700"
                }`}
              >
                {m === "regions" ? "지역별" : "지도"}
              </button>
            ))}
          </nav>
        )}
      </div>

      <div className="min-h-0 flex-1">
        {region ? (
          <RegionPhotos space={space} region={region} />
        ) : mode === "map" ? (
          <PlacesMapView space={space} regions={allRegions} onOpen={setRegion} />
        ) : (
          <div
            ref={regionScrollRef}
            className="scroll-thin h-full space-y-6 overflow-y-auto p-4"
          >
            {countries.map((c) => (
              <section key={c.name}>
                <h3 className="mb-2 flex items-baseline gap-2">
                  <span className="text-base font-semibold text-slate-800">
                    🌐 {c.label}
                  </span>
                  <span className="text-xs text-slate-400">
                    {c.total.toLocaleString()}장 · 지역 {c.regions.length}
                  </span>
                </h3>
                <div
                  className="grid gap-3"
                  style={{
                    gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
                  }}
                >
                  {c.regions.map((r) => (
                    <RegionCard
                      key={r.first_level}
                      space={space}
                      region={r}
                      scrollRoot={regionScrollRef}
                      onOpen={() => setRegion(r)}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** 지역(도시) 카드 — 대표 그룹 사진 4장을 2×2 미리보기로(폴더형). */
function RegionCard({
  space,
  region,
  scrollRoot,
  onOpen,
}: {
  space: Space;
  region: RegionGroup;
  scrollRoot: React.RefObject<HTMLDivElement | null>;
  onOpen: () => void;
}) {
  const [cardRef, near] = useNearViewport<HTMLButtonElement>(scrollRoot);
  // 미리보기 4장만 필요 → limit로 한 페이지만(그룹 전체 목록을 안 받음).
  // 전체 목록과 캐시 키를 분리(place-preview)해 서로 덮어쓰지 않게.
  const q = useQuery({
    queryKey: ["place-preview", space, region.coverId],
    queryFn: () => api.placeItems(space, region.coverId, 8),
    enabled: near,
    staleTime: 5 * 60_000,
  });
  const preview = (q.data?.items ?? []).slice(0, 4);
  return (
    <button
      ref={cardRef}
      onClick={onOpen}
      title={region.first_level}
      className="group flex flex-col gap-1.5 rounded-xl p-2 text-left hover:bg-slate-100"
    >
      <div className="grid aspect-square grid-cols-2 grid-rows-2 gap-0.5 overflow-hidden rounded-lg bg-slate-200">
        {preview.length === 0 ? (
          <div className="col-span-2 row-span-2 flex items-center justify-center text-4xl">
            📍
          </div>
        ) : (
          Array.from({ length: 4 }, (_, i) =>
            preview[i] ? (
              <Thumb key={i} item={preview[i]} space={space} rounded="" />
            ) : (
              <div key={i} className="bg-slate-100" />
            ),
          )
        )}
      </div>
      <div className="flex items-center justify-between px-0.5">
        <span className="truncate text-xs font-medium text-slate-700">
          📍 {region.first_level}
        </span>
        <span className="shrink-0 text-[10px] text-slate-400">
          {region.total.toLocaleString()}
        </span>
      </div>
    </button>
  );
}

/** 지역의 사진 — first_level에 속한 지오코딩 그룹들의 사진을 합쳐(id 중복
 * 제거·촬영일 정렬) 그리드로. */
function RegionPhotos({ space, region }: { space: Space; region: RegionGroup }) {
  const queries = useQueries({
    queries: region.placeIds.map((id) => ({
      queryKey: ["album-items", space, "place", id],
      queryFn: () => api.placeItems(space, id),
      staleTime: 60_000,
    })),
  });
  const pending = queries.some((r) => r.isPending);
  const items = useMemo(() => {
    const byId = new Map<string, PhotoItem>();
    for (const r of queries) {
      for (const it of r.data?.items ?? []) {
        if (!byId.has(it.id)) byId.set(it.id, { ...it, space });
      }
    }
    return [...byId.values()].sort((a, b) =>
      a.taken_at < b.taken_at ? 1 : a.taken_at > b.taken_at ? -1 : 0,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queries.map((r) => r.data?.items?.length ?? 0).join("|"), space]);

  if (pending && items.length === 0)
    return <p className="p-6 text-sm text-slate-400">불러오는 중…</p>;
  if (items.length === 0)
    return <p className="p-6 text-sm text-slate-400">사진이 없습니다.</p>;
  return <PhotoGrid items={items} space={space} />;
}
