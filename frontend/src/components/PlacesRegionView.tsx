import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PlaceInfo, Space } from "../api/types";
import { Thumb } from "./timeline/Thumb";
import { UniformPhotoGrid } from "./timeline/UniformPhotoGrid";

/** 장소(지역별) 뷰어 — Synology Photos의 GPS 지오코딩 그룹(`places`)을 국가→
 * 지역 2단 폴더형으로 보여준다. 국가 카드 탭 → 그 국가의 지역 카드(폴더형 +
 * 직속 사진 4장 미리보기) → 지역 탭 → 사진 썸네일 그리드(라이트박스). 순수
 * 뷰어(정리는 폴더 분류에서). 지도 뷰는 좌표 확보 후 후속 단계.
 *
 * 그룹 이름 파싱: 첫 토큰=국가, 나머지=지역(예 "대한민국 서울"). 실 NAS의
 * 지오코딩 name 포맷은 미검증이라 방어적으로 처리(토큰 1개면 국가=지역). */
export function PlacesRegionView({ space }: { space: Space }) {
  const [country, setCountry] = useState<string | null>(null);
  const [region, setRegion] = useState<PlaceInfo | null>(null);

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
      const c = countryOf(p.name);
      const list = m.get(c);
      if (list) list.push(p);
      else m.set(c, [p]);
    }
    return [...m.entries()]
      .map(([name, regions]) => ({
        name,
        regions,
        total: regions.reduce((s, r) => s + (r.item_count ?? 0), 0),
      }))
      .sort((a, b) => b.total - a.total);
  }, [places]);

  const currentRegions =
    country != null ? countries.find((c) => c.name === country)?.regions ?? [] : [];

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
            country
              ? "text-blue-600 hover:bg-slate-100"
              : "font-semibold text-slate-700"
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
              {country}
            </button>
          </span>
        )}
        {region && (
          <span className="flex items-center gap-1">
            <span className="text-slate-300">/</span>
            <span className="px-1.5 py-0.5 font-semibold text-slate-800">
              {regionLabel(region, country ?? "")}
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
              style={{
                gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
              }}
            >
              {currentRegions.map((r) => (
                <RegionCard
                  key={r.id}
                  space={space}
                  region={r}
                  label={regionLabel(r, country)}
                  onOpen={() => setRegion(r)}
                />
              ))}
            </div>
          </div>
        ) : (
          <div className="h-full overflow-y-auto p-4">
            <div
              className="grid gap-3"
              style={{
                gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
              }}
            >
              {countries.map((c) => (
                <button
                  key={c.name}
                  onClick={() => setCountry(c.name)}
                  className="flex flex-col items-center gap-1.5 rounded-xl border border-slate-200 p-4 hover:bg-slate-100"
                >
                  <span className="text-3xl">🌐</span>
                  <span className="truncate text-sm font-medium text-slate-700">
                    {c.name}
                  </span>
                  <span className="text-xs text-slate-400">
                    {c.total.toLocaleString()}장 · 지역 {c.regions.length}
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

/** 지역 카드 — 그 지역 사진 4장을 2×2 미리보기로(폴더형). */
function RegionCard({
  space,
  region,
  label,
  onOpen,
}: {
  space: Space;
  region: PlaceInfo;
  label: string;
  onOpen: () => void;
}) {
  const q = useQuery({
    queryKey: ["album-items", space, "place", region.id],
    queryFn: () => api.placeItems(space, region.id),
    staleTime: 60_000,
  });
  const preview = (q.data?.items ?? []).slice(0, 4);
  return (
    <button
      onClick={onOpen}
      title={label}
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
          📍 {label}
        </span>
        {region.item_count != null && (
          <span className="shrink-0 text-[10px] text-slate-400">
            {region.item_count.toLocaleString()}
          </span>
        )}
      </div>
    </button>
  );
}

function RegionPhotos({ space, region }: { space: Space; region: PlaceInfo }) {
  const q = useQuery({
    queryKey: ["album-items", space, "place", region.id],
    queryFn: () => api.placeItems(space, region.id),
  });
  const items = useMemo(
    () => (q.data?.items ?? []).map((it) => ({ ...it, space })),
    [q.data, space],
  );
  if (q.isPending)
    return <p className="p-6 text-sm text-slate-400">불러오는 중…</p>;
  if (items.length === 0)
    return <p className="p-6 text-sm text-slate-400">사진이 없습니다.</p>;
  return <UniformPhotoGrid items={items} space={space} />;
}

/** 지오코딩 그룹 이름에서 국가(첫 토큰) 추출. 빈 이름은 "기타". */
function countryOf(name: string): string {
  const n = (name || "").trim();
  if (!n) return "기타";
  return n.split(/\s+/)[0];
}

/** 국가 접두어를 뗀 지역명. 토큰이 하나뿐이면 그대로. */
function regionLabel(place: PlaceInfo, country: string): string {
  const n = (place.name || "").trim();
  if (!n) return "기타 지역";
  const rest = n.startsWith(country) ? n.slice(country.length).trim() : n;
  return rest || n;
}
