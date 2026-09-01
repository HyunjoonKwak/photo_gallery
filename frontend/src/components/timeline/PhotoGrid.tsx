import type { PhotoItem, Space } from "../../api/types";
import { useTimelineStore } from "../../store/timeline";
import { UniformPhotoGrid } from "./UniformPhotoGrid";
import { MasonryPhotoGrid } from "./MasonryPhotoGrid";

/**
 * 사진 그리드 — 배치는 보는 사람이 고른다(정사각 | 메이슨리).
 *
 * 앨범·사람·장소·비디오가 모두 이걸 쓴다. 고른 값은 기기에 남아
 * (`store.photoLayout` → localStorage) 화면을 옮겨도 따라온다.
 * 전환 단추는 여기 있지 않다 — 렌즈 바와 앨범 머리줄의 늘 같은 자리에 둔다
 * (`PhotoLayoutToggle`). 사진 위에 떠 있으면 첫 장을 가리고, 정작 타임라인
 * 에서는 이 컴포넌트를 쓰지 않아 만날 수조차 없었다.
 */
export function PhotoGrid({
  items,
  space,
}: {
  items: PhotoItem[];
  space?: Space;
}) {
  const layout = useTimelineStore((s) => s.photoLayout);
  return layout === "masonry" ? (
    <MasonryPhotoGrid items={items} space={space} />
  ) : (
    <UniformPhotoGrid items={items} space={space} />
  );
}
