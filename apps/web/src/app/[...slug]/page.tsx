import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { StructaraMarketingPage } from "@/components/structara-marketing-page";
import { PUBLIC_PAGES } from "@/lib/structara-content";

type Props = { params: Promise<{ slug: string[] }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const definition = PUBLIC_PAGES[`/${slug.join("/")}`];
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

export default async function StructaraPublicRoute({ params }: Props) {
  const { slug } = await params;
  const definition = PUBLIC_PAGES[`/${slug.join("/")}`];
  if (!definition) notFound();
  return <StructaraMarketingPage definition={definition} />;
}
