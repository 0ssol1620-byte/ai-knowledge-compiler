import {
  ArrowRight,
  Check,
  FileArrowUp,
  FileText,
  Funnel,
  Graph,
  MagnifyingGlass,
  ShieldCheck,
  WarningCircle,
} from "@phosphor-icons/react/dist/ssr";
import type { Route } from "next";
import Link from "next/link";
import type { CSSProperties } from "react";

import { appActionHref } from "@/lib/app-action";

type AppPageProps = {
  route: string;
  title: string;
  description: string;
  action: string;
};

const projectRows = [
  ["DART Annual Report", "6", "152", "3", "12 min ago", "Active"],
  ["Source-linked Research", "18", "486", "1", "Yesterday", "Active"],
  ["Course Knowledge Base", "9", "214", "0", "Jul 28", "Ready"],
] as const;

const jobRows = [
  ["Annual_Report_2025.pdf", "Parse", "128 / 421", "2", "83 / 120", "Running"],
  ["Research_Corpus_04.zip", "Knowledge", "18 / 42", "1", "44 / 80", "Running"],
  ["Course_Material.pdf", "Package", "96 / 96", "0", "31 / 40", "Ready"],
] as const;

const SAMPLE_CONTROL_TITLE =
  "Interactive controls require a connected workspace.";

export function FolyntaAppPage({
  route,
  title,
  description,
  action,
}: AppPageProps) {
  const isHome = route === "home";
  const isProjects = route.includes("projects");
  const isSettings = route.includes("settings");
  const isAdmin = route.includes("admin");
  const isKnowledge = route.includes("knowledge") || route.includes("graph");
  const isDocument = route.startsWith("document/");
  const specialized = [
    "jobs",
    "exports",
    "benchmarks",
    "recipes",
    "api",
    "usage",
    "billing",
  ].includes(route);

  return (
    <div className="fl-app-page">
      <header className="fl-app-context">
        <div>
          <p>Sample workspace / {route.replaceAll("/", " / ")}</p>
          <h1>{title}</h1>
          <span>{description}</span>
        </div>
        <Link
          href={appActionHref(route) as Route}
          className="fl-app-primary"
          data-app-header-action
        >
          {action}
          <ArrowRight size={14} aria-hidden="true" />
        </Link>
      </header>

      {isHome && <HomeOverview />}
      {isProjects && <ProjectsOverview route={route} />}
      {isKnowledge && !isProjects && !isDocument && <KnowledgeOverview />}
      {isSettings && <PolicyOverview route={route} />}
      {isAdmin && <AdminOverview route={route} />}
      {isDocument && <DocumentOverview route={route} />}
      {specialized && <SpecializedOverview route={route} />}
      {!isHome &&
        !isProjects &&
        !isSettings &&
        !isAdmin &&
        !isDocument &&
        !specialized &&
        !isKnowledge && <OperationsOverview route={route} />}
    </div>
  );
}

function HomeOverview() {
  return (
    <>
      <section className="fl-app-command">
        <div>
          <FileArrowUp size={20} aria-hidden="true" />
          <div>
            <strong>Start with a document</strong>
            <span>PDF, Office, image, HTML, text, and subtitle files</span>
          </div>
        </div>
        <Link href="/quick-convert">Upload documents</Link>
      </section>
      <MetricStrip
        values={[
          ["Active jobs", "2", "1 table route escalated"],
          ["Review required", "3", "2 numeric · 1 table"],
          ["Knowledge notes", "852", "18 created today"],
          ["Source coverage", "99.6%", "5 AI-only blocks labeled"],
        ]}
      />
      <section className="fl-app-split">
        <div className="fl-app-panel">
          <PanelHeader
            label="Active work"
            title="Processing now"
            href="/app/jobs"
          />
          <AppTable
            headers={[
              "Document",
              "Stage",
              "Progress",
              "Review",
              "Credits",
              "State",
            ]}
            rows={jobRows}
          />
        </div>
        <aside className="fl-app-panel fl-review-summary">
          <PanelHeader label="Priority queue" title="Needs review" />
          {(
            [
              [
                "Numeric mismatch",
                "Annual report · p214 · Table 7",
                "/documents/sample-dart/review",
              ],
              [
                "Table structure",
                "Research corpus · p38",
                "/documents/research-sample/review",
              ],
            ] as const
          ).map(([title, note, href]) => (
            <article key={title}>
              <WarningCircle size={18} aria-hidden="true" />
              <div>
                <strong>{title}</strong>
                <span>{note}</span>
              </div>
              <Link href={href}>Review</Link>
            </article>
          ))}
        </aside>
      </section>
      <section className="fl-home-lower">
        <article>
          <PanelHeader
            label="Recent projects"
            title="Knowledge in motion"
            href="/app/projects"
          />
          <dl>
            <div>
              <dt>DART Annual Report</dt>
              <dd>152 notes · 99.8% source coverage</dd>
            </div>
            <div>
              <dt>Source-linked Research</dt>
              <dd>486 notes · 1 review item</dd>
            </div>
          </dl>
        </article>
        <article>
          <PanelHeader
            label="Recent exports"
            title="Ready to use"
            href="/app/exports"
          />
          <dl>
            <div>
              <dt>Obsidian Vault</dt>
              <dd>Ready · checksum verified</dd>
            </div>
            <div>
              <dt>RAG JSONL</dt>
              <dd>Expires in 6 days</dd>
            </div>
          </dl>
        </article>
        <article>
          <PanelHeader
            label="Usage"
            title="This billing period"
            href="/app/usage"
          />
          <strong className="fl-usage-number">
            1,284 <small>pages</small>
          </strong>
          <p>42 jobs · 18% precision route · 1.4% review rate</p>
        </article>
      </section>
    </>
  );
}

function ProjectsOverview({ route }: { route: string }) {
  const detail = route.split("/").length > 1;
  return (
    <>
      <section className="fl-app-tools">
        <label>
          <MagnifyingGlass size={15} aria-hidden="true" />
          <input
            aria-label="Search projects"
            placeholder="Search requires a connected workspace"
            disabled
            title={SAMPLE_CONTROL_TITLE}
          />
        </label>
        <button
          type="button"
          disabled
          title={SAMPLE_CONTROL_TITLE}
          data-sample-static-control
        >
          <Funnel size={14} /> Filters
        </button>
        <div className="fl-view-switch" aria-label="Project view">
          <button
            type="button"
            aria-pressed="true"
            disabled
            title={SAMPLE_CONTROL_TITLE}
            data-sample-static-control
          >
            List
          </button>
          <button
            type="button"
            aria-pressed="false"
            disabled
            title={SAMPLE_CONTROL_TITLE}
            data-sample-static-control
          >
            Grid
          </button>
        </div>
      </section>
      <MetricStrip
        values={[
          ["Documents", detail ? "6" : "33", "Accepted sources"],
          ["Knowledge notes", detail ? "152" : "852", "Source-linked"],
          ["Review required", detail ? "3" : "4", "High impact"],
          ["Broken links", "0", "Last checked today"],
        ]}
      />
      <section className="fl-app-panel fl-project-table">
        <PanelHeader
          label={detail ? "Project evidence" : "Workspace inventory"}
          title={detail ? "Recent documents" : "All projects"}
        />
        <AppTable
          headers={
            detail
              ? [
                  "Document",
                  "Version",
                  "Pages",
                  "Processing",
                  "Review",
                  "Updated",
                ]
              : ["Project", "Documents", "Notes", "Review", "Members", "Status"]
          }
          rows={projectRows}
        />
      </section>
      {detail && (
        <section className="fl-project-health">
          <PanelHeader label="Knowledge health" title="Evidence integrity" />
          {[
            ["Source coverage", "High"],
            ["Broken links", "0"],
            ["Duplicate entities", "4"],
            ["Outdated documents", "2"],
            ["Review required", "3"],
          ].map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </section>
      )}
    </>
  );
}

type SpecializedSpec = {
  tabs: readonly string[];
  metrics: readonly (readonly string[])[];
  title: string;
  headers: readonly string[];
  rows: readonly (readonly string[])[];
  note: string;
};

const specializedSpecs: Record<string, SpecializedSpec> = {
  jobs: {
    tabs: ["All", "Queued", "Running", "Review", "Failed", "Completed"],
    metrics: [
      ["Running", "2", "Durable jobs"],
      ["Review", "3", "High impact"],
      ["Failed", "0", "Last 24 hours"],
      ["p95 duration", "8m 42s", "Balanced route"],
    ],
    title: "Durable job ledger",
    headers: ["Job", "Project", "Stage", "Progress", "Review", "Cost"],
    rows: [
      [
        "job_28c9",
        "DART Annual Report",
        "Parse",
        "128 / 421",
        "2",
        "83 credits",
      ],
      [
        "job_1ac4",
        "Research Corpus",
        "Knowledge",
        "18 / 42",
        "1",
        "44 credits",
      ],
      ["job_88df", "Course Material", "Package", "96 / 96", "0", "31 credits"],
    ],
    note: "Open a job to inspect stage counts, retries, route history, credit ledger, events, and output links.",
  },
  exports: {
    tabs: ["All outputs", "Portable Markdown", "Obsidian", "RAG", "Graph"],
    metrics: [
      ["Ready", "4", "Checksum verified"],
      ["Packaging", "1", "Obsidian Vault"],
      ["Broken links", "0", "Latest package"],
      ["Source coverage", "99.8%", "Accepted blocks"],
    ],
    title: "Output packages",
    headers: ["Package", "Contents", "Evidence", "State", "Expires", "Action"],
    rows: [
      [
        "Obsidian Vault",
        "152 notes · 486 links",
        "99.8%",
        "Ready",
        "6 days",
        "Download",
      ],
      ["RAG JSONL", "1,284 chunks", "99.6%", "Ready", "6 days", "Download"],
      [
        "Neo4j CSV",
        "852 nodes · 1,940 edges",
        "99.4%",
        "Packaging",
        "—",
        "Open",
      ],
    ],
    note: "Choose raw, structured, and knowledge layers; source assets; summaries; inferred relations; language; filenames; and redaction.",
  },
  benchmarks: {
    tabs: ["Overview", "Regressions", "Comparator", "Datasets"],
    metrics: [
      ["Production route", "Balanced v12", "Signed recipe"],
      ["Last run", "Jul 30", "DART + SEC"],
      ["Regressions", "3", "1 critical"],
      ["p95 cost", "0.84×", "Against budget"],
    ],
    title: "Evidence-grounded route comparison",
    headers: ["Route", "Dataset", "Text", "Number", "Table", "Source"],
    rows: [
      ["Production v12", "DART 2026.07", "99.2", "98.6", "94.1", "99.6"],
      ["Candidate A", "DART 2026.07", "99.3", "98.4", "95.0", "99.5"],
      ["Candidate B", "SEC 2026.07", "98.8", "97.9", "93.8", "99.7"],
    ],
    note: "Scores only represent the named, versioned sample dataset and signed evaluation recipe. They are not universal accuracy claims.",
  },
  recipes: {
    tabs: ["All recipes", "Workspace", "Shared", "Archived"],
    metrics: [
      ["Active recipes", "6", "2 shared"],
      ["Default", "Balanced", "Knowledge enabled"],
      ["External policy", "Ask", "Every job"],
      ["Retention", "7 days", "Source files"],
    ],
    title: "Processing policies",
    headers: [
      "Recipe",
      "Parsing",
      "Review",
      "Knowledge",
      "External",
      "Retention",
    ],
    rows: [
      [
        "Balanced Knowledge",
        "Native first",
        "Numbers + tables",
        "Enabled",
        "Ask",
        "7 days",
      ],
      [
        "Private Archive",
        "Local only",
        "Critical",
        "Enabled",
        "Disabled",
        "24 hours",
      ],
      [
        "Fast Markdown",
        "Native first",
        "Errors only",
        "Disabled",
        "Ask",
        "7 days",
      ],
    ],
    note: "Recipes describe input, parsing mode, review policy, knowledge output, privacy, and export—never vendor model names.",
  },
  api: {
    tabs: ["Keys", "Playground", "Webhooks", "Usage", "Logs"],
    metrics: [
      ["Active keys", "3", "Scoped"],
      ["Requests", "18,284", "This period"],
      ["Webhooks", "2", "Healthy"],
      ["Error rate", "0.12%", "Last 24 hours"],
    ],
    title: "Keys and request activity",
    headers: ["Key", "Scope", "Environment", "Last used", "Expires", "Action"],
    rows: [
      [
        "Production compiler",
        "jobs:write",
        "Production",
        "4 min ago",
        "Oct 30",
        "Rotate",
      ],
      [
        "Research read-only",
        "knowledge:read",
        "Sandbox",
        "Yesterday",
        "Never",
        "Revoke",
      ],
      [
        "Export service",
        "exports:write",
        "Production",
        "Jul 28",
        "Sep 30",
        "Rotate",
      ],
    ],
    note: "A secret is displayed once at creation. Playground responses stream with a source-map preview and copyable request code.",
  },
  usage: {
    tabs: ["Overview", "By project", "By route", "Storage"],
    metrics: [
      ["Credits", "1,842", "58% of cap"],
      ["Pages", "12,840", "This period"],
      ["Jobs", "284", "42 active/recent"],
      ["Storage", "18.4 GB", "Source + exports"],
    ],
    title: "Transparent usage ledger",
    headers: [
      "Processing class",
      "Pages",
      "Credits",
      "Share",
      "Change",
      "Policy",
    ],
    rows: [
      ["Native processing", "8,420", "624", "33.9%", "+4.2%", "Within"],
      ["OCR processing", "3,810", "702", "38.1%", "−1.8%", "Within"],
      ["Precision verification", "610", "308", "16.7%", "+0.6%", "Within"],
      ["Knowledge compilation", "12,840", "208", "11.3%", "+2.1%", "Within"],
    ],
    note: "Usage reports processing classes and bounded credits. Individual provider or model cost is intentionally not exposed.",
  },
  billing: {
    tabs: ["Plan", "Credits", "Invoices", "Payment method"],
    metrics: [
      ["Current plan", "Team", "Annual"],
      ["Credit balance", "4,218", "Auto-recharge off"],
      ["Monthly cap", "8,000", "58% used"],
      ["Next invoice", "Aug 30", "Payment method verified"],
    ],
    title: "Billing controls",
    headers: [
      "Control",
      "Current",
      "Alert",
      "Enforcement",
      "Updated",
      "Action",
    ],
    rows: [
      [
        "Monthly hard cap",
        "8,000 credits",
        "70 / 90 / 100%",
        "Stop new jobs",
        "Jul 30",
        "Edit",
      ],
      [
        "Per-job cap",
        "240 credits",
        "At estimate",
        "Require approval",
        "Jul 29",
        "Edit",
      ],
      [
        "Failure refunds",
        "Automatic",
        "Ledger event",
        "Immediate",
        "Today",
        "View ledger",
      ],
    ],
    note: "Failed-work credit recovery appears in the verified ledger. Cancellation, invoices, payment method, and usage alerts remain explicit.",
  },
};

function SpecializedOverview({ route }: { route: string }) {
  const spec = specializedSpecs[route]!;
  return (
    <>
      <nav className="fl-feature-tabs" aria-label={`${route} sections`}>
        {spec.tabs.map((tab, index) => (
          <button
            type="button"
            aria-pressed={index === 0}
            key={tab}
            disabled
            title={SAMPLE_CONTROL_TITLE}
            data-sample-static-control
          >
            {tab}
          </button>
        ))}
      </nav>
      <MetricStrip values={spec.metrics} />
      <section className="fl-app-panel fl-feature-ledger">
        <PanelHeader label="Operational detail" title={spec.title} />
        <AppTable headers={spec.headers} rows={spec.rows} />
        <p className="fl-feature-note">{spec.note}</p>
      </section>
    </>
  );
}

function DocumentOverview({ route }: { route: string }) {
  const view = route.split("/").at(-1);
  if (view === "sources") {
    return (
      <>
        <MetricStrip
          values={[
            ["Accepted blocks", "1,284", "Current version"],
            ["Source-linked", "1,279", "Page + bbox"],
            ["AI-only", "5", "Clearly labeled"],
            ["Coverage", "99.6%", "Review tracked"],
          ]}
        />
        <section className="fl-app-panel">
          <PanelHeader label="Provenance" title="Evidence by output block" />
          <AppTable
            headers={[
              "Output block",
              "Source page",
              "Source bbox",
              "Origin",
              "Evidence",
              "Review",
            ]}
            rows={[
              [
                "Revenue table",
                "214",
                "144,320,882,706",
                "Extracted",
                "Verified",
                "Accepted",
              ],
              [
                "Risk summary",
                "208",
                "92,178,914,440",
                "AI-assisted",
                "3 sources",
                "Accepted",
              ],
              [
                "FX relation",
                "92",
                "210,260,778,510",
                "Inferred",
                "Weak",
                "Review",
              ],
            ]}
          />
        </section>
      </>
    );
  }
  if (view === "versions") {
    return (
      <section className="fl-app-panel fl-version-ledger">
        <PanelHeader
          label="Document history"
          title="Non-destructive versions"
        />
        {[
          ["v4", "User edit + export", "Today, 10:42", "Current"],
          ["v3", "Precision reprocess", "Yesterday, 16:18", "Compare"],
          ["v2", "Recipe changed", "Jul 28, 09:12", "Compare"],
          ["v1", "Original upload", "Jul 27, 14:03", "Source"],
        ].map(([version, event, time, action]) => (
          <div key={version}>
            <strong>{version}</strong>
            <span>
              {event}
              <small>{time}</small>
            </span>
            <button
              type="button"
              disabled
              title={SAMPLE_CONTROL_TITLE}
              data-sample-static-control
            >
              {action}
            </button>
          </div>
        ))}
        <p className="fl-feature-note">
          Restore creates a new version after showing source, Markdown, and
          linked-knowledge impact. Existing history is never overwritten.
        </p>
      </section>
    );
  }
  return (
    <section className="fl-editor-layout">
      <aside>
        <span>Outline</span>
        {[
          "Executive summary",
          "Business overview",
          "Risk factors",
          "Financial statements",
        ].map((item) => (
          <button
            type="button"
            key={item}
            disabled
            title={SAMPLE_CONTROL_TITLE}
            data-sample-static-control
          >
            {item}
          </button>
        ))}
      </aside>
      <article>
        <header>
          <span>Preview</span>
          <span>Source</span>
          <strong>Split</strong>
        </header>
        <p className="fl-editor-kicker">Page 214 · paragraph 3 · User-edited</p>
        <h2>Foreign exchange risk</h2>
        <p>
          The company manages foreign exchange exposure through policy-governed
          instruments and continuous review.
        </p>
        <blockquote>
          Source-linked content remains locked against automatic overwrite. A
          new candidate is available for comparison.
        </blockquote>
      </article>
      <aside className="fl-proof-panel">
        <span>Evidence</span>
        <h2>Source page 214</h2>
        <p>Bounding box 92, 178, 914, 440</p>
        <strong>Verified</strong>
        <button
          type="button"
          disabled
          title={SAMPLE_CONTROL_TITLE}
          data-sample-static-control
        >
          Compare candidate
        </button>
        <button
          type="button"
          disabled
          title={SAMPLE_CONTROL_TITLE}
          data-sample-static-control
        >
          Keep mine
        </button>
      </aside>
    </section>
  );
}

function AdminOverview({ route }: { route: string }) {
  const section = route.split("/").at(-1) ?? "jobs";
  const rows: readonly (readonly string[])[] = [
    [`${section}_28c9`, "Healthy", "v2026.07.30", "4.2s", "0.12%", "Inspect"],
    [`${section}_1ac4`, "Review", "v2026.07.29", "18.6s", "0.84%", "Open"],
    [`${section}_88df`, "Healthy", "v2026.07.30", "6.1s", "0.08%", "Inspect"],
  ];
  return (
    <>
      <MetricStrip
        values={[
          ["Queue age", "4.2s", "p95"],
          ["Workers", "12 / 14", "Warm"],
          ["Terminal success", "99.7%", "24 hours"],
          ["Cost outliers", "2", "Review required"],
        ]}
      />
      <section className="fl-app-panel">
        <PanelHeader label="Operations console" title={section} />
        <AppTable
          headers={[
            "Resource",
            "State",
            "Version",
            "Latency",
            "Error",
            "Action",
          ]}
          rows={rows}
        />
        <p className="fl-feature-note">
          Operational views use safe identifiers only. Document content,
          filenames, email addresses, and secrets are excluded from logs and
          tables.
        </p>
      </section>
    </>
  );
}

function KnowledgeOverview() {
  return (
    <section className="fl-knowledge-layout">
      <aside className="fl-knowledge-nav">
        <span>Perspectives</span>
        {["Company", "Risk", "Metric", "Timeline", "Source"].map(
          (item, index) => (
            <button
              type="button"
              data-active={index === 0}
              key={item}
              disabled
              title={SAMPLE_CONTROL_TITLE}
              data-sample-static-control
            >
              {item}
            </button>
          ),
        )}
      </aside>
      <div
        className="fl-graph-scene"
        aria-label="Accessible sample knowledge graph"
      >
        <Graph size={20} aria-hidden="true" />
        {["Company", "Filing", "Risk", "Metric", "Evidence"].map(
          (node, index) => (
            <button
              type="button"
              key={node}
              style={{ "--node-index": index } as CSSProperties}
              disabled
              title={SAMPLE_CONTROL_TITLE}
              data-sample-static-control
            >
              {node}
            </button>
          ),
        )}
      </div>
      <aside className="fl-proof-panel">
        <span>Proof panel</span>
        <h2>Company → facesRisk → FX volatility</h2>
        <strong>Evidence 3</strong>
        <p>2025 Annual Report · page 214</p>
        <p>2024 Annual Report · page 208</p>
        <p>2026 Q1 Filing · page 92</p>
        <small>Origin: extracted · Review: user verified</small>
        <Link href="/documents/sample-dart/sources">Open source</Link>
      </aside>
    </section>
  );
}

function PolicyOverview({ route }: { route: string }) {
  const policies = [
    ["External processing", "Ask for every job", "Enforced"],
    ["Default retention", "7 days", "Enforced"],
    ["Processing region", "Seoul", "Available"],
    ["MFA enforcement", "Administrators", "Available"],
    ["Audit export", "Daily package", "Available"],
  ] as const;
  return (
    <section className="fl-app-panel fl-policy-table">
      <PanelHeader
        label="Organization policy"
        title={
          route.includes("admin")
            ? "Operational controls"
            : "Security and retention"
        }
      />
      {policies.map(([name, value, state]) => (
        <div key={name}>
          <ShieldCheck size={16} aria-hidden="true" />
          <span>
            <strong>{name}</strong>
            <small>Changes require impact review and an audit event.</small>
          </span>
          <b>{value}</b>
          <em>{state}</em>
        </div>
      ))}
    </section>
  );
}

function OperationsOverview({ route }: { route: string }) {
  return (
    <>
      <MetricStrip
        values={[
          ["Pages", "1,284", "This period"],
          ["Jobs", "42", "2 active"],
          ["Precision ratio", "18%", "Within policy"],
          ["Review rate", "1.4%", "High impact only"],
        ]}
      />
      <section className="fl-app-panel">
        <PanelHeader
          label="Operational detail"
          title={route.replaceAll("-", " ")}
        />
        <AppTable
          headers={[
            "Document",
            "Stage",
            "Progress",
            "Review",
            "Credits",
            "State",
          ]}
          rows={jobRows}
        />
      </section>
    </>
  );
}

function MetricStrip({ values }: { values: readonly (readonly string[])[] }) {
  return (
    <section className="fl-app-metrics" aria-label="Workspace summary">
      {values.map(([label, value, note]) => (
        <article key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
          <small>{note}</small>
        </article>
      ))}
    </section>
  );
}

function PanelHeader({
  label,
  title,
  href,
}: {
  label: string;
  title: string;
  href?: string;
}) {
  return (
    <header>
      <div>
        <span>{label}</span>
        <h2>{title}</h2>
      </div>
      {href && <Link href={href as Route}>View all</Link>}
    </header>
  );
}

function AppTable({
  headers,
  rows,
}: {
  headers: readonly string[];
  rows: readonly (readonly string[])[];
}) {
  return (
    <div
      className="fl-data-table"
      role="table"
      aria-label="Data table"
      tabIndex={0}
    >
      <div role="row" className="fl-data-head">
        {headers.map((header) => (
          <span role="columnheader" key={header}>
            {header}
          </span>
        ))}
      </div>
      {rows.map((row) => (
        <div role="row" key={row[0]}>
          {row.map((cell, index) => (
            <span role="cell" key={`${row[0]}-${index}`}>
              {index === 0 && <FileText size={15} aria-hidden="true" />}
              {cell}
              {index === row.length - 1 && (
                <Check size={13} aria-hidden="true" />
              )}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}
