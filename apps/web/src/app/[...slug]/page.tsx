import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { TavonelMarketingPage } from "@/components/tavonel-marketing-page";
import { JsonLd } from "@/components/json-ld";
import { getRequestLocale } from "@/lib/locale-server";
import { getPublicPage } from "@/lib/structara-content-localized";
import { pageGraph, SITE_BASE } from "@/lib/structured-data";

type Props = { params: Promise<{ slug: string[] }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const [{ slug }, locale] = await Promise.all([params, getRequestLocale()]);
  const definition = getPublicPage(`/${slug.join("/")}`, locale);
  if (!definition) return {};
  const hiddenProofRoute = new Set(["/customers", "/research/experiments"]).has(definition.path);
  return {
    title: definition.title,
    description: definition.intro,
    alternates: { canonical: definition.path },
    openGraph: {
      title: definition.title,
      description: definition.intro,
      url: definition.path,
    },
    robots: hiddenProofRoute ? { index: false, follow: false } : undefined,
  };
}

export default async function TavonelPublicRoute({ params }: Props) {
  const [{ slug }, locale] = await Promise.all([params, getRequestLocale()]);
  const definition = getPublicPage(`/${slug.join("/")}`, locale);
  if (!definition) notFound();
  if (new Set(["/customers", "/research/experiments"]).has(definition.path)) notFound();
  return (
    <>
      <JsonLd nodes={pageGraph(definition, SITE_BASE)} />
      <TavonelMarketingPage definition={definition} />
    </>
  );
}
