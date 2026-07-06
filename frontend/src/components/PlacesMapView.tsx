import { useEffect, useMemo, useRef } from "react";
import { useQueries } from "@tanstack/react-query";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "../api/client";
import type { Space } from "../api/types";
import type { RegionGroup } from "./PlacesRegionView";

/** 장소 지도 뷰 — 지역(first_level)별 대표 GPS 좌표에 핀을 찍는다. 좌표는 각
 * 지역 대표 그룹의 첫 사진 GPS(place_items의 lat/lng, limit=1로 가볍게)에서
 * 얻는다. 핀 탭 → 그 지역 사진. 타일은 OpenStreetMap(클라이언트가 직접 로드,
 * 인터넷 필요). 위치정보 있는 사진이 없으면 안내. */
export function PlacesMapView({
  space,
  regions,
  onOpen,
}: {
  space: Space;
  regions: RegionGroup[];
  onOpen: (r: RegionGroup) => void;
}) {
  // 각 지역 대표 좌표: 대표 그룹의 첫 사진 GPS(limit=1, 캐시 공유).
  const coordQueries = useQueries({
    queries: regions.map((r) => ({
      queryKey: ["place-coord", space, r.coverId],
      queryFn: () => api.placeItems(space, r.coverId, 1),
      staleTime: 30 * 60_000,
    })),
  });

  const sig = coordQueries
    .map((q) => {
      const it = q.data?.items?.[0];
      return it ? `${it.lat},${it.lng}` : "";
    })
    .join("|");

  const pins = useMemo(() => {
    return regions
      .map((r, i) => {
        const it = coordQueries[i].data?.items?.[0];
        if (it?.lat == null || it?.lng == null) return null;
        return { region: r, lat: it.lat, lng: it.lng };
      })
      .filter((p): p is { region: RegionGroup; lat: number; lng: number } => p != null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);

  const anyPending = coordQueries.some((q) => q.isPending);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const onOpenRef = useRef(onOpen);
  onOpenRef.current = onOpen;

  // 지도 1회 생성.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, {
      center: [20, 0],
      zoom: 2,
      worldCopyJump: true,
    });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap",
      maxZoom: 19,
    }).addTo(map);
    layerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
  }, []);

  // 핀 갱신.
  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();
    if (pins.length === 0) return;

    for (const pin of pins) {
      const icon = L.divIcon({
        className: "",
        html: `<div style="background:#2563eb;color:#fff;border-radius:9999px;padding:2px 7px;font-size:11px;font-weight:600;white-space:nowrap;box-shadow:0 1px 3px rgba(0,0,0,.4);transform:translate(-50%,-100%)">📍 ${pin.region.first_level} · ${pin.region.total.toLocaleString()}</div>`,
        iconSize: [0, 0],
      });
      L.marker([pin.lat, pin.lng], { icon })
        .addTo(layer)
        .on("click", () => onOpenRef.current(pin.region));
    }
    const bounds = L.latLngBounds(pins.map((p) => [p.lat, p.lng] as [number, number]));
    map.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
  }, [pins]);

  return (
    <div className="relative h-full">
      <div ref={containerRef} className="h-full w-full" />
      {anyPending && (
        <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-full bg-white/90 px-3 py-1 text-xs text-slate-500 shadow">
          위치 불러오는 중…
        </div>
      )}
      {!anyPending && pins.length === 0 && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <p className="rounded-lg bg-white/90 px-4 py-2 text-sm text-slate-500 shadow">
            GPS 좌표가 있는 사진이 없습니다.
          </p>
        </div>
      )}
    </div>
  );
}
