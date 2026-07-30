import {
  ArrowRight,
  CheckCircle,
  FileText,
  Graph,
  LinkSimple,
  SquaresFour,
} from "@phosphor-icons/react/dist/ssr";
import type { Route } from "next";
import Link from "next/link";

import { StructaraMarketingShell } from "@/components/structara-marketing-shell";
import type { StructaraPage } from "@/lib/structara-content";

const glyphs = [FileText, SquaresFour, LinkSimple, Graph] as const;

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
          <PageThesis definition={definition} />
        </section>

        <section className="st-thesis">
          <p>{definition.thesis}</p>
          <span>Source-linked by design</span>
        </section>

        <section className="st-page-sections">
          {definition.sections.map((section, index) => {
            const Icon = glyphs[index % glyphs.length]!;
            return (
              <article key={section.title}>
                <div className="st-section-index">
                  <Icon size={18} aria-hidden="true" />
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

function PageThesis({ definition }: { definition: StructaraPage }) {
  const labels =
    definition.family === "demo"
      ? ["Original", "Markdown", "Graph"]
      : definition.family === "docs"
        ? ["Request", "Events", "Package"]
        : ["Source", "Structure", "Knowledge"];

  return (
    <div className="st-page-visual" aria-label={`${definition.label} workflow`}>
      <div className="st-page-sheet">
        <span>{labels[0]}</span>
        <i />
        <i />
        <b />
      </div>
      <div className="st-evidence-line" />
      <div className="st-page-output">
        <span>{labels[1]}</span>
        <strong>{labels[2]}</strong>
        <div>
          <i />
          <i />
          <i />
        </div>
      </div>
      <small>Public sample · evidence preserved</small>
    </div>
  );
}
