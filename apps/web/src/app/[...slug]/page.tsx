import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { LocaleProvider } from "@/components/locale-provider";
import { TavonelMarketingPage } from "@/components/tavonel-marketing-page";
import { JsonLd } from "@/components/json-ld";
import { getPublicRequestLocale } from "@/lib/locale-server";
import type { StructaraLocale } from "@/lib/locale";
import { PUBLIC_PAGES_KO } from "@/lib/structara-content-ko";
import { PUBLIC_PAGES } from "@/lib/tavonel-content";
import { pageGraph, SITE_BASE } from "@/lib/structured-data";

type Props = { params: Promise<{ slug: string[] }> };

// Legal pages stay English: their Korean wording is founder-only.
async function resolvePage(slug: string[]) {
  const path = `/${slug.join("/")}`;
  const locale: StructaraLocale = path.startsWith("/legal/")
    ? "en"
    : await getPublicRequestLocale();
  const pages = locale === "ko" ? PUBLIC_PAGES_KO : PUBLIC_PAGES;
  return { locale, definition: pages[path] };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const { definition } = await resolvePage(slug);
  if (!definition) return {};
  return {
    title: definition.title,
    description: definition.intro,
    alternates: { canonical: definition.path },
    openGraph: {
      title: definition.title,
      description: definition.intro,
      url: definition.path,
    },
  };
}

export default async function TavonelPublicRoute({ params }: Props) {
  const { slug } = await params;
  const { locale, definition } = await resolvePage(slug);
  if (!definition) notFound();
  return (
    <LocaleProvider locale={locale}>
      <JsonLd nodes={pageGraph(definition, SITE_BASE)} />
      <TavonelMarketingPage definition={definition} locale={locale} />
    </LocaleProvider>
  );
}
