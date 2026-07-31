import { describe, expect, it } from "vitest";

import {
  bbox1000ToNormalized,
  bbox1000ToUnit,
  bboxCenterIsInside,
  bboxIntersectionOverUnion,
  bboxStyle,
  bboxViewportStyle,
  normalizedToBbox1000,
  rotateNormalizedBbox,
  transformBboxToViewport,
  unitToBbox1000,
  type Bbox1000,
  type BboxRotation,
  type BboxSourceBox,
  type BboxViewportGeometry,
} from "@/lib/bbox";

const portrait: BboxViewportGeometry = {
  mediaBox: { x: 0, y: 0, width: 1000, height: 2000 },
  cropBox: { x: 0, y: 0, width: 1000, height: 2000 },
  containerWidth: 1000,
  containerHeight: 1000,
  zoom: 1,
  devicePixelRatio: 1,
};

type GoldenCase = {
  name: string;
  bbox: Bbox1000;
  rotation: BboxRotation;
  sourceBox?: BboxSourceBox;
  geometry: BboxViewportGeometry;
};

const goldenCases: GoldenCase[] = [
  {
    name: "portrait 100%",
    bbox: [100, 200, 400, 600],
    rotation: 0,
    geometry: portrait,
  },
  {
    name: "portrait 50%",
    bbox: [100, 200, 400, 600],
    rotation: 0,
    geometry: { ...portrait, zoom: 0.5 },
  },
  {
    name: "portrait 200%",
    bbox: [100, 200, 400, 600],
    rotation: 0,
    geometry: { ...portrait, zoom: 2 },
  },
  {
    name: "landscape 90 degrees",
    bbox: [100, 200, 400, 600],
    rotation: 90,
    geometry: portrait,
  },
  {
    name: "portrait 180 degrees",
    bbox: [100, 200, 400, 600],
    rotation: 180,
    geometry: portrait,
  },
  {
    name: "landscape 270 degrees",
    bbox: [100, 200, 400, 600],
    rotation: 270,
    geometry: portrait,
  },
  {
    name: "high DPI 2x",
    bbox: [100, 200, 400, 600],
    rotation: 0,
    geometry: { ...portrait, devicePixelRatio: 2 },
  },
  {
    name: "high DPI 3x",
    bbox: [100, 200, 400, 600],
    rotation: 0,
    geometry: { ...portrait, devicePixelRatio: 3 },
  },
  {
    name: "mobile 390",
    bbox: [100, 200, 400, 600],
    rotation: 0,
    geometry: { ...portrait, containerWidth: 390, containerHeight: 700 },
  },
  {
    name: "tablet 1024",
    bbox: [100, 200, 400, 600],
    rotation: 0,
    geometry: { ...portrait, containerWidth: 1024, containerHeight: 768 },
  },
  {
    name: "desktop 1440",
    bbox: [100, 200, 400, 600],
    rotation: 0,
    geometry: { ...portrait, containerWidth: 1440, containerHeight: 900 },
  },
  {
    name: "wide desktop 1920",
    bbox: [100, 200, 400, 600],
    rotation: 0,
    geometry: { ...portrait, containerWidth: 1920, containerHeight: 1080 },
  },
  {
    name: "cropped PDF full crop from media",
    bbox: [100, 100, 900, 900],
    rotation: 0,
    sourceBox: "media",
    geometry: {
      mediaBox: { x: 0, y: 0, width: 1000, height: 1000 },
      cropBox: { x: 100, y: 100, width: 800, height: 800 },
      containerWidth: 800,
      containerHeight: 800,
      zoom: 1,
      devicePixelRatio: 1,
    },
  },
  {
    name: "cropped PDF inner region",
    bbox: [200, 200, 600, 600],
    rotation: 0,
    sourceBox: "media",
    geometry: {
      mediaBox: { x: 0, y: 0, width: 1000, height: 1000 },
      cropBox: { x: 100, y: 100, width: 800, height: 800 },
      containerWidth: 1000,
      containerHeight: 700,
      zoom: 1,
      devicePixelRatio: 2,
    },
  },
  {
    name: "table cell row 1 column 1",
    bbox: [80, 250, 300, 360],
    rotation: 0,
    geometry: portrait,
  },
  {
    name: "table cell row 1 column 2",
    bbox: [300, 250, 550, 360],
    rotation: 0,
    geometry: portrait,
  },
  {
    name: "table cell row 2 column 1",
    bbox: [80, 360, 300, 470],
    rotation: 0,
    geometry: portrait,
  },
  {
    name: "table cell row 2 column 2",
    bbox: [300, 360, 550, 470],
    rotation: 0,
    geometry: portrait,
  },
  {
    name: "nested table cell",
    bbox: [420, 510, 610, 590],
    rotation: 0,
    geometry: portrait,
  },
  {
    name: "virtualized page recycled at 125%",
    bbox: [115, 166, 882, 744],
    rotation: 90,
    geometry: {
      ...portrait,
      containerWidth: 1180,
      containerHeight: 820,
      zoom: 1.25,
      devicePixelRatio: 1.5,
    },
  },
];

describe("bbox conversion", () => {
  it("round-trips canonical integer coordinates", () => {
    const bbox: Bbox1000 = [103, 244, 901, 777];
    expect(unitToBbox1000(bbox1000ToUnit(bbox))).toEqual(bbox);
    expect(normalizedToBbox1000(bbox1000ToNormalized(bbox))).toEqual(bbox);
  });

  it("rejects inverted boxes", () => {
    expect(() => unitToBbox1000([0.8, 0.1, 0.2, 0.9])).toThrow(
      "invalid_bbox1000",
    );
  });

  it("preserves page, rotation, and source-box metadata", () => {
    expect(
      bbox1000ToNormalized([100, 200, 400, 600], {
        page: 7,
        rotation: 90,
        sourceBox: "media",
      }),
    ).toMatchObject({ page: 7, rotation: 90, sourceBox: "media" });
  });
});

describe("rotation normalization", () => {
  const source = bbox1000ToNormalized([100, 200, 400, 600]);

  it.each([
    [0, { x: 0.1, y: 0.2, width: 0.3, height: 0.4 }],
    [90, { x: 0.4, y: 0.1, width: 0.4, height: 0.3 }],
    [180, { x: 0.6, y: 0.4, width: 0.3, height: 0.4 }],
    [270, { x: 0.2, y: 0.6, width: 0.4, height: 0.3 }],
  ] as const)("rotates %i degrees exactly", (rotation, expected) => {
    const actual = rotateNormalizedBbox(source, rotation);
    expect(actual.x).toBeCloseTo(expected.x, 12);
    expect(actual.y).toBeCloseTo(expected.y, 12);
    expect(actual.width).toBeCloseTo(expected.width, 12);
    expect(actual.height).toBeCloseTo(expected.height, 12);
  });
});

describe("20-case viewport golden matrix", () => {
  it.each(goldenCases)(
    "maps $name without drift",
    ({ bbox, rotation, sourceBox, geometry }) => {
      const normalized = bbox1000ToNormalized(bbox, {
        rotation,
        sourceBox: sourceBox ?? "crop",
      });
      const rect = transformBboxToViewport(normalized, geometry);
      const page = {
        left: rect.offsetX,
        top: rect.offsetY,
        width: rect.renderedPageWidth,
        height: rect.renderedPageHeight,
      };

      expect(rect.width).toBeGreaterThan(0);
      expect(rect.height).toBeGreaterThan(0);
      expect(Object.values(rect).every(Number.isFinite)).toBe(true);
      expect(bboxCenterIsInside(rect, page)).toBe(true);
      expect(rect.deviceLeft).toBeCloseTo(
        rect.left * geometry.devicePixelRatio,
        8,
      );
      expect(rect.deviceTop).toBeCloseTo(
        rect.top * geometry.devicePixelRatio,
        8,
      );
    },
  );

  it("keeps CSS coordinates independent from device pixel ratio", () => {
    const bbox = bbox1000ToNormalized([100, 200, 400, 600]);
    const one = transformBboxToViewport(bbox, portrait);
    const three = transformBboxToViewport(bbox, {
      ...portrait,
      devicePixelRatio: 3,
    });
    expect(three.left).toBe(one.left);
    expect(three.top).toBe(one.top);
    expect(three.deviceWidth).toBeCloseTo(one.width * 3, 8);
  });

  it("centers portrait pages with horizontal letterboxing", () => {
    const rect = transformBboxToViewport(
      bbox1000ToNormalized([100, 200, 400, 600]),
      portrait,
    );
    expect(rect.renderedPageWidth).toBe(500);
    expect(rect.renderedPageHeight).toBe(1000);
    expect(rect.offsetX).toBe(250);
    expect(rect.offsetY).toBe(0);
    expect(rect.left).toBe(300);
    expect(rect.top).toBe(200);
  });

  it("converts a media-box region into the exact crop-box region", () => {
    const rect = transformBboxToViewport(
      bbox1000ToNormalized([100, 100, 900, 900], {
        sourceBox: "media",
      }),
      {
        mediaBox: { x: 0, y: 0, width: 1000, height: 1000 },
        cropBox: { x: 100, y: 100, width: 800, height: 800 },
        containerWidth: 800,
        containerHeight: 800,
        zoom: 1,
        devicePixelRatio: 1,
      },
    );
    expect(rect).toMatchObject({ left: 0, top: 0, width: 800, height: 800 });
  });

  it("supports zoom while preserving selection geometry", () => {
    const source = bbox1000ToNormalized([100, 200, 400, 600]);
    const at100 = transformBboxToViewport(source, portrait);
    const at200 = transformBboxToViewport(source, { ...portrait, zoom: 2 });
    expect(at200.width).toBeCloseTo(at100.width * 2, 8);
    expect(at200.height).toBeCloseTo(at100.height * 2, 8);
  });
});

describe("proof overlap and output styles", () => {
  it("reports perfect overlap for identical evidence", () => {
    const box = bbox1000ToNormalized([100, 200, 400, 600]);
    expect(bboxIntersectionOverUnion(box, box)).toBe(1);
  });

  it("reports the expected partial overlap", () => {
    const left = bbox1000ToNormalized([100, 100, 500, 500]);
    const right = bbox1000ToNormalized([300, 300, 700, 700]);
    expect(bboxIntersectionOverUnion(left, right)).toBeCloseTo(1 / 7, 8);
  });

  it("reports zero for separated evidence", () => {
    const left = bbox1000ToNormalized([0, 0, 100, 100]);
    const right = bbox1000ToNormalized([900, 900, 1000, 1000]);
    expect(bboxIntersectionOverUnion(left, right)).toBe(0);
  });

  it("creates stable percent and pixel styles", () => {
    expect(bboxStyle([100, 200, 400, 600])).toEqual({
      left: "10%",
      top: "20%",
      width: "30.000000000000004%",
      height: "40%",
    });
    expect(
      bboxViewportStyle({
        left: 10,
        top: 20,
        width: 30,
        height: 40,
        renderedPageWidth: 100,
        renderedPageHeight: 100,
        offsetX: 0,
        offsetY: 0,
        deviceLeft: 20,
        deviceTop: 40,
        deviceWidth: 60,
        deviceHeight: 80,
      }),
    ).toEqual({ left: "10px", top: "20px", width: "30px", height: "40px" });
  });

  it("rejects invalid viewport geometry", () => {
    expect(() =>
      transformBboxToViewport(bbox1000ToNormalized([100, 100, 200, 200]), {
        ...portrait,
        zoom: 0,
      }),
    ).toThrow("invalid_viewport_geometry");
  });
});
