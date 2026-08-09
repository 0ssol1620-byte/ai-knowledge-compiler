import type { CSSProperties } from "react";

export type Bbox1000 = [number, number, number, number];

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

export function bboxStyle(value: Bbox1000): CSSProperties {
  const [x1, y1, x2, y2] = value;
  return {
    left: `${x1 / 10}%`,
    top: `${y1 / 10}%`,
    width: `${(x2 - x1) / 10}%`,
    height: `${(y2 - y1) / 10}%`,
  };
}
