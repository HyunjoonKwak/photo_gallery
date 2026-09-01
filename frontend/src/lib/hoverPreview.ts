/**
 * 그리드에서 동영상 위에 마우스를 올리면 잠깐 재생해 보여 준다.
 * 그 재생권을 **한 번에 하나만** 갖게 하는 잠금.
 *
 * 그리드를 빠르게 훑으면 지나간 타일들이 저마다 재생을 붙들고 남는다.
 * 이 앱의 동영상은 NAS 에서 Range 프록시로 흘러오므로, 여러 개가 동시에
 * 돌면 화면이 버벅이는 데서 그치지 않고 **커넥션 풀까지 함께 먹는다**
 * (2026-07 PoolTimeout 사례와 같은 길). 그래서 새 미리보기가 시작될 때
 * 앞의 것을 끈다.
 *
 * 열쇠와 끄는 함수를 따로 받는 이유: 끄는 함수가 자기 자신을 열쇠로 쓰면
 * 함수 안에서 자기 이름을 불러야 해서 «선언 전 참조»가 된다.
 */

/** 타일 하나를 알아보는 열쇠. 타일이 사는 동안 같은 객체여야 한다. */
export type PreviewKey = object;

let active: { key: PreviewKey; stop: () => void } | null = null;

/** 이 타일이 재생권을 잡는다. 앞의 것은 꺼진다. */
export function claimHoverPreview(key: PreviewKey, stop: () => void) {
  if (active?.key === key) return;
  active?.stop();
  active = { key, stop };
}

/** 이 타일이 재생권을 놓는다. 이미 남에게 넘어갔으면 아무것도 하지 않는다. */
export function releaseHoverPreview(key: PreviewKey) {
  if (active?.key === key) active = null;
}

/** 마우스를 올린 뒤 재생까지 기다리는 시간. 스쳐 지나갈 때는 재생하지 않는다. */
export const HOVER_DELAY_MS = 400;

/**
 * 움직임을 줄여 달라고 한 사람에게는 자동 재생하지 않는다.
 * 매번 물어보는 이유: 설정은 보는 도중에도 바뀐다.
 */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );
}
