import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { HeroComp, HERO_COPY, type HeroVariant } from "@/components/facing/hero-comp";

/**
 * W1 comp gallery — DESIGN_MASTER_V3 §12.2, §25.1.
 *
 * Renders one hero variant at a time so the three can be captured under
 * identical conditions and ranked. Not a product route: it is excluded from
 * the sitemap and marked noindex, and it disappears once decision.md records
 * the choice.
 *
 *   /design/hero?variant=frame&copy=d1
 *
 * variant: frame | overlap | fullbleed   (§12.2 A / B / C)
 * copy:    d1 | d2 | d3                  (§3.3 three directions)
 */

export const metadata: Metadata = {
  title: "W1 hero comps",
  robots: { index: false, follow: false },
};

const VARIANTS: readonly HeroVariant[] = ["frame", "overlap", "fullbleed"];

type Props = {
  searchParams: Promise<{ variant?: string; copy?: string }>;
};

export default async function HeroCompPage({ searchParams }: Props) {
  const params = await searchParams;
  const variant = (params.variant ?? "frame") as HeroVariant;
  const copyId = (params.copy ?? "d1") as keyof typeof HERO_COPY;

  if (!VARIANTS.includes(variant) || !(copyId in HERO_COPY)) notFound();

  return (
    <main id="main-content">
      <HeroComp variant={variant} copy={HERO_COPY[copyId]} />
    </main>
  );
}
