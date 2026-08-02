"use client";

import { SignatureScene } from "@/components/creative-review/folynta-creative-review";
import creativeStyles from "@/components/creative-review/folynta-creative-review.module.css";
import type { StructaraLocale } from "@/lib/locale";

export function hasUsableWebGL2(
  canvas: HTMLCanvasElement = document.createElement("canvas"),
) {
  try {
    const context = canvas.getContext("webgl2", {
      failIfMajorPerformanceCaveat: true,
    });
    if (!context) return false;
    context.getExtension("WEBGL_lose_context")?.loseContext();
    return true;
  } catch {
    return false;
  }
}

export function StructaraHeroScene({ locale }: { locale: StructaraLocale }) {
  return (
    <div
      className="st-hero-scene folynta-folio-hero"
      data-enhanced="false"
      data-settled="true"
      data-direction="folio-synthesis"
      data-truth-class="deterministic-first-party-t1"
    >
      <div className={creativeStyles.publicSignature} aria-hidden="true">
        <SignatureScene direction="folio" />
      </div>
      <p className="sr-only">
        {locale === "ko"
          ? "보고서, 원장, 논문, 슬라이드, 스캔 문서 등 열두 유형의 원문이 검증된 하나의 folio와 원문 영수증으로 컴파일됩니다."
          : "Twelve source types compile into one verified folio while an evidence receipt preserves the route to the exact source."}
      </p>
      <div className="st-hero-scene-meta">
        <small>12 SOURCES → 1 VERIFIED FOLIO → SOURCE RECEIPT</small>
      </div>
    </div>
  );
}
