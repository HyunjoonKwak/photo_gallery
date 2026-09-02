/**
 * Join adjacent, already-loaded day buckets inside one visible timeline group.
 *
 * Month/year views do not render a header between individual days, so forcing
 * every day to start a new row leaves an unexplained gap whenever that day's
 * item count is not a multiple of the column count. Pending days remain their
 * own segments: this preserves viewport-driven loading and prevents one
 * visible placeholder from fetching an entire month or year at once.
 */

export type GroupDayRun<T> =
  | { kind: "loaded"; days: string[]; items: T[] }
  | { kind: "pending"; day: string; count: number };

export function groupLoadedDayRuns<T>(
  days: string[],
  loaded: ReadonlyMap<string, T[]>,
  countOf: (day: string) => number,
): GroupDayRun<T>[] {
  const runs: GroupDayRun<T>[] = [];
  let loadedDays: string[] = [];
  let loadedItems: T[] = [];

  const flushLoaded = () => {
    if (loadedDays.length === 0) return;
    runs.push({ kind: "loaded", days: loadedDays, items: loadedItems });
    loadedDays = [];
    loadedItems = [];
  };

  for (const day of days) {
    const items = loaded.get(day);
    if (items === undefined) {
      flushLoaded();
      runs.push({ kind: "pending", day, count: countOf(day) });
      continue;
    }
    loadedDays.push(day);
    loadedItems.push(...items);
  }
  flushLoaded();
  return runs;
}
