"use client";

import { useState } from "react";

import { StructaraProofDemo } from "@/components/tavonel-proof-demo";
import { StructaraSecProofDemo } from "@/components/structara-sec-proof-demo";
import type { StructaraLocale } from "@/lib/locale";

type Market = "dart" | "sec";

const COPY = {
  en: {
    label: "Public proof market",
    dart: "DART · Korea",
    sec: "SEC · United States",
    disclosure:
      "The market changes the registered public source fixture; it never changes a benchmark or customer claim.",
  },
  ko: {
    label: "공개 근거 시장",
    dart: "DART · 한국",
    sec: "SEC · 미국",
    disclosure:
      "시장을 바꾸면 등록된 공개 원문 픽스처만 바뀌며, 벤치마크나 고객 주장을 대신하지 않습니다.",
  },
} as const;

export function PublicProofSwitcher({ locale }: { locale: StructaraLocale }) {
  const [market, setMarket] = useState<Market>(
    locale === "ko" ? "dart" : "sec",
  );
  const copy = COPY[locale];

  return (
    <div className="folynta-proof-switcher" data-market={market}>
      <div className="folynta-proof-market-bar">
        <div role="group" aria-label={copy.label}>
          <button
            type="button"
            aria-pressed={market === "dart"}
            onClick={() => setMarket("dart")}
          >
            {copy.dart}
          </button>
          <button
            type="button"
            aria-pressed={market === "sec"}
            onClick={() => setMarket("sec")}
          >
            {copy.sec}
          </button>
        </div>
        <p>{copy.disclosure}</p>
      </div>
      {market === "dart" ? (
        <StructaraProofDemo locale={locale} />
      ) : (
        <StructaraSecProofDemo />
      )}
    </div>
  );
}
