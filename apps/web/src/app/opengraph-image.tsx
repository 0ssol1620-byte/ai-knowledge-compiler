import { ImageResponse } from "next/og";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function StructaraOpenGraphImage() {
  return new ImageResponse(
    <div
      style={{
        position: "relative",
        display: "flex",
        width: "1200px",
        height: "630px",
        overflow: "hidden",
        background: "#f4efe4",
        color: "#111820",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: "0",
          display: "flex",
          opacity: 0.28,
          backgroundImage:
            "linear-gradient(rgba(17,24,32,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(17,24,32,0.08) 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: "0",
          right: "0",
          display: "flex",
          width: "310px",
          height: "630px",
          background: "#0d1623",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: "180px",
          right: "105px",
          display: "flex",
          width: "112px",
          height: "148px",
          border: "3px solid #f7f2e8",
          borderRadius: "12px",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: "246px",
          right: "63px",
          display: "flex",
          width: "112px",
          height: "148px",
          border: "3px solid #5b8fff",
          borderRadius: "12px",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: "289px",
          right: "115px",
          display: "flex",
          width: "82px",
          height: "3px",
          background: "#58c7df",
          transform: "rotate(-34deg)",
        }}
      />

      <div
        style={{
          position: "relative",
          display: "flex",
          width: "890px",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px 78px 62px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          <div
            style={{
              display: "flex",
              width: "44px",
              height: "44px",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: "10px",
              background: "#0d1623",
              color: "#f7f2e8",
              fontSize: "22px",
              fontWeight: 700,
            }}
          >
            S
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "3px" }}>
            <span
              style={{
                fontSize: "24px",
                fontWeight: 700,
                letterSpacing: "-0.03em",
              }}
            >
              FOLYNTA
            </span>
            <span
              style={{
                color: "#627080",
                fontSize: "13px",
                letterSpacing: "0.12em",
                textTransform: "uppercase",
              }}
            >
              Knowledge Compiler
            </span>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          <div
            style={{
              display: "flex",
              width: "76px",
              height: "5px",
              background: "#2667ff",
            }}
          />
          <h1
            style={{
              maxWidth: "760px",
              margin: "0",
              fontFamily: "Georgia, serif",
              fontSize: "72px",
              fontWeight: 500,
              letterSpacing: "-0.052em",
              lineHeight: 0.99,
            }}
          >
            The Knowledge Compiler for AI
          </h1>
          <p
            style={{
              maxWidth: "730px",
              margin: "0",
              color: "#526171",
              fontSize: "23px",
              lineHeight: 1.42,
            }}
          >
            Turn source documents into structured, verified, connected, and
            portable knowledge.
          </p>
        </div>

        <div style={{ display: "flex", color: "#627080", fontSize: "14px" }}>
          Source → Structure → Evidence → Knowledge
        </div>
      </div>
    </div>,
    size,
  );
}
