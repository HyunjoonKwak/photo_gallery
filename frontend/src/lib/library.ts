import type { Space } from "../api/types";

/** Display label of the current library (셀렉터/뷰 헤더 공용). */
export function libraryLabel(space: Space, owner: string | null): string {
  if (owner) return `${owner}의 사진`;
  return space === "team" ? "공용 사진" : "내 사진";
}
