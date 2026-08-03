import {
  ActualSourceProof,
  FolyntaV4MarketingShell,
  IntakeCinematic,
  KnowledgeFormation,
  ProductFilmHero,
  RecoveryTheater,
} from "@/components/folynta-v4";
import type { StructaraLocale } from "@/lib/locale";

export function MarketingLanding({
  locale = "ko",
}: {
  locale?: StructaraLocale;
}) {
  return (
    <FolyntaV4MarketingShell locale={locale}>
      <main id="main-content" className="folynta-v4-home">
        <ProductFilmHero locale={locale} />
        <IntakeCinematic locale={locale} />
        <RecoveryTheater locale={locale} />
        <ActualSourceProof locale={locale} />
        <KnowledgeFormation locale={locale} />
      </main>
    </FolyntaV4MarketingShell>
  );
}
