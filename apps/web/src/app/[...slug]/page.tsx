import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { FolyntaMarketingPage } from "@/components/folynta-marketing-page";
import { PUBLIC_PAGES } from "@/lib/folynta-content";

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

export default async function FolyntaPublicRoute({ params }: Props) {
  const { slug } = await params;
  const definition = PUBLIC_PAGES[`/${slug.join("/")}`];
  if (!definition) notFound();
  return <FolyntaMarketingPage definition={definition} />;
}
