import type { CSSProperties } from "react";

export type Bbox1000 = [number, number, number, number];
export type BboxRotation = 0 | 90 | 180 | 270;
export type BboxSourceBox = "crop" | "media";

export type NormalizedBbox = {
  x: number;
  y: number;
  width: number;
  height: number;
  page: number;
  rotation: BboxRotation;
  sourceBox: BboxSourceBox;
};

export type PdfBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type BboxViewportGeometry = {
  mediaBox: PdfBox;
  cropBox: PdfBox;
  containerWidth: number;
  containerHeight: number;
  zoom: number;
  devicePixelRatio: number;
};

export type BboxViewportRect = {
  left: number;
  top: number;
  width: number;
  height: number;
  renderedPageWidth: number;
  renderedPageHeight: number;
  offsetX: number;
  offsetY: number;
  deviceLeft: number;
  deviceTop: number;
  deviceWidth: number;
  deviceHeight: number;
};

export function assertBbox1000(
  value: readonly number[],
): asserts value is Bbox1000 {
  if (
    value.length !== 4 ||
    value.some(
      (coordinate) =>
        !Number.isInteger(coordinate) || coordinate < 0 || coordinate > 1000,
    ) ||
    value[0]! >= value[2]! ||
    value[1]! >= value[3]!
  ) {
    throw new Error("invalid_bbox1000");
  }
}

export function bbox1000ToUnit(
  value: Bbox1000,
): [number, number, number, number] {
  assertBbox1000(value);
  return value.map((coordinate) => coordinate / 1000) as [
    number,
    number,
    number,
    number,
  ];
}

export function unitToBbox1000(value: readonly number[]): Bbox1000 {
  if (
    value.length !== 4 ||
    value.some(
      (coordinate) =>
        !Number.isFinite(coordinate) || coordinate < 0 || coordinate > 1,
    )
  ) {
    throw new Error("invalid_unit_bbox");
  }
  const bbox = value.map((coordinate) => Math.round(coordinate * 1000));
  assertBbox1000(bbox);
  return bbox;
}

export function bbox1000ToNormalized(
  value: Bbox1000,
  options: {
    page?: number;
    rotation?: BboxRotation;
    sourceBox?: BboxSourceBox;
  } = {},
): NormalizedBbox {
  const [x1, y1, x2, y2] = bbox1000ToUnit(value);
  return {
    x: x1,
    y: y1,
    width: x2 - x1,
    height: y2 - y1,
    page: options.page ?? 1,
    rotation: options.rotation ?? 0,
    sourceBox: options.sourceBox ?? "crop",
  };
}

export function normalizedToBbox1000(value: NormalizedBbox): Bbox1000 {
  assertNormalizedBbox(value);
  return unitToBbox1000([
    value.x,
    value.y,
    value.x + value.width,
    value.y + value.height,
  ]);
}

export function rotateNormalizedBbox(
  value: NormalizedBbox,
  rotation: BboxRotation = value.rotation,
): NormalizedBbox {
  assertNormalizedBbox(value);
  const { x, y, width, height } = value;
  const rotated =
    rotation === 90
      ? { x: 1 - y - height, y: x, width: height, height: width }
      : rotation === 180
        ? {
            x: 1 - x - width,
            y: 1 - y - height,
            width,
            height,
          }
        : rotation === 270
          ? { x: y, y: 1 - x - width, width: height, height: width }
          : { x, y, width, height };
  return { ...value, ...rotated, rotation };
}

export function transformBboxToViewport(
  value: NormalizedBbox,
  geometry: BboxViewportGeometry,
): BboxViewportRect {
  assertNormalizedBbox(value);
  assertPdfBox(geometry.mediaBox, "media_box");
  assertPdfBox(geometry.cropBox, "crop_box");
  if (
    !Number.isFinite(geometry.containerWidth) ||
    !Number.isFinite(geometry.containerHeight) ||
    geometry.containerWidth <= 0 ||
    geometry.containerHeight <= 0 ||
    !Number.isFinite(geometry.zoom) ||
    geometry.zoom <= 0 ||
    !Number.isFinite(geometry.devicePixelRatio) ||
    geometry.devicePixelRatio <= 0
  ) {
    throw new Error("invalid_viewport_geometry");
  }

  const cropNormalized =
    value.sourceBox === "media"
      ? mediaNormalizedToCropNormalized(
          value,
          geometry.mediaBox,
          geometry.cropBox,
        )
      : value;
  const rotated = rotateNormalizedBbox(cropNormalized, value.rotation);
  const swapsAxes = value.rotation === 90 || value.rotation === 270;
  const pageWidth = swapsAxes
    ? geometry.cropBox.height
    : geometry.cropBox.width;
  const pageHeight = swapsAxes
    ? geometry.cropBox.width
    : geometry.cropBox.height;
  const fitScale = Math.min(
    geometry.containerWidth / pageWidth,
    geometry.containerHeight / pageHeight,
  );
  const cssScale = fitScale * geometry.zoom;
  const renderedPageWidth = pageWidth * cssScale;
  const renderedPageHeight = pageHeight * cssScale;
  const offsetX = (geometry.containerWidth - renderedPageWidth) / 2;
  const offsetY = (geometry.containerHeight - renderedPageHeight) / 2;
  const left = offsetX + rotated.x * renderedPageWidth;
  const top = offsetY + rotated.y * renderedPageHeight;
  const width = rotated.width * renderedPageWidth;
  const height = rotated.height * renderedPageHeight;
  const dpr = geometry.devicePixelRatio;

  return {
    left,
    top,
    width,
    height,
    renderedPageWidth,
    renderedPageHeight,
    offsetX,
    offsetY,
    deviceLeft: left * dpr,
    deviceTop: top * dpr,
    deviceWidth: width * dpr,
    deviceHeight: height * dpr,
  };
}

export function bboxViewportStyle(rect: BboxViewportRect): CSSProperties {
  return {
    left: `${rect.left}px`,
    top: `${rect.top}px`,
    width: `${rect.width}px`,
    height: `${rect.height}px`,
  };
}

export function bboxStyle(value: Bbox1000): CSSProperties {
  const normalized = bbox1000ToNormalized(value);
  return {
    left: `${normalized.x * 100}%`,
    top: `${normalized.y * 100}%`,
    width: `${normalized.width * 100}%`,
    height: `${normalized.height * 100}%`,
  };
}

export function bboxIntersectionOverUnion(
  left: Pick<NormalizedBbox, "x" | "y" | "width" | "height">,
  right: Pick<NormalizedBbox, "x" | "y" | "width" | "height">,
): number {
  const intersectionWidth = Math.max(
    0,
    Math.min(left.x + left.width, right.x + right.width) -
      Math.max(left.x, right.x),
  );
  const intersectionHeight = Math.max(
    0,
    Math.min(left.y + left.height, right.y + right.height) -
      Math.max(left.y, right.y),
  );
  const intersection = intersectionWidth * intersectionHeight;
  const union =
    left.width * left.height + right.width * right.height - intersection;
  return union <= 0 ? 0 : intersection / union;
}

export function bboxCenterIsInside(
  inner: Pick<BboxViewportRect, "left" | "top" | "width" | "height">,
  outer: Pick<BboxViewportRect, "left" | "top" | "width" | "height">,
): boolean {
  const centerX = inner.left + inner.width / 2;
  const centerY = inner.top + inner.height / 2;
  return (
    centerX >= outer.left &&
    centerX <= outer.left + outer.width &&
    centerY >= outer.top &&
    centerY <= outer.top + outer.height
  );
}

function mediaNormalizedToCropNormalized(
  value: NormalizedBbox,
  media: PdfBox,
  crop: PdfBox,
): NormalizedBbox {
  const absoluteX = media.x + value.x * media.width;
  const absoluteY = media.y + value.y * media.height;
  const absoluteWidth = value.width * media.width;
  const absoluteHeight = value.height * media.height;
  const converted: NormalizedBbox = {
    ...value,
    x: (absoluteX - crop.x) / crop.width,
    y: (absoluteY - crop.y) / crop.height,
    width: absoluteWidth / crop.width,
    height: absoluteHeight / crop.height,
    sourceBox: "crop",
  };
  assertNormalizedBbox(converted);
  return converted;
}

function assertNormalizedBbox(value: NormalizedBbox): void {
  if (
    !Number.isInteger(value.page) ||
    value.page < 1 ||
    ![0, 90, 180, 270].includes(value.rotation) ||
    ![value.x, value.y, value.width, value.height].every(Number.isFinite) ||
    value.x < 0 ||
    value.y < 0 ||
    value.width <= 0 ||
    value.height <= 0 ||
    value.x + value.width > 1 + Number.EPSILON * 8 ||
    value.y + value.height > 1 + Number.EPSILON * 8
  ) {
    throw new Error("invalid_normalized_bbox");
  }
}

function assertPdfBox(value: PdfBox, label: string): void {
  if (
    ![value.x, value.y, value.width, value.height].every(Number.isFinite) ||
    value.width <= 0 ||
    value.height <= 0
  ) {
    throw new Error(`invalid_${label}`);
  }
}
