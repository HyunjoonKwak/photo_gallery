import type { PhotoItem, Space } from "../../api/types";
import { useTimelineStore } from "../../store/timeline";
import { UniformPhotoGrid } from "./UniformPhotoGrid";
import { MasonryPhotoGrid } from "./MasonryPhotoGrid";

/** 배치를 고를 만한 최소 장수. 몇 장 안 되면 정사각이든 메이슨리든 같아 보여
 * 단추만 사진을 가린다. */
const MIN_FOR_TOGGLE = 12;

/**
 * 사진 그리드 — 배치는 보는 사람이 고른다(정사각 | 메이슨리).
 *
 * 앨범·사람·장소·비디오가 모두 이걸 쓴다. 고른 값은 기기에 남아
 * (`store.photoLayout` → localStorage) 화면을 옮겨도 따라온다.
 */
export function PhotoGrid({
  items,
  space,
}: {
  items: PhotoItem[];
  space?: Space;
}) {
  const layout = useTimelineStore((s) => s.photoLayout);
  return (
    <div className="relative h-full">
      {layout === "masonry" ? (
        <MasonryPhotoGrid items={items} space={space} />
      ) : (
        <UniformPhotoGrid items={items} space={space} />
      )}
      {items.length >= MIN_FOR_TOGGLE && <PhotoLayoutToggle />}
    </div>
  );
}

/** 배치 전환 — 그리드 좌상단에 떠 있다(우측은 날짜 스크러버 자리). */
function PhotoLayoutToggle() {
  const layout = useTimelineStore((s) => s.photoLayout);
  const setLayout = useTimelineStore((s) => s.setPhotoLayout);
  const next = layout === "masonry" ? "square" : "masonry";
  return (
    <button
      data-no-boxselect
      onClick={() => setLayout(next)}
      title={
        layout === "masonry"
          ? "정사각으로 보기 — 칸이 고르게 맞습니다"
          : "비율 그대로 보기 — 세로 사진이 잘리지 않습니다"
      }
      className="absolute left-2 top-2 z-20 rounded-full bg-white/85 px-2.5 py-1 text-xs font-medium text-slate-600 shadow-sm backdrop-blur transition-colors hover:bg-white hover:text-slate-900"
    >
      {layout === "masonry" ? "▦ 정사각" : "▥ 비율"}
    </button>
  );
}
