import { ImageResponse } from "next/og";

export const alt =
  "FOLYNTA — structured, verified, connected knowledge for people and AI";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        padding: "70px 76px",
        background: "#F5F3EE",
        color: "#101216",
        fontFamily: "Arial, sans-serif",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <div
          style={{
            width: 34,
            height: 44,
            border: "2px solid #101216",
            display: "flex",
          }}
        />
        <div style={{ fontSize: 28, fontWeight: 700 }}>FOLYNTA</div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
        <div
          style={{
            maxWidth: 900,
            fontSize: 74,
            lineHeight: 1.02,
            letterSpacing: "-4px",
          }}
        >
          The Knowledge Compiler for AI
        </div>
        <div style={{ fontSize: 24, color: "#34383F" }}>
          Page → Structure → Evidence → Knowledge → Intelligence
        </div>
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          paddingTop: 24,
          borderTop: "1px solid #DEDFDC",
          fontSize: 18,
          color: "#34383F",
        }}
      >
        <span>Structured. Verified. Connected. Portable.</span>
        <span>Source-linked by design</span>
      </div>
    </div>,
    size,
  );
}
