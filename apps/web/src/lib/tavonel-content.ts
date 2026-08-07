export type TavonelSection = {
  title: string;
  body: string;
  items?: readonly string[];
};

export type TavonelPage = {
  path: string;
  family:
    "product" | "solution" | "demo" | "proof" | "editorial" | "docs" | "legal";
  label: string;
  title: string;
  intro: string;
  thesis: string;
  sections: readonly TavonelSection[];
  primaryAction: { label: string; href: string };
  secondaryAction?: { label: string; href: string };
};

const page = (
  path: string,
  family: TavonelPage["family"],
  label: string,
  title: string,
  intro: string,
  thesis: string,
  sections: readonly TavonelSection[],
  primaryAction: TavonelPage["primaryAction"] = {
    label: "Build your knowledge",
    href: "/signup",
  },
  secondaryAction?: TavonelPage["secondaryAction"],
): TavonelPage => ({
  path,
  family,
  label,
  title,
  intro,
  thesis,
  sections,
  primaryAction,
  secondaryAction,
});

export const PUBLIC_PAGES: Record<string, TavonelPage> = Object.fromEntries(
  [
    page(
      "/product",
      "product",
      "Product",
      "From source files to an intelligent knowledge system.",
      "Understand, verify, connect, and activate knowledge through one traceable workflow.",
      "One continuous compiler, not a collection of disconnected tools.",
      [
        {
          title: "Ingest",
          body: "Bring files, folders, batches, or API jobs into a policy-controlled project.",
          items: ["Files and folders", "Batch and API", "Retention policy"],
        },
        {
          title: "Structure",
          body: "Recover layout, tables, formulas, figures, and reading order.",
          items: ["Native extraction", "OCR routing", "Document hierarchy"],
        },
        {
          title: "Verify",
          body: "Return every important result to its page, block, and bounding box.",
          items: ["Source links", "Risk review", "Numeric differences"],
        },
        {
          title: "Compile",
          body: "Create notes, entities, relations, maps of content, and portable packages.",
          items: ["Knowledge notes", "Entity graph", "MOCs"],
        },
        {
          title: "Activate",
          body: "Move the same verified knowledge into people and AI workflows.",
          items: ["Markdown", "Obsidian", "RAG and JSON-LD"],
        },
      ],
      { label: "Explore Convert", href: "/product/convert" },
      { label: "Watch the end-to-end demo", href: "/demo/dart" },
    ),
    page(
      "/product/convert",
      "product",
      "Convert",
      "Clean Markdown is the beginning, not the end.",
      "Convert PDFs, scans, Office files, and images while preserving hierarchy, tables, figures, and source locations.",
      "Native when possible. Precision when the page requires it.",
      [
        {
          title: "Native when possible",
          body: "Documents that already contain text keep their original structure without unnecessary OCR.",
        },
        {
          title: "Precision when needed",
          body: "Scans, distortion, and complex tables move to a precision route automatically.",
        },
        {
          title: "Output layers",
          body: "Raw, Structured, and Knowledge layers remain distinct and inspectable.",
          items: [
            "Heading",
            "Paragraph",
            "List",
            "Table",
            "Figure",
            "Formula",
            "Footnote",
            "Citation",
          ],
        },
      ],
      { label: "Convert a sample", href: "/demo/dart" },
      { label: "View supported formats", href: "/developers/docs" },
    ),
    page(
      "/product/verify",
      "product",
      "Verify",
      "Do not trust extraction. Verify it.",
      "A Markdown sentence, metric, or table cell can always return to the source that produced it.",
      "Evidence is a first-class product surface.",
      [
        {
          title: "Source traceability",
          body: "Page, block, bounding box, and source hash travel with the output.",
        },
        {
          title: "Risk-based review",
          body: "Numbers, dates, units, tables, and missing content are prioritized by impact.",
        },
        {
          title: "Multiple candidates",
          body: "Compare route results or edit manually before accepting a block.",
        },
        {
          title: "Auditability",
          body: "Before, after, actor, time, route, and evidence are retained.",
        },
      ],
      { label: "Explore the proof demo", href: "/demo/dart" },
      { label: "Read the methodology", href: "/benchmarks" },
    ),
    page(
      "/product/knowledge",
      "product",
      "Knowledge",
      "Do not create more files. Build a knowledge system.",
      "Long documents become meaningful notes with properties, backlinks, maps of content, and evidence.",
      "A portable system that remains legible to people and AI.",
      [
        {
          title: "Meaningful boundaries",
          body: "Split by section, concept, or entity rather than arbitrary token length.",
        },
        {
          title: "Properties",
          body: "Title, aliases, source, status, tags, and review metadata stay explicit.",
        },
        {
          title: "Connections",
          body: "Related notes, backlinks, entity mentions, and evidence create navigable context.",
        },
        {
          title: "Obsidian-ready",
          body: "Folders, MOCs, Wikilinks, and assets arrive as a coherent vault.",
        },
      ],
      { label: "Open a sample Vault", href: "/demo/research-paper" },
      { label: "Build a knowledge project", href: "/signup" },
    ),
    page(
      "/product/graph",
      "product",
      "Graph",
      "Documents contain facts. Graphs reveal relationships.",
      "Explore a small, relevant subgraph first, with proof attached to every relation.",
      "Search before spectacle. Proof before inference.",
      [
        {
          title: "Perspectives",
          body: "Document, Entity, Risk, Timeline, and Evidence views define what matters.",
        },
        {
          title: "Search-first exploration",
          body: "Ask for a company, risk, metric, dataset, or unsupported note.",
        },
        {
          title: "Proof on every relation",
          body: "Select a relation to inspect its evidence list and exact source.",
        },
        {
          title: "Ontology export",
          body: "Export JSON-LD and Neo4j CSV; RDF and SHACL remain roadmap items.",
        },
      ],
      { label: "Explore the DART graph", href: "/demo/dart" },
      { label: "View ontology schema", href: "/developers/docs" },
    ),
    page(
      "/product/connect",
      "product",
      "Connect",
      "Compile knowledge once. Connect it everywhere.",
      "Package one verified knowledge core for AI projects, knowledge tools, RAG systems, and developer workflows.",
      "Connections are grouped by purpose, not scattered as a logo cloud.",
      [
        {
          title: "AI projects",
          body: "Prepare portable project packs for supported AI workspaces.",
        },
        {
          title: "Knowledge tools",
          body: "Export to Obsidian and GitHub; additional connectors remain labeled roadmap.",
        },
        {
          title: "RAG and search",
          body: "Produce source-linked data for pgvector, Qdrant, Pinecone, and Elasticsearch.",
        },
        {
          title: "Developer",
          body: "Use APIs, webhooks, SDKs, and later MCP integrations.",
        },
      ],
      { label: "View API docs", href: "/developers/docs" },
      { label: "Request an integration", href: "/company/contact" },
    ),
    page(
      "/solutions/individuals",
      "solution",
      "Individuals",
      "Your files, finally part of one mind.",
      "Turn notes, PDFs, and course material into connected knowledge you can own and reuse.",
      "From personal files to a durable, inspectable memory system.",
      [
        {
          title: "Bring the source",
          body: "Upload personal notes, books, lectures, and reference PDFs.",
        },
        {
          title: "Create the system",
          body: "Generate linked notes, properties, and an editable map of content.",
        },
        {
          title: "Keep control",
          body: "Use portable Markdown and choose retention and processing policy.",
        },
      ],
      { label: "Start free", href: "/signup" },
      { label: "Download a sample Vault", href: "/demo/course-material" },
    ),
    page(
      "/solutions/research",
      "solution",
      "Research",
      "Research faster without losing the source.",
      "Preserve paper structure, figures, formulas, methods, datasets, results, limitations, and citations.",
      "Five papers become a traceable literature system, not five isolated summaries.",
      [
        {
          title: "Structure the paper",
          body: "Keep methods, datasets, results, and limitations distinct.",
        },
        {
          title: "Follow citations",
          body: "Connect claims and cited works to their exact source position.",
        },
        {
          title: "Compare evidence",
          body: "Explore shared datasets, methods, and conflicting findings.",
        },
      ],
      { label: "Explore the research demo", href: "/demo/research-paper" },
    ),
    page(
      "/solutions/teams",
      "solution",
      "Teams",
      "One source of truth for people and AI.",
      "Shared projects, reviewer roles, version history, knowledge updates, and audit events keep teams aligned.",
      "Human review and automation converge on the same approved knowledge.",
      [
        {
          title: "Work together",
          body: "Assign project access, reviewer roles, and shared knowledge ownership.",
        },
        {
          title: "Approve changes",
          body: "Resolve high-impact uncertainty without re-reading the entire source.",
        },
        {
          title: "Track every decision",
          body: "Versions and audit events preserve how knowledge changed.",
        },
      ],
      { label: "Start a team workspace", href: "/signup" },
      { label: "Talk to sales", href: "/company/contact" },
    ),
    page(
      "/solutions/developers",
      "solution",
      "Developers",
      "Document intelligence without the parsing debt.",
      "Use an asynchronous API, typed contracts, webhooks, source maps, deterministic exports, and operational visibility.",
      "Request, events, verified package.",
      [
        {
          title: "Async by design",
          body: "Create jobs, observe durable events, and fetch resumable results.",
        },
        {
          title: "Typed outputs",
          body: "Use versioned canonical document and export contracts.",
        },
        {
          title: "Operational truth",
          body: "Inspect route, retries, cost ledger, source coverage, and failures.",
        },
      ],
      { label: "Read the quickstart", href: "/developers" },
      { label: "Open documentation", href: "/developers/docs" },
    ),
    page(
      "/solutions/enterprise",
      "solution",
      "Enterprise",
      "Trusted knowledge infrastructure for the enterprise.",
      "Apply organization policy across projects, workers, data regions, retention, external providers, and audit.",
      "Control surrounds the document before processing begins.",
      [
        {
          title: "Policy and identity",
          body: "Organization roles, SSO/MFA controls, and a clear SCIM roadmap.",
        },
        {
          title: "Data control",
          body: "Select region, retention, external provider policy, and private deployment options.",
        },
        {
          title: "Operational assurance",
          body: "Audit, incident response, support controls, and explicit service commitments.",
        },
      ],
      { label: "Talk to enterprise", href: "/company/contact" },
      { label: "View security architecture", href: "/security" },
    ),
    page(
      "/demo",
      "demo",
      "Demos",
      "See documents become knowledge.",
      "Inspect public filing, research paper, and course-material workflows through the same source-linked contract.",
      "Choose a source. Follow it through structure, proof, knowledge, and export.",
      [
        {
          title: "Korea DART",
          body: "A Korean filing with long-form text, financial tables, metrics, and corrected-filing relationships.",
        },
        {
          title: "US SEC EDGAR",
          body: "10-K, 10-Q, 8-K, Inline XBRL, risk factors, and source-linked entities.",
        },
        {
          title: "Research paper",
          body: "Methods, dataset, results, limitations, equations, figures, and citations.",
        },
        {
          title: "Course material",
          body: "Slides, handouts, and lecture notes compiled into concepts and a study graph.",
        },
      ],
      { label: "Open the DART demo", href: "/demo/dart" },
    ),
    page(
      "/demo/dart",
      "demo",
      "Public filing demo",
      "Korea DART Knowledge System.",
      "A source-linked public filing demo for Korean long-form text, tables, numbers, notes, graph relations, and benchmark evidence.",
      "Original → Markdown → Vault → Graph → Proof",
      [
        {
          title: "Original",
          body: "Navigate report outline, page rendering, and typed block overlays.",
        },
        {
          title: "Markdown",
          body: "Inspect source-linked lines, tables, and origin labels.",
        },
        {
          title: "Vault",
          body: "Companies, filings, metrics, segments, risks, subsidiaries, and corrections.",
        },
        {
          title: "Graph and benchmark",
          body: "Compare XML/XBRL ground truth without presenting unqualified scores.",
        },
      ],
      {
        label: "Open interactive proof",
        href: "/documents/sample-dart/processing",
      },
      { label: "Read the disclaimer", href: "/benchmarks" },
    ),
    page(
      "/demo/sec",
      "demo",
      "Public filing demo",
      "US SEC EDGAR Knowledge System.",
      "The same source-linked system applied to 10-K, 10-Q, 8-K, Inline XBRL, exhibits, segments, facts, and risk factors.",
      "One ontology across jurisdictions; no decorative jurisdiction palette.",
      [
        {
          title: "Entities",
          body: "Company, filing, segment, financial fact, risk factor, and exhibit.",
        },
        {
          title: "Evidence",
          body: "Every extracted fact returns to its filing and source location.",
        },
        {
          title: "Cross-jurisdiction",
          body: "Compare DART annual reports with SEC 10-K and event disclosures with 8-K.",
        },
      ],
      {
        label: "Open the filing demo",
        href: "/documents/sample-sec/processing",
      },
    ),
    page(
      "/demo/research-paper",
      "demo",
      "Research demo",
      "From paper to literature system.",
      "Follow abstract, method, dataset, result, limitation, figure, formula, and citation into notes and a small evidence graph.",
      "Paper → Structured Markdown → Concept Notes → Literature Graph → Evidence",
      [
        {
          title: "Paper",
          body: "Read the original page with figure, caption, formula, and citation overlays.",
        },
        {
          title: "Concept notes",
          body: "Build atomic notes around methods, data, results, and limitations.",
        },
        {
          title: "Literature graph",
          body: "Connect cited papers and shared datasets with source proof.",
        },
      ],
      {
        label: "Inspect the sample",
        href: "/documents/research-sample/processing",
      },
    ),
    page(
      "/demo/course-material",
      "demo",
      "Course demo",
      "Turn a course into a study system.",
      "Slides, handouts, and lecture notes become definitions, examples, concept notes, and optional practice prompts.",
      "Study material stays tied to the page and lecture it came from.",
      [
        { title: "Inputs", body: "Slides, handouts, and lecture notes." },
        {
          title: "Outputs",
          body: "Concept notes, definitions, examples, and a navigable study graph.",
        },
        {
          title: "Portable study",
          body: "Download an Obsidian-ready sample vault.",
        },
      ],
      { label: "Download sample Vault", href: "/app/exports" },
    ),
    page(
      "/benchmarks",
      "proof",
      "Benchmarks",
      "We benchmark what matters inside the document.",
      "Text alone is not enough. We measure numbers, tables, hierarchy, reading order, source traceability, latency, and cost.",
      "Accuracy should be demonstrated, not declared.",
      [
        {
          title: "Ground truth",
          body: "Dataset revision, sample count, route version, evaluator, and date accompany every result.",
        },
        {
          title: "Deterministic metrics",
          body: "Text, number, table, reading order, and source coverage remain separate.",
        },
        {
          title: "Page comparator",
          body: "Inspect ground truth, production, challenger, and differences at page level.",
        },
        {
          title: "What this does not prove",
          body: "No benchmark represents every customer document, language, or semantic use case.",
        },
      ],
      { label: "View the latest report", href: "/app/benchmarks" },
      { label: "Read the methodology", href: "/research" },
    ),
    page(
      "/research",
      "editorial",
      "Research",
      "Research for source-linked knowledge systems.",
      "Engineering notes, benchmark artifacts, and methods for document parsing, provenance, compilation, and ontology.",
      "A product laboratory with the discipline of a technical journal.",
      [
        {
          title: "AI-ready knowledge is not extracted text",
          body: "Why structure, context, relationships, and evidence matter before retrieval.",
        },
        {
          title: "A Korean document benchmark with DART",
          body: "Ground truth construction, limitations, and reproducible evaluation.",
        },
        {
          title: "Measuring source-linked Markdown",
          body: "How coverage and fidelity differ from surface similarity.",
        },
        {
          title: "From documents to ontology",
          body: "A portable path from blocks to notes, entities, and relations.",
        },
      ],
      { label: "Explore benchmarks", href: "/benchmarks" },
    ),
    page(
      "/security",
      "proof",
      "Security",
      "Your knowledge stays yours.",
      "Private by default, controlled by policy, and traceable by design—without showing unearned certifications.",
      "Browser → Signed Upload → Private Storage → Controlled Worker → Derived Knowledge → Scheduled Purge",
      [
        {
          title: "Encryption and isolation",
          body: "Protect data in transit and at rest; enforce tenant and project boundaries.",
        },
        {
          title: "Retention and deletion",
          body: "Make source, derivative, export, and audit lifecycles explicit.",
        },
        {
          title: "External processing",
          body: "Policy determines whether external providers are disabled, allowed, or require approval.",
        },
        {
          title: "Available and roadmap",
          body: "Separate current controls from SSO, SCIM, region, VPC, or on-prem roadmap items.",
        },
      ],
      { label: "Request the security package", href: "/company/contact" },
      { label: "Read data principles", href: "/legal/privacy" },
    ),
    page(
      "/pricing",
      "proof",
      "Pricing",
      "Start with documents. Scale into knowledge infrastructure.",
      "Choose by processing depth and operating control. Credits, page ranges, precision cost, retention, and caps stay visible.",
      "Illustrative plan structure; final commercial values require owner approval.",
      [
        {
          title: "Free and Personal",
          body: "Core conversion, clean Markdown, basic Obsidian output, and shorter retention.",
        },
        {
          title: "Pro and Team",
          body: "Precision routes, source comparison, knowledge notes, graph, reviewers, and API.",
        },
        {
          title: "Business and Enterprise",
          body: "Higher limits, policy controls, roles, support, region, and private deployment.",
        },
        {
          title: "Estimate, not quote",
          body: "Monthly pages, scan ratio, precision ratio, and knowledge output produce a bounded estimate.",
        },
      ],
      { label: "Start free", href: "/signup" },
      { label: "Talk to sales", href: "/company/contact" },
    ),
    page(
      "/customers",
      "editorial",
      "Proof stories",
      "Evidence before testimonials.",
      "Until approved customers and outcomes exist, this page presents public engineering studies, sample exports, and benchmark reports.",
      "No invented logos. No fabricated quotes. No decorative proof.",
      [
        {
          title: "DART engineering story",
          body: "How a complex public filing becomes a source-linked knowledge system.",
        },
        {
          title: "SEC ontology study",
          body: "How filing types, facts, risks, and exhibits map into a shared schema.",
        },
        {
          title: "Sample export",
          body: "Inspect the files, links, assets, coverage, and limitations in a portable package.",
        },
      ],
      { label: "Explore the DART study", href: "/demo/dart" },
    ),
    page(
      "/developers",
      "docs",
      "Developers",
      "Build on verified document knowledge.",
      "Upload, create a job, listen to events, review source maps, and download a deterministic package.",
      "Five steps from API key to verified output.",
      [
        {
          title: "1. Create a project",
          body: "Choose a policy, output profile, and idempotency key.",
        },
        {
          title: "2. Upload and process",
          body: "Use signed multipart upload and an asynchronous job.",
        },
        {
          title: "3. Observe",
          body: "Follow snapshots, sequence-aware SSE, and webhooks.",
        },
        {
          title: "4. Inspect and export",
          body: "Read canonical blocks, source maps, review items, and manifests.",
        },
      ],
      { label: "Open documentation", href: "/developers/docs" },
      { label: "Open API console", href: "/app/api" },
    ),
    page(
      "/developers/docs",
      "docs",
      "Documentation",
      "Everything needed to compile verified knowledge.",
      "Search versioned guides, copy examples, inspect API contracts, and understand limits and security behavior.",
      "Getting Started · Core Concepts · Upload · Processing · Review · Knowledge · Exports · API · Webhooks",
      [
        {
          title: "Getting started",
          body: "Create credentials, a project, upload, and the first job.",
        },
        {
          title: "Core concepts",
          body: "Project, Document, Job, Route, CIR, Evidence, and Export.",
        },
        {
          title: "Operations",
          body: "Events, retries, idempotency, webhooks, limits, and errors.",
        },
        {
          title: "Security",
          body: "Scopes, retention, external providers, regions, and deletion.",
        },
      ],
      { label: "Open API reference", href: "/developers/api" },
    ),
    page(
      "/developers/api",
      "docs",
      "API reference",
      "A typed contract for source-linked knowledge.",
      "Versioned endpoints cover authentication, projects, uploads, jobs, review, knowledge, exports, and operations.",
      "Requests are asynchronous; mutations are idempotent; events are sequence-aware.",
      [
        {
          title: "Projects and documents",
          body: "Create policy-bound containers and immutable source versions.",
        },
        {
          title: "Jobs and events",
          body: "Start work, follow SSE, reconcile snapshots, and handle retries.",
        },
        {
          title: "Review and knowledge",
          body: "Resolve candidates and access source-linked notes, entities, and relations.",
        },
        {
          title: "Exports",
          body: "Request packages and verify manifests and checksums.",
        },
      ],
      { label: "Open API console", href: "/app/api" },
    ),
    page(
      "/developers/sdk",
      "docs",
      "SDKs",
      "Integrate without hiding the contract.",
      "Small typed clients preserve explicit job, event, review, and export behavior.",
      "Python and TypeScript first; cURL remains the canonical portable example.",
      [
        {
          title: "Python",
          body: "Typed requests, event iteration, retry boundaries, and export downloads.",
        },
        {
          title: "TypeScript",
          body: "Browser and server runtimes with explicit credential boundaries.",
        },
        {
          title: "cURL",
          body: "Copyable protocol examples without SDK abstraction.",
        },
      ],
      { label: "Read the quickstart", href: "/developers/docs" },
    ),
    page(
      "/developers/changelog",
      "editorial",
      "Changelog",
      "Product behavior, explained.",
      "Browse Product, API, Models and Quality, Security, and Design changes with screenshots and migration notes.",
      "Model changes are described by route behavior and quality impact, with technical detail available.",
      [
        {
          title: "2026.07 — TAVONEL foundation",
          body: "New category, source-to-knowledge narrative, route system, and calm product shell.",
        },
        {
          title: "2026.07 — Evidence workflow",
          body: "Processing and review surfaces connect results to page and block evidence.",
        },
        {
          title: "2026.07 — Public proof",
          body: "DART, SEC, benchmark, and limitations surfaces become first-class routes.",
        },
      ],
      { label: "Read documentation", href: "/developers/docs" },
    ),
    page(
      "/company/about",
      "editorial",
      "About",
      "We are building the knowledge layer between documents and AI.",
      "Documents still lose structure and source relationships in AI workflows. Portable, evidence-linked knowledge is the layer in between.",
      "Evidence over confidence. Structure over decoration. Portability over lock-in.",
      [
        {
          title: "Why documents fail",
          body: "Pages hold layout, hierarchy, tables, figures, and context that plain extraction can flatten.",
        },
        {
          title: "Why source matters",
          body: "A result becomes useful when a person can verify it and a system can preserve its provenance.",
        },
        {
          title: "Why portability matters",
          body: "Knowledge should move across people, tools, models, and future systems.",
        },
      ],
      { label: "Read our principles", href: "/company/principles" },
    ),
    page(
      "/company/principles",
      "editorial",
      "Principles",
      "The decisions behind the compiler.",
      "Six operating principles connect directly to product behavior.",
      "Source before generation.",
      [
        {
          title: "Source before generation",
          body: "Keep extracted, inferred, and edited content visibly distinct.",
        },
        {
          title: "Evidence before confidence",
          body: "Show where a result came from before asking users to trust a score.",
        },
        {
          title: "Structure before intelligence",
          body: "Recover the document before deriving the knowledge.",
        },
        {
          title: "Control before automation",
          body: "Policy and review boundaries precede unattended processing.",
        },
        {
          title: "Portability before lock-in",
          body: "Use open, inspectable exports.",
        },
        {
          title: "Benchmark before adoption",
          body: "Publish method and limitations with every claim.",
        },
      ],
      { label: "See the product", href: "/product" },
    ),
    page(
      "/company/careers",
      "editorial",
      "Careers",
      "Build the infrastructure that helps AI understand the world’s documents.",
      "Join a small team working on parsing, provenance, knowledge systems, benchmarks, product craft, and trustworthy infrastructure.",
      "Real product and research work, not invented culture photography.",
      [
        {
          title: "Mission",
          body: "Make complex source material usable without hiding its uncertainty or origin.",
        },
        {
          title: "How we work",
          body: "Small scopes, measurable quality, durable decisions, and direct product evidence.",
        },
        {
          title: "Open roles",
          body: "No roles are published until approved by the company owner.",
        },
      ],
      { label: "Contact the team", href: "/company/contact" },
    ),
    page(
      "/company/contact",
      "editorial",
      "Contact",
      "Tell us what your knowledge needs to become.",
      "Share document volume, primary need, and security requirements. Do not upload sensitive documents in this form.",
      "A knowledge architect reviews the request; response time is confirmed after operating policy approval.",
      [
        {
          title: "What to include",
          body: "Company, role, document volume, source types, target outputs, and security needs.",
        },
        {
          title: "Security review",
          body: "Architecture and policy material can be shared through an approved follow-up channel.",
        },
        {
          title: "No source upload",
          body: "This contact route never requests customer documents.",
        },
      ],
      { label: "Open contact form", href: "mailto:sales@example.invalid" },
    ),
    page(
      "/legal/privacy",
      "legal",
      "Legal",
      "Privacy principles.",
      "This repository demonstrates product controls; final public policy text requires legal approval before external launch.",
      "Collect less. Explain purpose. Retain by policy. Delete completely.",
      [
        {
          title: "Data categories",
          body: "Account, project, source, derivative, operational, billing, and audit data remain distinct.",
        },
        {
          title: "Processing",
          body: "Purpose, provider boundary, region, and retention are visible before a job begins.",
        },
        {
          title: "Rights and deletion",
          body: "Export, correction, deletion, and support processes require production contact details.",
        },
      ],
      { label: "Contact privacy", href: "/company/contact" },
    ),
    page(
      "/legal/terms",
      "legal",
      "Legal",
      "Terms of service.",
      "Final legal terms, governing entity, jurisdiction, payment terms, and service commitments require owner and counsel approval.",
      "This route is an implementation-ready legal shell, not published legal advice.",
      [
        {
          title: "Service",
          body: "Account, acceptable use, source rights, outputs, and API behavior.",
        },
        {
          title: "Commercial",
          body: "Plans, credits, refunds, taxes, suspension, and termination.",
        },
        {
          title: "Risk",
          body: "Warranties, limitations, indemnity, and dispute process.",
        },
      ],
      { label: "Contact legal", href: "/company/contact" },
    ),
    page(
      "/legal/subprocessors",
      "legal",
      "Legal",
      "Subprocessors and infrastructure.",
      "Production vendors, purpose, data category, region, and change notice are listed only after deployment choices are approved.",
      "No vendor is presented as active from a local development configuration alone.",
      [
        {
          title: "Infrastructure",
          body: "Hosting, storage, database, observability, email, and payment vendors.",
        },
        {
          title: "Processing",
          body: "External model or OCR providers appear with their exact policy scope.",
        },
        {
          title: "Change control",
          body: "Material changes require a dated notice and owner approval.",
        },
      ],
      { label: "Request current list", href: "/company/contact" },
    ),
    page(
      "/legal/third-party-notices",
      "legal",
      "Legal",
      "Third-party notices.",
      "Runtime packages, licenses, attributions, assets, fonts, and public data sources are recorded before release.",
      "The repository license register is the implementation source of truth.",
      [
        {
          title: "Software",
          body: "Open-source runtime and build packages with observed licenses.",
        },
        {
          title: "Assets",
          body: "Fonts, textures, images, video, 3D, and generated asset provenance.",
        },
        {
          title: "Public data",
          body: "DART and SEC source terms and required notices.",
        },
      ],
      { label: "View repository notices", href: "/notices" },
    ),
  ].map((definition) => [definition.path, definition]),
);

export const APP_PAGE_COPY: Record<
  string,
  { title: string; description: string; action: string }
> = {
  home: {
    title: "Today in your workspace",
    description:
      "Active processing, high-impact review, recent knowledge, and usage at a glance.",
    action: "Upload documents",
  },
  projects: {
    title: "Projects",
    description:
      "Organize sources, policy, collaborators, and knowledge outputs.",
    action: "New project",
  },
  jobs: {
    title: "Jobs",
    description:
      "Inspect durable stage progress, review state, cost ledger, retries, and events.",
    action: "Open filters",
  },
  "knowledge-bases": {
    title: "Knowledge bases",
    description:
      "Explore notes, entities, relations, source coverage, and health recommendations.",
    action: "Open knowledge",
  },
  benchmarks: {
    title: "Benchmark Lab",
    description:
      "Compare production and challenger routes against versioned ground truth.",
    action: "Run benchmark",
  },
  recipes: {
    title: "Recipes",
    description: "Save processing policy without binding users to model names.",
    action: "New recipe",
  },
  exports: {
    title: "Export center",
    description:
      "Package verified knowledge for people, AI projects, RAG systems, and graphs.",
    action: "New export",
  },
  api: {
    title: "API console",
    description: "Manage keys, playground requests, webhooks, usage, and logs.",
    action: "Create key",
  },
  usage: {
    title: "Usage",
    description:
      "Understand pages, credits, jobs, storage, precision, review, and bounded cost.",
    action: "Export usage",
  },
  billing: {
    title: "Billing",
    description:
      "Manage plan, credits, caps, alerts, invoices, and failure refunds.",
    action: "Manage plan",
  },
};
