import { ArrowRight, CheckCircle } from "@phosphor-icons/react/dist/ssr";
import Image from "next/image";
import type { Route } from "next";
import Link from "next/link";

import {
  FolyntaGlyph,
  type FolyntaGlyphName,
} from "@/components/folynta-glyph";
import { FolyntaDiagram } from "@/components/folynta-diagram";
import { FolyntaMarketingShell } from "@/components/folynta-marketing-shell";
import { FolyntaProofDemo } from "@/components/folynta-proof-demo";
import { FolyntaPricingPlanner } from "@/components/folynta-pricing-planner";
import type { FolyntaPage } from "@/lib/folynta-content";
import {
  ROUTE_DIAGRAMS,
  type FolyntaDiagramId,
} from "@/lib/folynta-diagrams";

const glyphs: FolyntaGlyphName[] = ["page", "block", "evidence", "node"];

const productEvidence: Record<
  string,
  { src: string; label: string; alt: string }
> = {
  "/product": {
    src: "/product/workspace-home.webp",
    label: "Actual product · deterministic demo workspace",
    alt: "FOLYNTA workspace with active jobs, review items, knowledge notes, and source coverage.",
  },
  "/product/convert": {
    src: "/product/processing.webp",
    label: "Actual product · processing workspace",
    alt: "FOLYNTA processing workspace linking source pages to structured output.",
  },
  "/product/verify": {
    src: "/product/review.webp",
    label: "Actual product · review workspace",
    alt: "FOLYNTA review workspace showing source-linked numeric and table review.",
  },
  "/product/knowledge": {
    src: "/product/knowledge.webp",
    label: "Actual product · knowledge workspace",
    alt: "FOLYNTA knowledge workspace with notes, entities, and source coverage.",
  },
  "/product/graph": {
    src: "/product/graph.webp",
    label: "Actual product · local graph workspace",
    alt: "FOLYNTA local knowledge graph with a restrained evidence-focused layout.",
  },
  "/product/connect": {
    src: "/product/exports.webp",
    label: "Actual product · export center",
    alt: "FOLYNTA export center with portable knowledge packages and verified status.",
  },
};

export function FolyntaMarketingPage({
  definition,
}: {
  definition: FolyntaPage;
}) {
  return (
    <FolyntaMarketingShell>
      <main id="main-content" className="fl-page">
        <section className="fl-page-hero">
          <div className="fl-page-hero-copy">
            <p className="fl-context-label">{definition.label}</p>
            <h1>{definition.title}</h1>
            <p>{definition.intro}</p>
            <div className="fl-actions">
              <Link
                href={definition.primaryAction.href as Route}
                className="fl-button fl-button-dark"
              >
                {definition.primaryAction.label}
                <ArrowRight size={16} aria-hidden="true" />
              </Link>
              {definition.secondaryAction && (
                <Link
                  href={definition.secondaryAction.href as Route}
                  className="fl-text-action"
                >
                  {definition.secondaryAction.label}
                </Link>
              )}
            </div>
          </div>
          {productEvidence[definition.path] ? (
            <ProductEvidence
              evidence={productEvidence[definition.path]!}
              path={definition.path}
            />
          ) : (
            <PageThesis definition={definition} />
          )}
        </section>

        <section className="fl-thesis">
          <p>{definition.thesis}</p>
          <span>Source-linked by design</span>
        </section>

        {definition.path === "/demo/dart" && (
          <section className="fl-route-proof">
            <div className="fl-route-proof-heading">
              <p className="fl-context-label">Public filing proof surface</p>
              <h2>One number, every transformation, the original evidence.</h2>
              <p>
                The values below come from an acquired OpenDART filing. They are
                a public-source product fixture, not benchmark labels or a
                quality claim.
              </p>
            </div>
            <FolyntaProofDemo />
          </section>
        )}

        {definition.path === "/pricing" && <FolyntaPricingPlanner />}

        {ROUTE_DIAGRAMS[definition.path] && (
          <FolyntaDiagram
            id={ROUTE_DIAGRAMS[definition.path] as FolyntaDiagramId}
          />
        )}

        <section className="fl-page-sections">
          {definition.sections.map((section, index) => {
            const glyph = glyphs[index % glyphs.length]!;
            return (
              <article key={section.title}>
                <div className="fl-section-index">
                  <FolyntaGlyph name={glyph} size={18} />
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

        <section className="fl-route-cta">
          <div>
            <p>Page → Structure → Evidence → Knowledge → Intelligence</p>
            <h2>Build knowledge that can always show its work.</h2>
          </div>
          <Link href="/signup" className="fl-button fl-button-light">
            Start with your documents
          </Link>
        </section>
      </main>
    </FolyntaMarketingShell>
  );
}

function ProductEvidence({
  evidence,
  path,
}: {
  evidence: (typeof productEvidence)[string];
  path: string;
}) {
  return (
    <figure className="fl-page-product-evidence">
      <div>
        <Image
          src={evidence.src}
          alt={evidence.alt}
          width={1440}
          height={900}
          sizes="(max-width: 960px) 92vw, 52vw"
          priority={path === "/product"}
        />
      </div>
      <figcaption>
        <span>{evidence.label}</span>
        <strong>Public Filing Knowledge Demo</strong>
      </figcaption>
    </figure>
  );
}

function PageThesis({ definition }: { definition: FolyntaPage }) {
  if (definition.family === "solution") {
    return (
      <div
        className="fl-route-visual fl-route-visual-journey"
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
        className="fl-route-visual fl-route-visual-code"
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
        className="fl-route-visual fl-route-visual-ledger"
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
        className="fl-route-visual fl-route-visual-index"
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
      className="fl-route-visual fl-route-visual-demo"
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
