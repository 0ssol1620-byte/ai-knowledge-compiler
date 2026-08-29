import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { TavonelMarketingPage } from "@/components/tavonel-marketing-page";
import { JsonLd } from "@/components/json-ld";
import { getRequestLocale } from "@/lib/locale-server";
import { PUBLIC_PAGES_KO } from "@/lib/structara-content-ko";
import { PUBLIC_PAGES } from "@/lib/tavonel-content";
import { pageGraph, SITE_BASE } from "@/lib/structured-data";

type Props = { params: Promise<{ slug: string[] }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const locale = await getRequestLocale();
  const pages = locale === "ko" ? PUBLIC_PAGES_KO : PUBLIC_PAGES;
  const definition = pages[`/${slug.join("/")}`];
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
  const locale = await getRequestLocale();
  const pages = locale === "ko" ? PUBLIC_PAGES_KO : PUBLIC_PAGES;
  const definition = pages[`/${slug.join("/")}`];
  if (!definition) notFound();
  return (
    <>
      <JsonLd nodes={pageGraph(definition, SITE_BASE)} />
      <TavonelMarketingPage definition={definition} locale={locale} />
    </>
  );
}
