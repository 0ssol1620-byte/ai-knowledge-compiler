import { ArrowRight, CheckCircle } from "@phosphor-icons/react/dist/ssr";
import Image from "next/image";
import type { Route } from "next";
import Link from "next/link";

import {
  StructaraGlyph,
  type StructaraGlyphName,
} from "@/components/structara-glyph";
import { StructaraDiagram } from "@/components/structara-diagram";
import { StructaraMarketingShell } from "@/components/structara-marketing-shell";
import { StructaraLegalRegister } from "@/components/structara-legal-register";
import { StructaraProofDemo } from "@/components/structara-proof-demo";
import { StructaraPricingPlanner } from "@/components/structara-pricing-planner";
import { StructaraSecProofDemo } from "@/components/structara-sec-proof-demo";
import { StructaraSecurityArchitecture } from "@/components/structara-security-architecture";
import type { StructaraPage } from "@/lib/structara-content";
import {
  ROUTE_DIAGRAMS,
  type StructaraDiagramId,
} from "@/lib/structara-diagrams";

const glyphs: StructaraGlyphName[] = ["page", "block", "evidence", "node"];

const productEvidence: Record<
  string,
  { src: string; label: string; alt: string }
> = {
  "/product": {
    src: "/product/workspace-home.webp",
    label: "Actual product · deterministic demo workspace",
    alt: "Structara workspace with active jobs, review items, knowledge notes, and source coverage.",
  },
  "/product/convert": {
    src: "/product/processing.webp",
    label: "Actual product · processing workspace",
    alt: "Structara processing workspace linking source pages to structured output.",
  },
  "/product/verify": {
    src: "/product/review.webp",
    label: "Actual product · review workspace",
    alt: "Structara review workspace showing source-linked numeric and table review.",
  },
  "/product/knowledge": {
    src: "/product/knowledge.webp",
    label: "Actual product · knowledge workspace",
    alt: "Structara knowledge workspace with notes, entities, and source coverage.",
  },
  "/product/graph": {
    src: "/product/graph.webp",
    label: "Actual product · local graph workspace",
    alt: "Structara local knowledge graph with a restrained evidence-focused layout.",
  },
  "/product/connect": {
    src: "/product/exports.webp",
    label: "Actual product · export center",
    alt: "Structara export center with portable knowledge packages and verified status.",
  },
};

export function StructaraMarketingPage({
  definition,
}: {
  definition: StructaraPage;
}) {
  return (
    <StructaraMarketingShell>
      <main id="main-content" className="st-page">
        <section className="st-page-hero">
          <div className="st-page-hero-copy">
            <p className="st-context-label">{definition.label}</p>
            <h1>{definition.title}</h1>
            <p>{definition.intro}</p>
            <div className="st-actions">
              <Link
                href={definition.primaryAction.href as Route}
                className="st-button st-button-dark"
              >
                {definition.primaryAction.label}
                <ArrowRight size={16} aria-hidden="true" />
              </Link>
              {definition.secondaryAction && (
                <Link
                  href={definition.secondaryAction.href as Route}
                  className="st-text-action"
                >
                  {definition.secondaryAction.label}
                </Link>
              )}
            </div>
          </div>
          {productEvidence[definition.path] ? (
            <ProductEvidence evidence={productEvidence[definition.path]!} />
          ) : (
            <PageThesis definition={definition} />
          )}
        </section>

        <section className="st-thesis">
          <p>{definition.thesis}</p>
          <span>Source-linked by design</span>
        </section>

        {definition.path === "/demo/dart" && (
          <section className="st-route-proof">
            <div className="st-route-proof-heading">
              <p className="st-context-label">Public filing proof surface</p>
              <h2>One number, every transformation, the original evidence.</h2>
              <p>
                The values below come from an acquired OpenDART filing. They are
                a public-source product fixture, not benchmark labels or a
                quality claim.
              </p>
            </div>
            <StructaraProofDemo />
          </section>
        )}

        {definition.path === "/demo/sec" && (
          <section className="st-route-proof st-route-proof-sec">
            <StructaraSecProofDemo />
          </section>
        )}

        {definition.path === "/security" && <StructaraSecurityArchitecture />}

        {definition.path === "/pricing" && <StructaraPricingPlanner />}

        {definition.family === "legal" && (
          <StructaraLegalRegister path={definition.path} />
        )}

        {ROUTE_DIAGRAMS[definition.path] && definition.path !== "/security" && (
          <StructaraDiagram
            id={ROUTE_DIAGRAMS[definition.path] as StructaraDiagramId}
          />
        )}

        <section className="st-page-sections">
          {definition.sections.map((section, index) => {
            const glyph = glyphs[index % glyphs.length]!;
            return (
              <article key={section.title}>
                <div className="st-section-index">
                  <StructaraGlyph name={glyph} size={18} />
                  <span>{String(index + 1).padStart(2, "0")}</span>
                </div>
                <div>
                  <h2>{section.title}</h2>
                  <p>{section.body}</p>
                  {section.items && (
                    <ul>
                      {section.items.map((item) => (
                        <li key={item}>
                          <CheckCircle size={15} aria-hidden="true" />
                          {item}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </article>
            );
          })}
        </section>

        <section className="st-route-cta">
          <div>
            <p>Page → Structure → Evidence → Knowledge → Intelligence</p>
            <h2>Build knowledge that can always show its work.</h2>
          </div>
          <Link href="/signup" className="st-button st-button-light">
            Start with your documents
          </Link>
        </section>
      </main>
    </StructaraMarketingShell>
  );
}

function ProductEvidence({
  evidence,
}: {
  evidence: (typeof productEvidence)[string];
}) {
  return (
    <figure className="st-page-product-evidence">
      <div>
        <Image
          src={evidence.src}
          alt={evidence.alt}
          width={1440}
          height={900}
          sizes="(max-width: 960px) 92vw, 52vw"
          priority
        />
      </div>
      <figcaption>
        <span>{evidence.label}</span>
        <strong>Public Filing Knowledge Demo</strong>
      </figcaption>
    </figure>
  );
}

function PageThesis({ definition }: { definition: StructaraPage }) {
  if (definition.family === "solution") {
    return (
      <div
        className="st-route-visual st-route-visual-journey"
        aria-label={`${definition.label} knowledge journey`}
      >
        <p>{definition.label} operating path</p>
        <ol>
          {definition.sections.slice(0, 3).map((section, index) => (
            <li key={section.title}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{section.title}</strong>
              <i />
            </li>
          ))}
        </ol>
        <small>Source → verified knowledge → controlled activation</small>
      </div>
    );
  }

  if (definition.family === "docs") {
    return (
      <div
        className="st-route-visual st-route-visual-code"
        aria-label={`${definition.label} developer interface`}
      >
        <header>
          <span>POST</span>
          <code>/v1/compile</code>
          <i>202</i>
        </header>
        <pre>{`{
  "source": "public-filing.pdf",
  "mode": "balanced",
  "proof": true
}`}</pre>
        <footer>
          <span>event: block.verified</span>
          <strong>source_ref attached</strong>
        </footer>
      </div>
    );
  }

  if (definition.family === "proof") {
    const pricing = definition.path === "/pricing";
    return (
      <div
        className="st-route-visual st-route-visual-ledger"
        aria-label={`${definition.label} control ledger`}
      >
        <p>{pricing ? "Plan controls" : "Policy controls"}</p>
        {(pricing
          ? [
              ["Documents", "Included"],
              ["Knowledge graph", "Portable"],
              ["Hard cap", "Owner set"],
            ]
          : [
              ["External transfer", "Blocked"],
              ["Retention", "Policy set"],
              ["Audit event", "Required"],
            ]
        ).map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
        <small>No hidden policy · no unregistered claim</small>
      </div>
    );
  }

  if (definition.family === "editorial" || definition.family === "legal") {
    return (
      <div
        className="st-route-visual st-route-visual-index"
        aria-label={`${definition.label} editorial index`}
      >
        <p>
          {definition.family === "legal" ? "Document index" : "Field notes"}
        </p>
        {definition.sections.slice(0, 4).map((section, index) => (
          <div key={section.title}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{section.title}</strong>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div
      className="st-route-visual st-route-visual-demo"
      aria-label={`${definition.label} evidence workflow`}
    >
      <div>
        <span>Original</span>
        <i />
        <i />
        <b />
      </div>
      <em />
      <div>
        <span>Markdown</span>
        <strong>Graph</strong>
        <i />
      </div>
      <small>Public sample · evidence preserved</small>
    </div>
  );
}
