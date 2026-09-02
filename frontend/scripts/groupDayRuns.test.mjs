import assert from "node:assert/strict";
import test from "node:test";

import { groupLoadedDayRuns } from "../src/lib/groupDayRuns.ts";

test("adjacent loaded days share one run in newest-first order", () => {
  const days = ["2026-09-03", "2026-09-02", "2026-09-01"];
  const loaded = new Map([
    ["2026-09-03", ["a", "b"]],
    ["2026-09-02", ["c"]],
    ["2026-09-01", ["d", "e"]],
  ]);

  assert.deepEqual(groupLoadedDayRuns(days, loaded, () => 0), [
    {
      kind: "loaded",
      days,
      items: ["a", "b", "c", "d", "e"],
    },
  ]);
});

test("a pending day breaks loaded runs and stays independently loadable", () => {
  const days = ["2026-09-04", "2026-09-03", "2026-09-02", "2026-09-01"];
  const loaded = new Map([
    ["2026-09-04", ["a"]],
    ["2026-09-02", ["b"]],
    ["2026-09-01", ["c"]],
  ]);

  assert.deepEqual(groupLoadedDayRuns(days, loaded, (day) => (day.endsWith("03") ? 7 : 0)), [
    { kind: "loaded", days: ["2026-09-04"], items: ["a"] },
    { kind: "pending", day: "2026-09-03", count: 7 },
    {
      kind: "loaded",
      days: ["2026-09-02", "2026-09-01"],
      items: ["b", "c"],
    },
  ]);
});

test("an explicitly loaded empty day still joins its neighbors", () => {
  const days = ["2026-09-03", "2026-09-02", "2026-09-01"];
  const loaded = new Map([
    ["2026-09-03", ["a"]],
    ["2026-09-02", []],
    ["2026-09-01", ["b"]],
  ]);

  assert.deepEqual(groupLoadedDayRuns(days, loaded, () => 0), [
    {
      kind: "loaded",
      days,
      items: ["a", "b"],
    },
  ]);
});
