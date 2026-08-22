import { ImageResponse } from "next/og";

export const size = { width: 64, height: 64 };
export const contentType = "image/png";

export default function StructaraIcon() {
  return new ImageResponse(
    <div
      style={{
        display: "flex",
        width: "64px",
        height: "64px",
        alignItems: "center",
        justifyContent: "center",
        borderRadius: "14px",
        background: "#0d1623",
      }}
    >
      <div
        style={{
          position: "relative",
          display: "flex",
          width: "38px",
          height: "38px",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: "2px 12px 18px 2px",
            border: "2px solid #f7f2e8",
            borderRadius: "3px",
            background: "rgba(247,242,232,0.08)",
          }}
        />
        <div
          style={{
            position: "absolute",
            inset: "18px 2px 2px 12px",
            border: "2px solid #5b8fff",
            borderRadius: "3px",
            background: "rgba(91,143,255,0.15)",
          }}
        />
        <div
          style={{
            position: "absolute",
            width: "22px",
            height: "2px",
            background: "#58c7df",
            transform: "rotate(-35deg)",
          }}
        />
      </div>
    </div>,
    size,
  );
}
