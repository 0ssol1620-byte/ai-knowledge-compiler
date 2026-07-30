import {
  ArrowRight,
  CheckCircle,
  FileText,
  Graph,
  LinkSimple,
  LockKey,
  ShieldCheck,
  SquaresFour,
} from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

import { StructaraHeroScene } from "@/components/structara-hero";
import { StructaraMarketingShell } from "@/components/structara-marketing-shell";
import { StructaraProofDemo } from "@/components/structara-proof-demo";

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
    <StructaraMarketingShell>
      <main id="main-content" className="st-home">
        <section className="st-home-hero">
          <div className="st-home-copy">
            <p className="st-context-label">The Knowledge Compiler for AI</p>
            <h1>Your AI is only as good as the knowledge it receives.</h1>
            <p className="st-home-intro">
              Turn documents into structured, verified, connected knowledge with
              every important result linked back to its source.
            </p>
            <div className="st-actions">
              <Link href="/signup" className="st-button st-button-dark">
                Build your knowledge
                <ArrowRight size={16} aria-hidden="true" />
              </Link>
              <a href="#transformation" className="st-text-action">
                Watch the transformation
              </a>
            </div>
            <p className="st-trust-line">
              Source-linked · Portable · Private by policy
            </p>
            <p className="st-compiler-sequence">
              Page → Structure → Evidence → Knowledge → Intelligence
            </p>
          </div>
          <StructaraHeroScene />
          <div className="st-output-rail" aria-label="Supported outputs">
            {[
              "Portable Markdown",
              "Obsidian Vault",
              "RAG JSONL",
              "Knowledge Graph",
            ].map((output) => (
              <span key={output}>{output}</span>
            ))}
          </div>
        </section>

        <section className="st-problem">
          <div>
            <h2>
              Powerful models.
              <br />
              Weak context.
            </h2>
            <p>
              Complex layouts, broken tables, repeated headers, page boundaries,
              and summaries without sources leave AI with text but not usable
              knowledge.
            </p>
          </div>
          <div className="st-before-after">
            <article>
              <span>Raw documents</span>
              <div className="st-fragments">
                <i />
                <i />
                <i />
                <i />
              </div>
              <p>Fragments · repeated headers · broken table · no links</p>
            </article>
            <div className="st-compile-path" aria-hidden="true">
              <FileText size={16} />
              <span />
              <SquaresFour size={16} />
              <span />
              <LinkSimple size={16} />
              <span />
              <Graph size={16} />
            </div>
            <article>
              <span>Compiled knowledge</span>
              <div className="st-compiled">
                <strong>Heading tree</strong>
                <i>Table object</i>
                <i>Source link</i>
                <i>Note network</i>
              </div>
              <p>Structure · evidence · relationships · portable output</p>
            </article>
          </div>
        </section>

        <section id="transformation" className="st-transformation">
          <header>
            <p>The compiler path</p>
            <h2>From pages to intelligence, without losing the proof.</h2>
          </header>
          <div className="st-chapters">
            {chapters.map((chapter) => (
              <article key={chapter.number}>
                <div className="st-chapter-copy">
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

        <section className="st-demo-section">
          <div className="st-section-intro">
            <p>Public filing demo</p>
            <h2>Do not take our word for it. Inspect the result.</h2>
            <span>
              The same DART sample connects the original page, Markdown,
              knowledge package, graph, and proof panel.
            </span>
          </div>
          <StructaraProofDemo />
          <div className="st-inline-actions">
            <Link href="/demo/dart">Open full DART demo</Link>
            <Link href="/signup">Try it with your document</Link>
          </div>
        </section>

        <section className="st-pillars">
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

        <section className="st-public-proof">
          <div className="st-section-intro">
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

        <section className="st-benchmark">
          <div>
            <p>Benchmark discipline</p>
            <h2>Accuracy should be demonstrated, not declared.</h2>
            <span>
              Dataset, sample count, route version, evaluator, and date travel
              with every result. Unmeasured values remain unavailable.
            </span>
          </div>
          <div className="st-metric-table">
            <div>
              <span>Metric</span>
              <span>Public status</span>
              <span>Evidence</span>
            </div>
            {[
              ["Text fidelity", "Not measured", "Dataset required"],
              ["Numeric preservation", "Not measured", "Ground truth required"],
              ["Table structure", "Not measured", "Comparator required"],
              ["Source coverage", "Verified locally", "Live source-link E2E"],
            ].map((row) => (
              <div key={row[0]}>
                {row.map((cell) => (
                  <span key={cell}>{cell}</span>
                ))}
              </div>
            ))}
          </div>
          <Link href="/benchmarks" className="st-text-action">
            Explore benchmark methodology
          </Link>
        </section>

        <section className="st-use-cases">
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

        <section className="st-security-band">
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
          <div className="st-policy-orbit">
            <strong>Document</strong>
            {["Region", "Retention", "Access", "Audit", "External AI"].map(
              (item) => (
                <span key={item}>{item}</span>
              ),
            )}
          </div>
        </section>

        <section className="st-manifesto">
          <ShieldCheck size={24} aria-hidden="true" />
          <p>AI does not need more information. It needs better knowledge.</p>
          <div>
            <span>Knowledge has structure.</span>
            <span>Knowledge has context.</span>
            <span>Knowledge has relationships.</span>
            <span>Knowledge has evidence.</span>
          </div>
          <h2>Structara compiles all four.</h2>
        </section>

        <section className="st-home-final">
          <p>Your documents already contain what your AI needs.</p>
          <h2>Make it usable.</h2>
          <div className="st-actions">
            <Link href="/signup" className="st-button st-button-dark">
              Build your knowledge <ArrowRight size={16} />
            </Link>
            <Link href="/company/contact" className="st-text-action">
              Talk to sales
            </Link>
          </div>
          <small>
            <CheckCircle size={14} /> Source-linked · Portable · Policy
            controlled
          </small>
        </section>
      </main>
    </StructaraMarketingShell>
  );
}

function ChapterVisual({ index }: { index: string }) {
  return (
    <div className={`st-chapter-visual st-chapter-${index}`} aria-hidden="true">
      <div className="st-visual-page">
        <i />
        <i />
        <i />
        <b />
      </div>
      <div className="st-visual-result">
        <strong>
          {index === "02"
            ? "12,345,678"
            : index === "04"
              ? "Export"
              : "Knowledge"}
        </strong>
        <span />
        <span />
      </div>
      <div className="st-visual-link" />
    </div>
  );
}
