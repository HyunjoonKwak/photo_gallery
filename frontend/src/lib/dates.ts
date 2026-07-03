/** Date formatting helpers for the timeline (Korean locale). */

const HEADER_FMT = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "long",
  day: "numeric",
  weekday: "short",
});

/** Local YYYY-MM-DD for a Date ("sv-SE" locale formats exactly this way). */
function localIso(d: Date): string {
  return d.toLocaleDateString("sv-SE");
}

export function formatDayHeader(day: string): string {
  const now = new Date();
  if (day === localIso(now)) return "오늘";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (day === localIso(yesterday)) return "어제";
  return HEADER_FMT.format(new Date(`${day}T00:00:00`));
}

/** "2026년 6월" from a YYYY-MM-DD (or YYYY-MM) string. */
export function formatMonth(day: string): string {
  return `${Number(day.slice(0, 4))}년 ${Number(day.slice(5, 7))}월`;
}

export function formatBytes(n: number | null): string {
  if (n == null) return "";
  if (n < 1024 * 1024) return `${Math.round(n / 1024)}KB`;
  return `${(n / (1024 * 1024)).toFixed(1)}MB`;
}


/** Video duration for badges: "0:34", "12:05", "1:02:33". */
export function formatDuration(ms: number): string {
  const total = Math.round(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return `${h > 0 ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}
