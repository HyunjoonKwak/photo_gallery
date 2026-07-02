declare module "justified-layout" {
  export interface JustifiedBox {
    aspectRatio: number;
    top: number;
    left: number;
    width: number;
    height: number;
  }

  export interface JustifiedResult {
    containerHeight: number;
    widowCount: number;
    boxes: JustifiedBox[];
  }

  export interface JustifiedConfig {
    containerWidth?: number;
    containerPadding?: number | { top: number; right: number; bottom: number; left: number };
    boxSpacing?: number | { horizontal: number; vertical: number };
    targetRowHeight?: number;
    targetRowHeightTolerance?: number;
    maxNumRows?: number;
    forceAspectRatio?: number | boolean;
    showWidows?: boolean;
    fullWidthBreakoutRowCadence?: number | boolean;
    widowLayoutStyle?: "left" | "justify" | "center";
  }

  export default function justifiedLayout(
    input: Array<number | { width: number; height: number }>,
    config?: JustifiedConfig,
  ): JustifiedResult;
}
