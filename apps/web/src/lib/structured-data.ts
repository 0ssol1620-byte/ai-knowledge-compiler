import type { TavonelPage } from "@/lib/tavonel-content";

/**
 * schema.org payloads — DESIGN_MASTER_V3 §19.
 *
 * Truthfulness carries over from the rest of the site: nothing here asserts a
 * rating, a price, a customer count, or a benchmark number, because none of
 * those are measured. The graph describes what the pages are, not how well
 * they perform.
 */

const ORGANIZATION_ID = "#organization";
const SITE_ID = "#website";

/** Same source of truth as `metadataBase` in the root layout. */
export const SITE_BASE =
  process.env.NEXT_PUBLIC_SITE_URL ?? "http://127.0.0.1:3000";

export type JsonLdNode = Record<string, unknown>;

function absolute(base: string, path: string) {
  return new URL(path, base).toString();
}

/** Emitted once, from the root layout. Every page node references it. */
export function organizationGraph(base: string): JsonLdNode[] {
  return [
    {
      "@type": "Organization",
      "@id": absolute(base, "/") + ORGANIZATION_ID.slice(1),
      name: "TAVONEL",
      url: base,
      description:
        "The Knowledge Compiler. A traceable path from every source to knowledge — documents become structured, verified knowledge that people and AI can reuse.",
      slogan: "A traceable path from every source to knowledge.",
    },
    {
      "@type": "WebSite",
      "@id": absolute(base, "/") + SITE_ID.slice(1),
      url: base,
      name: "TAVONEL",
      inLanguage: "en",
      publisher: { "@id": absolute(base, "/") + ORGANIZATION_ID.slice(1) },
    },
  ];
}

/**
 * §19 maps families to types:
 *   SoftwareApplication  product routes
 *   Dataset              benchmarks and the public filing fixtures
 *   TechArticle          research and developer documentation
 *   FAQPage              only where the route actually asks and answers
 */
export function pageGraph(page: TavonelPage, base: string): JsonLdNode[] {
  const url = absolute(base, page.path);
  const publisher = { "@id": absolute(base, "/") + ORGANIZATION_ID.slice(1) };

  const common = {
    "@id": `${url}#page`,
    url,
    name: page.title,
    description: page.intro,
    inLanguage: "en",
    isPartOf: { "@id": absolute(base, "/") + SITE_ID.slice(1) },
    publisher,
  };

  switch (page.family) {
    case "product":
      return [
        {
          ...common,
          "@type": "SoftwareApplication",
          applicationCategory: "BusinessApplication",
          operatingSystem: "Web",
          // No offers block: pricing is a plan estimator, not a fixed price,
          // and an invented price is exactly the kind of claim §19 forbids.
        },
      ];

    case "proof":
      // /benchmarks publishes measured runs; /security and /pricing do not.
      if (page.path !== "/benchmarks") {
        return [{ ...common, "@type": "WebPage" }];
      }
      return [
        {
          ...common,
          "@type": "Dataset",
          creator: publisher,
          license: "https://spdx.org/licenses/Apache-2.0.html",
          measurementTechnique:
            "Deterministic replay of frozen source documents against the published extraction pipeline.",
        },
      ];

    case "demo":
      return [
        {
          ...common,
          "@type": "Dataset",
          creator: publisher,
          description: `${page.intro} Source documents are public filings and papers held as frozen fixtures.`,
        },
      ];

    case "editorial":
    case "docs":
      return [
        {
          ...common,
          "@type": "TechArticle",
          headline: page.title,
          author: publisher,
        },
      ];

    case "solution":
    case "legal":
    default:
      return [{ ...common, "@type": "WebPage" }];
  }
}

/**
 * Only call this where the route genuinely renders questions and answers.
 * A FAQPage node on a route without them is a fabricated claim about the page.
 */
export function faqGraph(
  entries: ReadonlyArray<{ question: string; answer: string }>,
  url: string,
): JsonLdNode[] {
  if (entries.length === 0) return [];
  return [
    {
      "@type": "FAQPage",
      "@id": `${url}#faq`,
      mainEntity: entries.map((entry) => ({
        "@type": "Question",
        name: entry.question,
        acceptedAnswer: { "@type": "Answer", text: entry.answer },
      })),
    },
  ];
}

export function jsonLdDocument(nodes: JsonLdNode[]) {
  return JSON.stringify({ "@context": "https://schema.org", "@graph": nodes });
}
