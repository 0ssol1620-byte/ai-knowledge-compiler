import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function StructaraAppleIcon() {
  return new ImageResponse(
    <div
      style={{
        display: "flex",
        width: "180px",
        height: "180px",
        alignItems: "center",
        justifyContent: "center",
        borderRadius: "38px",
        background:
          "linear-gradient(145deg, #17283d 0%, #0d1623 58%, #09111c 100%)",
      }}
    >
      <div
        style={{
          position: "relative",
          display: "flex",
          width: "106px",
          height: "106px",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: "5px 34px 52px 5px",
            border: "5px solid #f7f2e8",
            borderRadius: "9px",
            background: "rgba(247,242,232,0.07)",
            boxShadow: "0 16px 36px rgba(0,0,0,0.22)",
          }}
        />
        <div
          style={{
            position: "absolute",
            inset: "52px 5px 5px 34px",
            border: "5px solid #5b8fff",
            borderRadius: "9px",
            background: "rgba(91,143,255,0.14)",
            boxShadow: "0 16px 36px rgba(0,0,0,0.22)",
          }}
        />
        <div
          style={{
            position: "absolute",
            width: "64px",
            height: "5px",
            borderRadius: "999px",
            background: "#58c7df",
            transform: "rotate(-35deg)",
            boxShadow: "0 0 18px rgba(88,199,223,0.35)",
          }}
        />
      </div>
    </div>,
    size,
  );
}
