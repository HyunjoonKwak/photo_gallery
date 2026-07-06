import { useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PhotoItem, PlaceInfo, Space } from "../api/types";
import { Thumb } from "./timeline/Thumb";
import { UniformPhotoGrid } from "./timeline/UniformPhotoGrid";

/** 장소(지역별) 뷰어 — Synology Photos의 GPS 지오코딩 그룹(`places`)을
 * 국가 → 지역(first_level) 2단으로 묶어 폴더형으로 보여준다. 국가 카드 탭 →
 * 그 국가의 지역 카드(폴더형 + 사진 4장 미리보기) → 지역 탭 → 사진 썸네일
 * 그리드(라이트박스). 한 first_level(예 Seoul)에 지오코딩 그룹이 여럿이면
 * 지역 진입 시 그 그룹들의 사진을 합쳐 보여준다. 순수 뷰어. */

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

interface RegionGroup {
  first_level: string;
  total: number;
  placeIds: string[]; // item_count 내림차순
  coverId: string; // 미리보기용(가장 큰 그룹)
}

export function PlacesRegionView({ space }: { space: Space }) {
  const [country, setCountry] = useState<string | null>(null);
  const [region, setRegion] = useState<RegionGroup | null>(null);

  const q = useQuery({
    queryKey: ["places", space],
    queryFn: () => api.places(space),
    staleTime: 5 * 60_000,
  });
  const places = q.data?.places ?? [];

  // 국가별 그룹 (개수 내림차순).
  const countries = useMemo(() => {
    const m = new Map<string, PlaceInfo[]>();
    for (const p of places) {
      const c = p.country || "기타";
      const list = m.get(c);
      if (list) list.push(p);
      else m.set(c, [p]);
    }
    return [...m.entries()]
      .map(([name, group]) => ({
        name,
        label: countryLabel(name),
        total: group.reduce((s, r) => s + (r.item_count ?? 0), 0),
        group,
      }))
      .sort((a, b) => b.total - a.total);
  }, [places]);

  // 선택 국가의 지역(first_level)별 그룹.
  const regions = useMemo<RegionGroup[]>(() => {
    if (country == null) return [];
    const inCountry = countries.find((c) => c.name === country)?.group ?? [];
    const m = new Map<string, PlaceInfo[]>();
    for (const p of inCountry) {
      const key = p.first_level || p.name || "기타 지역";
      const list = m.get(key);
      if (list) list.push(p);
      else m.set(key, [p]);
    }
    return [...m.entries()]
      .map(([first_level, group]) => {
        const sorted = [...group].sort(
          (a, b) => (b.item_count ?? 0) - (a.item_count ?? 0),
        );
        return {
          first_level,
          total: sorted.reduce((s, r) => s + (r.item_count ?? 0), 0),
          placeIds: sorted.map((p) => p.id),
          coverId: sorted[0].id,
        };
      })
      .sort((a, b) => b.total - a.total);
  }, [country, countries]);

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
          onClick={() => {
            setCountry(null);
            setRegion(null);
          }}
          className={`rounded px-1.5 py-0.5 ${
            country ? "text-blue-600 hover:bg-slate-100" : "font-semibold text-slate-700"
          }`}
        >
          🌏 장소
        </button>
        {country && (
          <span className="flex items-center gap-1">
            <span className="text-slate-300">/</span>
            <button
              onClick={() => setRegion(null)}
              className={`rounded px-1.5 py-0.5 ${
                region
                  ? "text-blue-600 hover:bg-slate-100"
                  : "font-semibold text-slate-800"
              }`}
            >
              {countryLabel(country)}
            </button>
          </span>
        )}
        {region && (
          <span className="flex items-center gap-1">
            <span className="text-slate-300">/</span>
            <span className="px-1.5 py-0.5 font-semibold text-slate-800">
              {region.first_level}
            </span>
          </span>
        )}
      </div>

      <div className="min-h-0 flex-1">
        {region ? (
          <RegionPhotos space={space} region={region} />
        ) : country ? (
          <div className="h-full overflow-y-auto p-4">
            <div
              className="grid gap-3"
              style={{ gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))" }}
            >
              {regions.map((r) => (
                <RegionCard
                  key={r.first_level}
                  space={space}
                  region={r}
                  onOpen={() => setRegion(r)}
                />
              ))}
            </div>
          </div>
        ) : (
          <div className="h-full overflow-y-auto p-4">
            <div
              className="grid gap-3"
              style={{ gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))" }}
            >
              {countries.map((c) => (
                <button
                  key={c.name}
                  onClick={() => setCountry(c.name)}
                  className="flex flex-col items-center gap-1.5 rounded-xl border border-slate-200 p-4 hover:bg-slate-100"
                >
                  <span className="text-3xl">🌐</span>
                  <span className="truncate text-sm font-medium text-slate-700">
                    {c.label}
                  </span>
                  <span className="text-xs text-slate-400">
                    {c.total.toLocaleString()}장 · 지역{" "}
                    {new Set(c.group.map((p) => p.first_level || p.name)).size}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** 지역 카드 — 대표 그룹 사진 4장을 2×2 미리보기로(폴더형). */
function RegionCard({
  space,
  region,
  onOpen,
}: {
  space: Space;
  region: RegionGroup;
  onOpen: () => void;
}) {
  const q = useQuery({
    queryKey: ["album-items", space, "place", region.coverId],
    queryFn: () => api.placeItems(space, region.coverId),
    staleTime: 60_000,
  });
  const preview = (q.data?.items ?? []).slice(0, 4);
  return (
    <button
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
  return <UniformPhotoGrid items={items} space={space} />;
}
