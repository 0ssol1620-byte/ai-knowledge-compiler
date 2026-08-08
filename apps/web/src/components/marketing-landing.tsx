import { ArrowRight, CheckCircle, LockKey } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

import { AccuracySection } from "@/components/accuracy-section";
import { TrialRunFilm } from "@/components/trial-run-film";
import { HeroComp, HERO_COPY } from "@/components/facing/hero-comp";
import { TavonelGlyph } from "@/components/tavonel-glyph";
import { TavonelMarketingShell } from "@/components/tavonel-marketing-shell";
import { TavonelProofDemo } from "@/components/tavonel-proof-demo";
import { DART_PUBLIC_FIXTURE } from "@/lib/dart-public-fixture";

const chapters = [
  {
    number: "01",
    title: "It sees more than text.",
    body: "Headings, paragraphs, tables, formulas, figures, footnotes, and reading order become one inspectable document structure.",
    signal: "Page → typed blocks",
  },
  {
    number: "02",
    title: "Every output returns to its source.",
    body: "Select a sentence, number, or table cell and return to the exact page region that produced it.",
    signal: "Result → page · block · bbox",
  },
  {
    number: "03",
    title: "Documents become a knowledge system.",
    body: "Sections become notes. Notes surface entities. Evidence-backed relations connect documents that previously stood alone.",
    signal: "Blocks → notes · entities · relations",
  },
  {
    number: "04",
    title: "Compile once. Use it everywhere.",
    body: "Portable Markdown, Obsidian, RAG JSONL, JSON-LD, and project packs derive from the same verified source map.",
    signal: "One core → many destinations",
  },
] as const;

export function MarketingLanding() {
  return (
    <TavonelMarketingShell>
      <main id="main-content" className="tv-home">
        {/*
          §9.2 option A, decided at G-C: the hero is an affordance, not a
          scene. The visitor is not shown a picture of compiling — the left
          page is a real document with its blocks at stored bbox coordinates,
          and dropping a file replaces it with theirs.

          What this replaced, and why. The previous hero paired the copy with
          an abstract render that had to caption itself "no generated imagery"
          — a hero image that has to deny being AI slop has already lost the
          argument. Below it, a "Powerful models / Weak context" section
          illustrated raw documents with four empty white rectangles and
          compiled knowledge with four labelled empty cells. On a document
          product, an empty box does not read as a fragmented document; it
          reads as a failed image load. §21 [확정] requires marketing visuals
          to be generated from real product components, and those were
          hand-drawn empty divs.

          The section is not replaced by a better diagram. It is deleted,
          because the hero now makes its point by doing the thing.
        */}
        <HeroComp variant="frame" copy={HERO_COPY.d1} live />

        <div className="tv-output-rail" aria-label="Supported outputs">
          {["Portable Markdown", "Obsidian Vault", "RAG JSONL", "Knowledge Graph"].map(
            (output) => (
              <span key={output}>{output}</span>
            ),
          )}
        </div>

        <TrialRunFilm />

        <section className="tv-demo-section">
          <div className="tv-section-intro">
            <p>Public filing demo</p>
            <h2>Do not take our word for it. Inspect the result.</h2>
            <span>
              The same DART sample connects the original page, Markdown,
              knowledge package, graph, and proof panel.
            </span>
          </div>
          <TavonelProofDemo />
          <div className="tv-inline-actions">
            <Link href="/demo/dart">Open full DART demo</Link>
            <Link href="/signup">Try it with your document</Link>
          </div>
        </section>

        <AccuracySection />

        <section id="transformation" className="tv-transformation">
          <header>
            <p>The compiler path</p>
            <h2>From pages to intelligence, without losing the proof.</h2>
          </header>
          <div className="tv-chapters">
            {chapters.map((chapter) => (
              <article key={chapter.number}>
                <div className="tv-chapter-copy">
                  <span>{chapter.number}</span>
                  <h3>{chapter.title}</h3>
                  <p>{chapter.body}</p>
                  <small>{chapter.signal}</small>
                </div>
                <ChapterVisual index={chapter.number} />
              </article>
            ))}
          </div>
        </section>


        <section className="tv-pillars">
          <header>
            <h2>
              Knowledge has structure, evidence, connection, and a way out.
            </h2>
          </header>
          {[
            [
              "Structure",
              "Preserve hierarchy, not just characters.",
              "Heading tree + reading order",
            ],
            [
              "Evidence",
              "Trace every result back to the page.",
              "Page · block · bounding box",
            ],
            [
              "Connection",
              "Turn isolated files into a knowledge network.",
              "Notes · entities · relations",
            ],
            [
              "Portability",
              "Your knowledge should not belong to one tool.",
              "Markdown · Vault · RAG · JSON-LD",
            ],
          ].map(([title, copy, proof]) => (
            <article key={title}>
              <span>{title}</span>
              <h3>{copy}</h3>
              <p>{proof}</p>
            </article>
          ))}
        </section>

        <section className="tv-public-proof">
          <div className="tv-section-intro">
            <p>Public proof systems</p>
            <h2>Built for documents that cannot afford to be misunderstood.</h2>
          </div>
          <article>
            <span>KR · DART</span>
            <h3>Korean financial filings</h3>
            <p>
              Long-form Korean, XML/XBRL ground truth, complex tables, metrics,
              risks, segments, and corrected filing relationships.
            </p>
            <Link href="/demo/dart">Explore DART</Link>
          </article>
          <article>
            <span>US · SEC EDGAR</span>
            <h3>10-K, 10-Q, and 8-K</h3>
            <p>
              Inline XBRL, risk factors, exhibits, filing relationships, and
              source-linked entities in the same ontology.
            </p>
            <Link href="/demo/sec">Explore SEC</Link>
          </article>
        </section>


        <section className="tv-use-cases">
          <header>
            <h2>One compiler. Different knowledge systems.</h2>
          </header>
          {[
            [
              "Research",
              "Papers become methods, datasets, results, limitations, and citation-linked notes.",
            ],
            [
              "Personal knowledge",
              "Books, lectures, and notes become an Obsidian-ready concept system.",
            ],
            [
              "Enterprise",
              "Manuals, policies, and reports remain governed by access, retention, and audit.",
            ],
            [
              "AI and RAG",
              "Source-linked chunks and JSONL arrive ready for evaluation and retrieval.",
            ],
          ].map(([title, copy], index) => (
            <article key={title}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <h3>{title}</h3>
              <p>{copy}</p>
            </article>
          ))}
        </section>

        <section className="tv-security-band">
          <div>
            <LockKey size={22} aria-hidden="true" />
            <p>Private by default</p>
            <h2>Your knowledge stays yours.</h2>
            <span>
              Region, retention, access, audit, and external processing policy
              surround the document before a job begins.
            </span>
            <Link href="/security">Explore security architecture</Link>
          </div>
          <div className="tv-policy-orbit">
            <strong>Document</strong>
            {["Region", "Retention", "Access", "Audit", "External AI"].map(
              (item) => (
                <span key={item}>{item}</span>
              ),
            )}
          </div>
        </section>

        <section className="tv-manifesto">
          <TavonelGlyph name="verified" size={24} />
          <p>AI does not need more information. It needs better knowledge.</p>
          <div>
            <span>Knowledge has structure.</span>
            <span>Knowledge has context.</span>
            <span>Knowledge has relationships.</span>
            <span>Knowledge has evidence.</span>
          </div>
          <h2>TAVONEL compiles all four.</h2>
        </section>

        <section className="tv-home-final">
          <p>Your documents already contain what your AI needs.</p>
          <h2>Make it usable.</h2>
          <div className="tv-actions">
            <Link href="/signup" className="tv-button tv-button-dark">
              Build your knowledge <ArrowRight size={16} />
            </Link>
            <Link href="/company/contact" className="tv-text-action">
              Talk to sales
            </Link>
          </div>
          <small>
            <CheckCircle size={14} /> Source-linked · Portable · Policy
            controlled
          </small>
        </section>
      </main>
    </TavonelMarketingShell>
  );
}

/**
 * The four chapters, each showing the thing it claims — §21 [확정]: marketing
 * visuals come from real product data, not from drawings of it.
 *
 * This replaced one component that rendered all four chapters identically:
 * the same page of empty <i> bars, the same empty result box, the same
 * connector, with only a corner glyph and one label changing. Three different
 * claims illustrated by one picture is the clearest possible signal that
 * there was nothing specific to show.
 *
 * Everything below comes from DART_PUBLIC_FIXTURE, the same public filing the
 * proof explorer further down the page uses. Nothing here is invented: the
 * figures, taxonomy tags, and source line numbers are the ones in the filing.
 */
function ChapterVisual({ index }: { index: string }) {
  const fixture = DART_PUBLIC_FIXTURE;
  const revenue = fixture.rows[0]!;

  return (
    <div className={`tv-chapter-visual tv-chapter-${index}`}>
      <div className="tv-cv-source">
        <span className="tv-cv-stamp">
          {fixture.source} · {fixture.receiptNumber}
        </span>

        {index === "01" && (
          <ol className="tv-cv-blocks">
            <li data-block="heading">{fixture.statement}</li>
            <li data-block="paragraph">
              Consolidated figures for {fixture.currentPeriod}, presented in{" "}
              {fixture.unit}.
            </li>
            <li data-block="table">
              {fixture.rows.length} rows · {fixture.currentPeriod} vs{" "}
              {fixture.priorPeriod}
            </li>
          </ol>
        )}

        {index === "02" && (
          <table className="tv-cv-table">
            <tbody>
              {fixture.rows.slice(0, 3).map((row) => (
                <tr key={row.taxonomy} data-cited={row === revenue || undefined}>
                  <th scope="row">{row.label}</th>
                  <td>{row.current}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {index === "03" && (
          <ul className="tv-cv-entities">
            <li>
              {fixture.company} <em>issuer</em>
            </li>
            <li>
              {fixture.stockCode} <em>listing</em>
            </li>
            <li>
              {fixture.report} <em>filing</em>
            </li>
          </ul>
        )}

        {index === "04" && (
          <p className="tv-cv-digest">
            <span>archive sha256</span>
            {fixture.archiveSha256.slice(0, 24)}…
          </p>
        )}
      </div>

      <div className="tv-cv-thread" aria-hidden="true" />

      <div className="tv-cv-knowledge">
        {index === "01" && (
          <>
            <strong>3 typed blocks</strong>
            <p>heading · paragraph · table</p>
          </>
        )}
        {index === "02" && (
          <>
            <strong>{revenue.current}</strong>
            <p>
              {revenue.taxonomy}
              <br />
              source line {revenue.sourceLine}
            </p>
          </>
        )}
        {index === "03" && (
          <>
            <strong>3 entities</strong>
            <p>issuer → listing → filing</p>
          </>
        )}
        {index === "04" && (
          <>
            <strong>4 destinations</strong>
            <p>Markdown · Vault · RAG JSONL · JSON-LD</p>
          </>
        )}
      </div>
    </div>
  );
}
