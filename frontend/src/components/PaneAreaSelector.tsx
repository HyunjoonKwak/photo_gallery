import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type AreaScope } from "../api/client";

/** 분할 뷰 페인별 영역 선택 — 공용/내사진/1차구역/타인. 영역 간(예 1차구역
 * →내사진) 폴더 이동을 위해 각 페인이 독립적으로 영역을 고른다. */
function areaId(a: AreaScope): string {
  return `${a.space}:${a.zone ?? ""}:${a.targetUser ?? ""}`;
}
function sameArea(a: AreaScope, b: AreaScope): boolean {
  return areaId(a) === areaId(b);
}

export function PaneAreaSelector({
  area,
  onChange,
}: {
  area: AreaScope;
  onChange: (a: AreaScope) => void;
}) {
  const [open, setOpen] = useState(false);
  const zonesQ = useQuery({
    queryKey: ["zones"],
    queryFn: api.listZones,
    staleTime: 5 * 60_000,
    retry: false,
  });
  const membersQ = useQuery({
    queryKey: ["members"],
    queryFn: api.members,
    staleTime: 5 * 60_000,
    retry: false,
  });
  const zones = zonesQ.data?.zones ?? [];
  const members = (membersQ.data?.members ?? []).filter((m) => m.has_photos);

  const options: { area: AreaScope; label: string }[] = [
    { area: { space: "team" }, label: "📚 가족 사진" },
    { area: { space: "personal" }, label: "👤 내 사진" },
    ...zones.map((z) => ({
      area: { space: "personal", zone: z.id } as AreaScope,
      label: `📦 ${z.label}`,
    })),
    ...members.map((m) => ({
      area: { space: "personal", targetUser: m.name } as AreaScope,
      label: `👥 ${m.name}`,
    })),
  ];
  const current = options.find((o) => sameArea(o.area, area)) ?? options[0];

  return (
    <div className="relative shrink-0" data-no-boxselect>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
      >
        <span className="truncate">{current.label}</span>
        <span className="text-slate-400">▾</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-40 mt-1 min-w-[10rem] overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
            {options.map((o) => {
              const active = sameArea(o.area, area);
              return (
                <button
                  key={areaId(o.area)}
                  onClick={() => {
                    onChange(o.area);
                    setOpen(false);
                  }}
                  className={`block w-full px-3 py-1.5 text-left text-xs ${
                    active
                      ? "bg-blue-50 font-semibold text-blue-700"
                      : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  {o.label}
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
