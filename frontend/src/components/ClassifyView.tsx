import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, thumbnailUrl } from "../api/client";
import type { PersonInfo, PlaceInfo } from "../api/types";
import { layoutBucket } from "../lib/rowModel";
import { useTimelineStore } from "../store/timeline";
import { PhotoCell } from "./timeline/PhotoCell";

/** AI 분류 뷰 (3단계, docs/IMPROVEMENTS.md 결정): Synology Photos 내장 AI가
 * 이미 인덱싱한 얼굴(인물)·GPS(장소) 그룹을 읽어와 브라우즈하고, "전체 선택"
 * 으로 기존 선택→액션바(이동/복사/삭제+Undo) 파이프라인에 태워 정리한다.
 * 외부 AI API·NAS 추가 부하 없음.
 */

type Group =
  | { kind: "person"; id: string; label: string }
  | { kind: "place"; id: string; label: string };

function PersonCard({
  person,
  onOpen,
}: {
  person: PersonInfo;
  onOpen: () => void;
}) {
  const label = person.name || "이름 없는 인물";
  return (
    <button
      onClick={onOpen}
      title={label}
      className="flex w-24 flex-col items-center gap-1.5 rounded-xl p-2 hover:bg-slate-100"
    >
      {person.cover_item_id ? (
        <img
          src={thumbnailUrl(
            person.space,
            person.cover_item_id,
            person.cover_cache_key ?? "",
            "sm",
          )}
          alt={label}
          className="h-16 w-16 rounded-full bg-slate-200 object-cover"
          loading="lazy"
        />
      ) : (
        <span className="flex h-16 w-16 items-center justify-center rounded-full bg-slate-200 text-2xl">
          👤
        </span>
      )}
      <span
        className={`w-full truncate text-center text-xs ${
          person.name ? "text-slate-700" : "italic text-slate-400"
        }`}
      >
        {label}
      </span>
      {person.item_count != null && (
        <span className="-mt-1 text-[10px] text-slate-400">
          {person.item_count.toLocaleString()}장
        </span>
      )}
    </button>
  );
}

function PlaceChip({ place, onOpen }: { place: PlaceInfo; onOpen: () => void }) {
  return (
    <button
      onClick={onOpen}
      className="flex items-center gap-1.5 rounded-full border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
    >
      <span aria-hidden>📍</span>
      {place.name || "알 수 없는 장소"}
      {place.item_count != null && (
        <span className="text-xs text-slate-400">
          {place.item_count.toLocaleString()}
        </span>
      )}
    </button>
  );
}

export function ClassifyView() {
  const space = useTimelineStore((s) => s.space);
  const setOrdered = useTimelineStore((s) => s.setOrdered);
  const replaceSelection = useTimelineStore((s) => s.replaceSelection);
  const [group, setGroup] = useState<Group | null>(null);

  const personsQuery = useQuery({
    queryKey: ["persons", space],
    queryFn: () => api.persons(space),
    staleTime: 5 * 60_000,
  });
  const placesQuery = useQuery({
    queryKey: ["places", space],
    queryFn: () => api.places(space),
    staleTime: 5 * 60_000,
  });
  const persons = personsQuery.data?.persons ?? [];
  const places = placesQuery.data?.places ?? [];

  // Photos of the opened group — fed into the shared selection model so the
  // existing action bar / DnD / lightbox all work unchanged.
  const itemsQuery = useQuery({
    queryKey: ["classify-items", space, group?.kind, group?.id],
    queryFn: () =>
      group!.kind === "person"
        ? api.personItems(space, group!.id)
        : api.placeItems(space, group!.id),
    enabled: group != null,
  });
  const items = useMemo(
    () => (itemsQuery.data?.items ?? []).map((it) => ({ ...it, space })),
    [itemsQuery.data, space],
  );
  useEffect(() => {
    setOrdered(items);
  }, [items, setOrdered]);

  const gridRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = gridRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(Math.floor(el.clientWidth)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const rows = useMemo(
    () => (width > 0 && items.length > 0 ? layoutBucket("classify", items, width) : []),
    [items, width],
  );

  const empty =
    !personsQuery.isPending &&
    !placesQuery.isPending &&
    persons.length === 0 &&
    places.length === 0;

  return (
    <div className="h-full overflow-y-auto">
      {/* Header: breadcrumb + bulk-select suggestion */}
      <div
        data-no-boxselect
        className="sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b border-slate-100 bg-white/90 px-4 py-2 text-sm backdrop-blur"
      >
        <button
          onClick={() => setGroup(null)}
          className={`rounded px-1.5 py-0.5 ${
            group ? "text-blue-600 hover:bg-slate-100" : "font-semibold text-slate-700"
          }`}
        >
          ✨ 분류
        </button>
        {group && (
          <>
            <span className="text-slate-300">/</span>
            <span className="font-semibold text-slate-800">
              {group.kind === "person" ? "👤" : "📍"} {group.label}
              {!itemsQuery.isPending && ` (${items.length.toLocaleString()}장)`}
            </span>
            <button
              onClick={() => replaceSelection(items.map((i) => i.id))}
              disabled={items.length === 0}
              className="ml-2 rounded-lg border border-blue-200 px-2 py-1 text-xs text-blue-600 hover:bg-blue-50 disabled:opacity-40"
            >
              전체 선택
            </button>
            <span className="text-xs text-slate-400">
              선택 후 하단 액션바로 폴더 이동/복사 (또는 드래그)
            </span>
          </>
        )}
      </div>

      {/* width ref on the unpadded inner box (padded-box measurement makes
       * justified rows overflow the right padding) */}
      <div className="px-4 pb-10">
        <div ref={gridRef}>
        {!group && (
          <>
            <section className="py-4">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                인물 {personsQuery.isPending ? "" : `(${persons.length})`}
              </h3>
              {personsQuery.isPending && (
                <p className="py-4 text-sm text-slate-400">불러오는 중…</p>
              )}
              {personsQuery.isError && (
                <p className="py-4 text-sm text-red-500">
                  인물 정보를 불러오지 못했습니다.
                </p>
              )}
              {!personsQuery.isPending && !personsQuery.isError && persons.length === 0 && (
                <p className="py-4 text-sm text-slate-400">
                  인식된 인물이 없습니다 — Synology Photos 설정에서 "인물"
                  기능이 켜져 있는지 확인해 보세요.
                </p>
              )}
              <div className="flex flex-wrap gap-1">
                {persons.map((p) => (
                  <PersonCard
                    key={p.id}
                    person={p}
                    onOpen={() =>
                      setGroup({
                        kind: "person",
                        id: p.id,
                        label: p.name || "이름 없는 인물",
                      })
                    }
                  />
                ))}
              </div>
            </section>

            <section className="py-2">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                장소 {placesQuery.isPending ? "" : `(${places.length})`}
              </h3>
              {placesQuery.isPending && (
                <p className="py-4 text-sm text-slate-400">불러오는 중…</p>
              )}
              {!placesQuery.isPending && places.length === 0 && !placesQuery.isError && (
                <p className="py-4 text-sm text-slate-400">
                  위치 정보(GPS)가 있는 사진이 없습니다.
                </p>
              )}
              <div className="flex flex-wrap gap-1.5">
                {places.map((g) => (
                  <PlaceChip
                    key={g.id}
                    place={g}
                    onOpen={() =>
                      setGroup({ kind: "place", id: g.id, label: g.name })
                    }
                  />
                ))}
              </div>
            </section>

            {empty && (
              <p className="py-10 text-center text-sm text-slate-400">
                분류 데이터가 없습니다.
              </p>
            )}
          </>
        )}

        {group && (
          <section className="py-3">
            {itemsQuery.isPending && (
              <p className="py-6 text-center text-sm text-slate-400">불러오는 중…</p>
            )}
            {!itemsQuery.isPending && items.length === 0 && (
              <p className="py-6 text-center text-sm text-slate-400">
                이 그룹에 사진이 없습니다.
              </p>
            )}
            {rows.map(
              (row) =>
                row.kind === "photos" && (
                  <div key={row.key} style={{ position: "relative", height: row.height }}>
                    {row.cells.map((cell) => (
                      <PhotoCell key={cell.item.id} cell={cell} />
                    ))}
                  </div>
                ),
            )}
          </section>
        )}
        </div>
      </div>
    </div>
  );
}
