import {
  ArrowRight,
  ChartScatter,
  Check,
  FileArrowDown,
  FileText,
  FlowArrow,
  Graph,
  LockKey,
  ShieldCheck,
  Stack,
} from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";

import { BrandMark } from "@/components/brand-mark";
import { SplineHero } from "@/components/spline-hero";
import {
  formatBenchmarkPercent,
  publicBenchmarkSnapshot,
} from "@/lib/benchmark-public";

const proofSteps = [
  {
    title: "Recover the structure",
    copy: "Headings, tables, figures, formulas, and reading order stay attached to their original page coordinates.",
    icon: FileText,
    signal: "Blocks · geometry · reading order",
  },
  {
    title: "Verify the result",
    copy: "Numeric values, table shape, and citation coverage are checked before uncertain output enters the review queue.",
    icon: ShieldCheck,
    signal: "Numbers · structure · provenance",
  },
  {
    title: "Compile the knowledge",
    copy: "Approved blocks become notes, entities, and relationships with an evidence chain for every derived claim.",
    icon: Graph,
    signal: "Notes · entities · relationships",
  },
  {
    title: "Export without lock-in",
    copy: "Portable Markdown, Obsidian Vault, RAG JSONL, and JSON-LD are generated from the same verified source map.",
    icon: FileArrowDown,
    signal: "Markdown · Vault · RAG · JSON-LD",
  },
] as const;

const benchmarkLabels: Record<string, string> = {
  "ko-dart": "Korean DART annual reports",
  "en-sec": "English SEC filings",
  "ko-scan": "Korean scanned documents",
  "lecture-deck": "Lecture slide decks",
};

export function MarketingLanding() {
  return (
    <div className="marketing-site">
      <header className="marketing-nav">
        <Link
          href="/"
          className="marketing-brand"
          aria-label="AI Knowledge Compiler"
        >
          <BrandMark />
        </Link>
        <nav aria-label="Primary navigation">
          <a href="#product">Product</a>
          <a href="#demo">Studio</a>
          <a href="#benchmark">Benchmarks</a>
          <a href="#security">Security</a>
          <a href="#pricing">Pricing</a>
          <Link href="/notices">Docs</Link>
          <Link href="/home">Dashboard</Link>
        </nav>
        <div>
          <Link href="/login" className="marketing-signin">
            Sign in
          </Link>
          <Link href="/home" className="primary-button marketing-cta">
            Start compiling
          </Link>
        </div>
      </header>

      <main id="main-content">
        <section className="marketing-hero">
          <div className="hero-copy">
            <h1>
              Compile the evidence.
              <br />
              Keep the source.
            </h1>
            <p>
              Turn PDFs, reports, papers, and slide decks into production-ready
              knowledge with every block linked back to its page and
              coordinates.
            </p>
            <div className="hero-actions">
              <Link href="/home" className="primary-button hero-primary">
                Start with a document
                <ArrowRight size={17} aria-hidden="true" />
              </Link>
              <a href="#demo" className="secondary-button hero-secondary">
                See the evidence loop
              </a>
            </div>
            <div className="hero-trust" aria-label="Product guarantees">
              {[
                "Source-linked output",
                "Inspectable processing",
                "Private by default",
                "Configurable retention",
              ].map((item) => (
                <span key={item}>
                  <Check size={13} weight="bold" aria-hidden="true" />
                  {item}
                </span>
              ))}
            </div>
          </div>

          <SplineHero />
        </section>

        <section className="product-truth-strip" aria-label="Supported outputs">
          <span>Portable Markdown</span>
          <span>Obsidian Vault</span>
          <span>RAG JSONL</span>
          <span>JSON-LD</span>
          <span>Source map</span>
          <span>Quality report</span>
        </section>

        <section className="transformation-story" id="product">
          <header>
            <h2>A compiler for evidence, not another file converter.</h2>
            <p>
              The system preserves the path from source to structure to
              knowledge. Select any result and return to the exact page region
              that produced it.
            </p>
          </header>
          <div className="proof-step-grid">
            {proofSteps.map((step) => {
              const Icon = step.icon;
              return (
                <article key={step.title}>
                  <div>
                    <Icon size={21} aria-hidden="true" />
                  </div>
                  <h3>{step.title}</h3>
                  <p>{step.copy}</p>
                  <small>{step.signal}</small>
                </article>
              );
            })}
          </div>
        </section>

        <section className="interactive-proof" id="demo">
          <div className="proof-copy">
            <h2>Inspect the source and output in one continuous workspace.</h2>
            <p>
              Processing Studio replays the same event contract used by live
              jobs. Page routes, typed blocks, review findings, and knowledge
              nodes update as the document moves through the pipeline.
            </p>
            <ul>
              <li>
                <Check size={14} weight="bold" aria-hidden="true" />
                Trace a Markdown row to its source table cell
              </li>
              <li>
                <Check size={14} weight="bold" aria-hidden="true" />
                Separate extracted facts from AI-derived text
              </li>
              <li>
                <Check size={14} weight="bold" aria-hidden="true" />
                Return from a graph relationship to the originating PDF
              </li>
            </ul>
            <Link href="/workspace" className="text-link">
              Open Processing Studio
              <ArrowRight size={15} aria-hidden="true" />
            </Link>
          </div>
          <div className="product-proof-frame">
            <div className="proof-frame-topbar">
              <span />
              <strong>evidence-grounded-report.pdf</strong>
              <small>Sample document · 14 pages</small>
            </div>
            <div className="proof-stage-rail">
              {["Upload", "Preflight", "Parse", "Normalize", "Knowledge"].map(
                (stage, index) => (
                  <span data-state={index < 3 ? "done" : "next"} key={stage}>
                    <i>{index < 3 ? "✓" : index + 1}</i>
                    {stage}
                  </span>
                ),
              )}
            </div>
            <div className="proof-workspace">
              <aside>
                {[12, 13, 14, 15].map((page) => (
                  <div
                    className={page === 14 ? "active" : undefined}
                    key={page}
                  >
                    <span>Page {page}</span>
                    <i>{page === 14 ? "Review 1" : "Native"}</i>
                  </div>
                ))}
              </aside>
              <div className="proof-source">
                <span>ORIGINAL · PAGE 14</span>
                <strong>Consolidated revenue</strong>
                <p>
                  The reported consolidated revenue increased during the fiscal
                  period.
                </p>
                <div className="proof-source-table">
                  <span>Current period</span>
                  <strong>1,234</strong>
                  <span>Prior period</span>
                  <strong>1,102</strong>
                </div>
                <i className="proof-bbox">table · source verified</i>
              </div>
              <div className="proof-result">
                <span>MARKDOWN · LIVE RESULT</span>
                <strong># Consolidated revenue</strong>
                <p>
                  The reported consolidated revenue increased during the fiscal
                  period.
                </p>
                <code>| Current period | 1,234 |</code>
                <small>
                  <ShieldCheck size={12} weight="fill" aria-hidden="true" />
                  Sample values match · not a performance claim
                </small>
              </div>
            </div>
          </div>
        </section>

        <section className="benchmark-section" id="benchmark">
          <header>
            <h2>
              Quality is reported by document type, not hidden in an average.
            </h2>
            <p>
              Each result names its corpus revision, evaluator, route, latency,
              cost, and evidence bundle. Unmeasured values remain unavailable.
            </p>
          </header>
          <div className="benchmark-grid">
            <div className="benchmark-matrix">
              <div className="benchmark-head">
                <span>Document subset</span>
                <span>Text</span>
                <span>Numbers</span>
                <span>Tables</span>
                <span>Source</span>
              </div>
              {publicBenchmarkSnapshot.datasets.map((dataset) => (
                <div key={dataset.id}>
                  <span>{benchmarkLabels[dataset.id] ?? dataset.label}</span>
                  <span>{formatBenchmarkPercent(dataset.metrics.text)}</span>
                  <span>{formatBenchmarkPercent(dataset.metrics.numbers)}</span>
                  <span>{formatBenchmarkPercent(dataset.metrics.tables)}</span>
                  <span>
                    {formatBenchmarkPercent(dataset.metrics.provenance)}
                  </span>
                </div>
              ))}
            </div>
            <article className="benchmark-method">
              <ChartScatter size={24} aria-hidden="true" />
              <h3>No evidence, no score.</h3>
              <p>
                Scores are pinned to a dataset revision, evaluator version,
                model revision, and route profile. Missing evidence is never
                displayed as zero.
              </p>
              <Link href="/benchmarks" className="text-link">
                Open Benchmark Lab
                <ArrowRight size={14} aria-hidden="true" />
              </Link>
            </article>
          </div>
        </section>

        <section className="security-product-section" id="security">
          <div>
            <h2>
              Security controls live in the product, not just on a trust page.
            </h2>
            <p>
              Provider access, processing region, source retention, and audit
              events are enforced as workspace policy before a job can run.
            </p>
          </div>
          <div className="policy-preview">
            <PolicyRow
              icon={LockKey}
              title="External provider"
              detail="Admin approval required"
              value="Restricted"
            />
            <PolicyRow
              icon={Stack}
              title="Source retention"
              detail="Automatic deletion"
              value="30 days"
            />
            <PolicyRow
              icon={FlowArrow}
              title="Processing region"
              detail="Fail closed outside policy"
              value="Seoul"
            />
            <PolicyRow
              icon={ShieldCheck}
              title="Audit evidence"
              detail="Review and export actions"
              value="Enabled"
            />
          </div>
        </section>

        <section className="pricing-section" id="pricing">
          <header>
            <h2>Choose the processing depth your documents require.</h2>
          </header>
          <div className="pricing-grid">
            {[
              {
                name: "Free",
                copy: "Small documents compiled into source-linked Markdown",
                items: ["Fast pages", "Portable Markdown", "7-day retention"],
              },
              {
                name: "Pro",
                copy: "Precision processing for research and personal knowledge",
                items: [
                  "Precision processing",
                  "Obsidian Vault",
                  "RAG package",
                ],
                featured: true,
              },
              {
                name: "Team",
                copy: "Shared review, knowledge bases, and operational controls",
                items: ["Shared projects", "Review workflow", "Audit history"],
              },
              {
                name: "Enterprise",
                copy: "Regional control, SSO, and private deployment options",
                items: ["SSO & MFA", "Provider policy", "Private deployment"],
              },
            ].map((plan) => (
              <article
                className={plan.featured ? "featured" : undefined}
                key={plan.name}
              >
                {plan.featured && <span>Recommended</span>}
                <h3>{plan.name}</h3>
                <p>{plan.copy}</p>
                <ul>
                  {plan.items.map((item) => (
                    <li key={item}>
                      <Check size={13} weight="bold" aria-hidden="true" />
                      {item}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/home"
                  className={
                    plan.featured ? "primary-button" : "secondary-button"
                  }
                >
                  {plan.name === "Enterprise"
                    ? "Contact sales"
                    : "Start compiling"}
                </Link>
              </article>
            ))}
          </div>
        </section>

        <section className="closing-cta">
          <h2>Build knowledge that can always show its work.</h2>
          <Link href="/home" className="primary-button hero-primary">
            Open your workspace
            <ArrowRight size={17} aria-hidden="true" />
          </Link>
        </section>
      </main>

      <footer className="marketing-footer">
        <div>
          <BrandMark />
          <p>Source-grounded knowledge from every document.</p>
        </div>
        <nav aria-label="Footer navigation">
          <a href="#product">Product</a>
          <a href="#benchmark">Benchmarks</a>
          <a href="#security">Security</a>
          <Link href="/notices">Third-party notices</Link>
          <Link href="/login">Sign in</Link>
        </nav>
        <small>
          © 2026 AI Knowledge Compiler. Unmeasured performance is never shown as
          a score.
        </small>
      </footer>
    </div>
  );
}

function PolicyRow({
  icon: Icon,
  title,
  detail,
  value,
}: {
  icon: typeof LockKey;
  title: string;
  detail: string;
  value: string;
}) {
  return (
    <div>
      <Icon size={18} aria-hidden="true" />
      <span>
        <strong>{title}</strong>
        <small>{detail}</small>
      </span>
      <i>{value}</i>
    </div>
  );
}
