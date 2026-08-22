import type {
  ProductEvent,
  ResolutionBasis,
  SourceRefLite,
  TemporalStatus,
} from "@/lib/product-event";

/**
 * The demo workspace — a synthetic fixture, and it says so everywhere.
 *
 * Every figure below is invented for the landing page. None of it is a
 * measurement, a customer, or a benchmark result. The published numbers this
 * product is allowed to state live in `lib/claims.ts` and arrive with their
 * receipts; nothing here may be presented next to them without the
 * `SAMPLE WORKSPACE` label that `DemoModeBadge` renders, and no figure here
 * appears in a sentence that reads as a claim.
 *
 * It is deterministic on purpose. The whole point of the source abstraction is
 * that the same projection code runs against a fixture and against a live SSE
 * stream, so the fixture has to be replayable byte-for-byte: fixed ids, fixed
 * timestamps derived from one epoch, fixed graph coordinates. That is also
 * what makes the Playwright visual baselines stable — a random layout would
 * make every screenshot a new baseline.
 *
 * `Customer A`, `Contract 182`, `Product X`: deliberately unnamed. A plausible
 * company name in a demo is the first step toward a fabricated case study.
 */

export const DEMO_COLLECTION_ID = "col_sample_0001";
export const DEMO_WORLD_STATE_ID = "ws_sample_0001";

/** One fixed instant so replays are identical. */
const EPOCH = Date.parse("2026-08-11T09:00:00.000Z");

/* ── Entities ────────────────────────────────────────────────────────────── */

export type EntityKind =
  | "customer"
  | "contract"
  | "product"
  | "policy"
  | "region"
  | "document";

export interface DemoEntity {
  id: string;
  kind: EntityKind;
  label: string;
  /**
   * Position in the world's own 1000 × 620 coordinate space.
   *
   * Hand-placed rather than force-directed: a force layout re-runs on every
   * mount, and §12.5 forbids curve-happy graphs and edges without a basis.
   * Fixed coordinates also mean the SVG renders identically on the server.
   */
  x: number;
  y: number;
  /** Order of appearance in the WORLD reveal. Lower emerges first. */
  beat: number;
  /**
   * Which file on screen this came out of, as an index into `MESS_FILES`.
   *
   * The WORLD act opens on the same nine files the hero shows and then
   * decomposes them, so every entity needs a birthplace to travel from. Making
   * it an index rather than a coordinate keeps the two layouts independent:
   * move a card and the entity still emerges from the right one.
   */
  originIndex: number;
}

export const DEMO_ENTITIES: readonly DemoEntity[] = [
  { id: "e_customer_a", kind: "customer", label: "Customer A", x: 96, y: 318, beat: 0, originIndex: 4 },
  { id: "e_contract_182", kind: "contract", label: "Contract 182", x: 268, y: 318, beat: 1, originIndex: 4 },
  { id: "e_product_x", kind: "product", label: "Product X", x: 452, y: 318, beat: 2, originIndex: 5 },
  { id: "e_policy_warranty", kind: "policy", label: "Warranty Policy", x: 648, y: 318, beat: 3, originIndex: 2 },
  { id: "e_region_kr", kind: "region", label: "Korea", x: 856, y: 318, beat: 4, originIndex: 2 },

  { id: "e_doc_contract_a", kind: "document", label: "Customer A contract", x: 292, y: 146, beat: 6, originIndex: 4 },
  { id: "e_doc_manual_2024", kind: "document", label: "2024 service manual", x: 548, y: 128, beat: 5, originIndex: 3 },
  { id: "e_doc_policy_2026", kind: "document", label: "2026 warranty policy", x: 762, y: 150, beat: 5, originIndex: 2 },

  { id: "e_support_sla", kind: "policy", label: "Support SLA", x: 238, y: 494, beat: 7, originIndex: 7 },
  { id: "e_product_variant", kind: "product", label: "Model X-220", x: 452, y: 502, beat: 7, originIndex: 5 },
  { id: "e_distributor_kr", kind: "customer", label: "Distributor KR-01", x: 690, y: 486, beat: 8, originIndex: 6 },
  { id: "e_region_jp", kind: "region", label: "Japan", x: 890, y: 468, beat: 8, originIndex: 2 },
] as const;

/**
 * Where the nine files sit before anything is compiled — a 3 × 3 stack in the
 * same 1000 × 620 space the world uses, so one coordinate system carries both
 * halves of the scene and the morph is a `transform` rather than a crossfade.
 */
export const DOC_CARD = { w: 214, h: 46 } as const;

export const DOC_STACK: readonly { x: number; y: number }[] = [
  { x: 268, y: 132 }, { x: 500, y: 132 }, { x: 732, y: 132 },
  { x: 268, y: 232 }, { x: 500, y: 232 }, { x: 732, y: 232 },
  { x: 268, y: 332 }, { x: 500, y: 332 }, { x: 732, y: 332 },
] as const;

export interface DemoRelation {
  id: string;
  from: string;
  to: string;
  predicate: string;
  beat: number;
  /** The spine the copy names: Customer A → … → Korea. Drawn heavier. */
  spine?: boolean;
}

export const DEMO_RELATIONS: readonly DemoRelation[] = [
  { id: "r_holds", from: "e_customer_a", to: "e_contract_182", predicate: "holds", beat: 1, spine: true },
  { id: "r_covers", from: "e_contract_182", to: "e_product_x", predicate: "covers", beat: 2, spine: true },
  { id: "r_governed", from: "e_product_x", to: "e_policy_warranty", predicate: "governed by", beat: 3, spine: true },
  { id: "r_applies_kr", from: "e_policy_warranty", to: "e_region_kr", predicate: "applies in", beat: 4, spine: true },

  { id: "r_states_2024", from: "e_doc_manual_2024", to: "e_policy_warranty", predicate: "states", beat: 5 },
  { id: "r_states_2026", from: "e_doc_policy_2026", to: "e_policy_warranty", predicate: "states", beat: 5 },
  { id: "r_overrides", from: "e_doc_contract_a", to: "e_policy_warranty", predicate: "overrides for", beat: 6 },
  { id: "r_evidences", from: "e_doc_contract_a", to: "e_contract_182", predicate: "evidences", beat: 6 },

  { id: "r_includes", from: "e_contract_182", to: "e_support_sla", predicate: "includes", beat: 7 },
  { id: "r_variant", from: "e_product_x", to: "e_product_variant", predicate: "has variant", beat: 7 },
  { id: "r_distributes", from: "e_distributor_kr", to: "e_product_x", predicate: "distributes", beat: 8 },
  { id: "r_operates", from: "e_distributor_kr", to: "e_region_kr", predicate: "operates in", beat: 8 },
  { id: "r_applies_jp", from: "e_policy_warranty", to: "e_region_jp", predicate: "applies in", beat: 8 },
  { id: "r_located", from: "e_customer_a", to: "e_region_kr", predicate: "located in", beat: 8 },
] as const;

/* ── Knowledge units in conflict ─────────────────────────────────────────── */

export interface DemoKnowledgeUnit {
  id: string;
  subject: string;
  /** What the unit asserts, as the visitor reads it. */
  value: string;
  status: TemporalStatus;
  /** Why this unit won or lost. Never "it was the newest file". */
  basis: string;
  scope: string;
  effectiveFrom: string;
  source: SourceRefLite;
}

export const WARRANTY_SUBJECT = "Warranty term · Product X · Korea";

export const DEMO_UNITS: readonly DemoKnowledgeUnit[] = [
  {
    id: "u_warranty_2024",
    subject: WARRANTY_SUBJECT,
    value: "1 year",
    status: "SUPERSEDED",
    basis: "Replaced by a later statement from the same authority",
    scope: "All regions",
    effectiveFrom: "2024-03-01",
    source: {
      document_id: "d_manual_2024",
      document_label: "2024 service manual",
      page_number: 62,
      locator: "Section 9.1",
    },
  },
  {
    id: "u_warranty_2026",
    subject: WARRANTY_SUBJECT,
    value: "2 years",
    status: "ACTIVE",
    basis: "Current statement from the issuing authority",
    scope: "All regions · default",
    effectiveFrom: "2026-01-01",
    source: {
      document_id: "d_policy_2026",
      document_label: "2026 warranty policy",
      page_number: 17,
      locator: "Table 3",
      cell: "Cell B4",
    },
  },
  {
    id: "u_warranty_customer_a",
    subject: WARRANTY_SUBJECT,
    value: "3 years",
    status: "EXCEPTION",
    basis: "Narrower applicability scope than the active default",
    scope: "Customer A only",
    effectiveFrom: "2025-11-14",
    source: {
      document_id: "d_contract_a",
      document_label: "Customer A contract",
      page_number: 4,
      locator: "Clause 7.2",
    },
  },
] as const;

export const DEMO_RESOLUTION_BASIS: ResolutionBasis = "applicability";

/* ── The ASK exchange ────────────────────────────────────────────────────── */

export const DEMO_QUESTION = "What is the current warranty?";

export const DEMO_ANSWER = "2 years";

export interface DemoGuarantee {
  label: string;
  held: boolean;
  because: string;
}

export const DEMO_GUARANTEES: readonly DemoGuarantee[] = [
  {
    label: "Current",
    held: true,
    because: "The 2024 statement is superseded and was not read.",
  },
  {
    label: "Official",
    held: true,
    because: "The 2026 policy is the issuing authority for this subject.",
  },
  {
    label: "Applicable",
    held: true,
    because:
      "No customer scope was given, so the Customer A exception does not apply.",
  },
  {
    label: "Evidence-backed",
    held: true,
    because: "Page 17 · Table 3 · Cell B4 of the 2026 warranty policy.",
  },
] as const;

/**
 * The last rung of the zoom-back: the table the answer actually came from.
 *
 * Rendered as a real `<table>` with the cited cell marked, which is the point
 * of the ladder — the path has to end somewhere a person can look. §12.4 is
 * blunt that a DOM table rendered under an "Original" heading is a reject:
 * this one is labelled a reconstruction of a synthetic source, never a scan.
 */
export interface DemoSourceTable {
  caption: string;
  columns: readonly string[];
  rows: readonly { ref: string; cells: readonly string[] }[];
  citedRowRef: string;
  citedColumnIndex: number;
}

/**
 * The cited table as of a given document revision.
 *
 * The cell the answer came from has to read what the world currently says. A
 * visitor who revises the term to five years and then follows the answer home
 * must land on a cell containing five years — a provenance path that arrives
 * at the *old* value has disproved itself on the way down.
 */
export function sourceTableFor(term: string, revision = 1): DemoSourceTable {
  return {
    caption: `2026 warranty policy · rev ${revision} · Page 17 · Table 3 — Coverage by product line`,
    columns: ["A · Product line", "B · Warranty term", "C · Region"],
    rows: [
      { ref: "2", cells: ["Product W", "1 year", "Global"] },
      { ref: "3", cells: ["Product V", "2 years", "Global"] },
      { ref: "4", cells: ["Product X", term, "Korea"] },
      { ref: "5", cells: ["Product Y", "3 years", "Global"] },
    ],
    citedRowRef: "4",
    citedColumnIndex: 1,
  };
}

/** The table at revision 1, which is what the page shows before any change. */
export const DEMO_SOURCE_TABLE = sourceTableFor(DEMO_ANSWER, 1);

/**
 * The zoom-back path, from the answer down to the cell that produced it.
 *
 * `Document revision` is a rung of its own because the document is no longer
 * a single fixed thing once the CHANGE act can revise it. Naming the revision
 * on the way down is what distinguishes "this is where the value lives" from
 * "this is where the value lived when the page loaded".
 */
export function traceFor(revision = 1): readonly string[] {
  return [
    "Answer",
    "Claim",
    "Knowledge Unit",
    "Document",
    `Document revision ${revision}`,
    "Page 17",
    "Table 3",
    "Cell B4",
  ];
}

export const DEMO_TRACE: readonly string[] = traceFor(1);

/**
 * The page the zoom-back lands on, as geometry.
 *
 * Enough of a page to fly into: a header band, body paragraphs, and the table
 * at real coordinates with the cited cell where the `SourceRef` says it is.
 * The rungs below are camera stops — each one frames a rectangle, and the
 * transform between two stops is the zoom.
 *
 * Schematic, and labelled as such wherever it renders. §12.4 rejects a DOM
 * table presented as an original scan; this is a synthetic source drawn from
 * the fixture and never claims otherwise.
 */
export const SOURCE_PAGE = { w: 560, h: 720 } as const;

export const SOURCE_PAGE_BLOCKS: readonly {
  x: number;
  y: number;
  w: number;
  h: number;
  kind: "heading" | "text" | "caption";
}[] = [
  { x: 56, y: 54, w: 300, h: 16, kind: "heading" },
  { x: 56, y: 96, w: 448, h: 7, kind: "text" },
  { x: 56, y: 112, w: 448, h: 7, kind: "text" },
  { x: 56, y: 128, w: 372, h: 7, kind: "text" },
  { x: 56, y: 168, w: 210, h: 11, kind: "caption" },
  { x: 56, y: 470, w: 448, h: 7, kind: "text" },
  { x: 56, y: 486, w: 448, h: 7, kind: "text" },
  { x: 56, y: 502, w: 316, h: 7, kind: "text" },
] as const;

/** Table 3 on the page, in page coordinates. */
export const SOURCE_PAGE_TABLE = {
  x: 56,
  y: 196,
  w: 448,
  h: 240,
  cols: 3,
  rows: 5,
  /** 0-based within the body rows, matching `DEMO_SOURCE_TABLE`. */
  citedRow: 2,
  citedCol: 1,
} as const;

/**
 * Camera stops, one per rung of `DEMO_TRACE`.
 *
 * Each is a rectangle in page coordinates; the renderer scales it to fill the
 * frame. The first is the whole page, the last is one cell — which is what
 * makes the descent read as a zoom rather than a list.
 */
export const TRACE_STOPS: readonly { x: number; y: number; w: number; h: number }[] = (() => {
  const cellW = SOURCE_PAGE_TABLE.w / SOURCE_PAGE_TABLE.cols;
  const rowH = SOURCE_PAGE_TABLE.h / SOURCE_PAGE_TABLE.rows;
  const cell = {
    x: SOURCE_PAGE_TABLE.x + cellW * SOURCE_PAGE_TABLE.citedCol,
    // +1 skips the header row.
    y: SOURCE_PAGE_TABLE.y + rowH * (SOURCE_PAGE_TABLE.citedRow + 1),
    w: cellW,
    h: rowH,
  };
  const whole = { x: 0, y: 0, w: SOURCE_PAGE.w, h: SOURCE_PAGE.h };
  return [
    whole, // Answer
    whole, // Claim
    { x: 24, y: 140, w: SOURCE_PAGE.w - 48, h: 360 }, // Knowledge Unit
    { x: 12, y: 20, w: SOURCE_PAGE.w - 24, h: 560 }, // Document
    // Document revision — the same sheet, framed one step tighter, because the
    // revision is a property of this document rather than a different page.
    { x: 20, y: 40, w: SOURCE_PAGE.w - 40, h: 520 },
    { x: 32, y: 150, w: SOURCE_PAGE.w - 64, h: 330 }, // Page 17
    {
      x: SOURCE_PAGE_TABLE.x - 16,
      y: SOURCE_PAGE_TABLE.y - 24,
      w: SOURCE_PAGE_TABLE.w + 32,
      h: SOURCE_PAGE_TABLE.h + 40,
    }, // Table 3
    { x: cell.x - 14, y: cell.y - 14, w: cell.w + 28, h: cell.h + 28 }, // Cell B4
  ];
})();

/* ── The CHANGE the visitor can make ─────────────────────────────────────── */

export const DEMO_CHANGE_OPTIONS = ["2 years", "3 years", "5 years"] as const;
export type DemoChangeOption = (typeof DEMO_CHANGE_OPTIONS)[number];

/**
 * Impact of editing the 2026 policy term.
 *
 * `worldUnitsTotal` is the denominator the recompile counter needs: the point
 * of WOW #3 is that 7 units move and 12,834 do not. Both numbers are fixture.
 */
export const DEMO_IMPACT = {
  changeId: "chg_sample_0001",
  changedUnitId: "u_warranty_2026",
  sourcesChanged: 1,
  knowledgeUnitsAffected: 7,
  agentContextsStale: 3,
  retrievalPackagesInvalidated: 2,
  worldUnitsTotal: 12841,
} as const;

/**
 * The blast radius, by layer.
 *
 * A number in a `<dl>` says seven units moved. It does not say *why* those
 * seven, and the point of incremental recompilation is the chain — one cell
 * changes, one claim changes, seven units depend on that claim, two retrieval
 * packages embed those units, three agent contexts were built from those
 * packages. So the cascade is data, and the counts below are exactly the
 * `impact.detected.v1` payload rather than a second set of figures.
 */
export type ImpactLayer =
  | "SOURCE"
  | "CLAIM"
  | "KNOWLEDGE"
  | "RETRIEVAL"
  | "AGENT";

export const IMPACT_LAYERS: readonly {
  layer: ImpactLayer;
  caption: string;
  items: readonly { id: string; label: string }[];
}[] = [
  {
    layer: "SOURCE",
    caption: "the cell that changed",
    items: [{ id: "src_policy_b4", label: "2026 warranty policy · p.17 · Table 3 · B4" }],
  },
  {
    layer: "CLAIM",
    caption: "what it asserted",
    items: [{ id: "clm_warranty_term", label: "Warranty term · Product X · Korea" }],
  },
  {
    layer: "KNOWLEDGE",
    caption: "units that read that claim",
    items: [
      { id: "u_warranty_2026", label: "Warranty term · default" },
      { id: "u_warranty_kr", label: "Warranty term · Korea" },
      { id: "u_warranty_jp", label: "Warranty term · Japan" },
      { id: "u_product_x_terms", label: "Product X · coverage summary" },
      { id: "u_variant_terms", label: "Model X-220 · coverage summary" },
      { id: "u_contract_182_terms", label: "Contract 182 · effective terms" },
      { id: "u_sla_alignment", label: "Support SLA · alignment note" },
    ],
  },
  {
    layer: "RETRIEVAL",
    caption: "packages that embedded them",
    items: [
      { id: "pkg_support_kb", label: "Support knowledge base · ko-KR" },
      { id: "pkg_sales_terms", label: "Sales terms pack · APAC" },
    ],
  },
  {
    layer: "AGENT",
    // Rendered copy, so it follows the public wording rather than the payload
    // key (`agent_contexts_stale`) that supplies its count.
    caption: "contexts built from them",
    items: [
      { id: "ctx_support_agent", label: "Support agent" },
      { id: "ctx_renewals_agent", label: "Renewals agent" },
      { id: "ctx_field_service", label: "Field service assistant" },
    ],
  },
] as const;

/** The seven units that actually move, so the counter names each one. */
export const DEMO_AFFECTED_UNITS: readonly { id: string; label: string; entityId: string }[] = [
  { id: "u_warranty_2026", label: "Warranty term · default", entityId: "e_policy_warranty" },
  { id: "u_warranty_kr", label: "Warranty term · Korea", entityId: "e_region_kr" },
  { id: "u_warranty_jp", label: "Warranty term · Japan", entityId: "e_region_jp" },
  { id: "u_product_x_terms", label: "Product X · coverage summary", entityId: "e_product_x" },
  { id: "u_variant_terms", label: "Model X-220 · coverage summary", entityId: "e_product_variant" },
  { id: "u_contract_182_terms", label: "Contract 182 · effective terms", entityId: "e_contract_182" },
  { id: "u_sla_alignment", label: "Support SLA · alignment note", entityId: "e_support_sla" },
] as const;

/* ── MESS — what the workspace looks like before anything is compiled ────── */

export interface MessFile {
  name: string;
  kind: string;
  size: string;
  modified: string;
  /** What the profiler will later say about it. Empty before compilation. */
  note?: string;
  lang?: "ko";
}

/**
 * The hero's document objects.
 *
 * These are rows, not rectangles. §21 [확정] requires marketing visuals to be
 * made of real product surfaces, and the previous landing illustrated
 * "fragmented documents" with four empty white boxes — which reads as a failed
 * image load, not as a mess. A filename with a `(1)` in it and a `FINAL_v3`
 * beside a `FINAL_v4` is the actual shape of the problem, and it is also where
 * the 27 revision families and 83 duplicates in the stream come from.
 */
export const MESS_FILES: readonly MessFile[] = [
  { name: "warranty_policy_FINAL_v3.pdf", kind: "PDF", size: "2.4 MB", modified: "2026-01-08" },
  { name: "Copy of warranty_policy_FINAL_v3.pdf", kind: "PDF", size: "2.4 MB", modified: "2026-01-11" },
  { name: "warranty_policy_FINAL_v4 (1).pdf", kind: "PDF", size: "2.6 MB", modified: "2026-02-02" },
  { name: "2024 서비스 매뉴얼_scan.pdf", kind: "Scan", size: "48.1 MB", modified: "2024-03-04", lang: "ko" },
  { name: "Contract_182_signed.pdf", kind: "PDF", size: "1.1 MB", modified: "2025-11-14" },
  { name: "Product X spec sheet.xlsx", kind: "Sheet", size: "820 KB", modified: "2025-06-21" },
  { name: "IMG_4471.HEIC", kind: "Photo", size: "3.9 MB", modified: "2025-09-30" },
  { name: "support_sla_draft.docx", kind: "Doc", size: "142 KB", modified: "2025-08-02" },
  { name: "무제 문서.pdf", kind: "PDF", size: "704 KB", modified: "2026-04-17", lang: "ko" },
] as const;

/* ── The processing stream ───────────────────────────────────────────────── */

export const DEMO_DISCOVERY = {
  filesDiscovered: 4821,
  revisionFamilies: 27,
  duplicates: 83,
  complexTables: 413,
  deepInspectionPage: 147,
} as const;

/**
 * One scheduled event.
 *
 * Timing lives beside the event rather than inside it: `occurred_at` is what
 * the wire carries, `atMs` is what the demo scheduler uses. A live source has
 * no schedule — the network is its schedule — which is the asymmetry that
 * keeps `ProductEventSource` honest.
 */
export interface ScheduledEvent {
  atMs: number;
  event: ProductEvent;
}

/**
 * The half of an event a fixture entry has to supply.
 *
 * Written as a distributive conditional rather than `Omit<ProductEvent, …>`:
 * `Omit` is not distributive over a union, so it would collapse twenty
 * variants into one loose shape where any payload could sit under any
 * `event_type`. That would defeat the point of typing the fixture at all —
 * the reason it is typed is so that a payload that does not match its event
 * fails here rather than at parse time in a browser.
 */
type Draft<T = ProductEvent> = T extends ProductEvent
  ? Pick<T, "event_type" | "payload"> &
      Partial<Pick<T, "document_id" | "page_number">>
  : never;

function build(entries: readonly { atMs: number; draft: Draft }[]): ScheduledEvent[] {
  /*
   * Sequence follows delivery time, not array position.
   *
   * This is not tidiness. The projection drops any event at or below
   * `lastSequence` — correct, because delivery is at-least-once — so an event
   * that is scheduled early but numbered late silently swallows everything
   * numbered before it. The entity and relation blocks below are written as
   * two `.map()`s whose `atMs` ranges overlap, which produced exactly that:
   * eleven of twelve entities vanished, and only a timed run showed it,
   * because reducing the array in order hides the problem completely.
   *
   * Sorting here means a fixture author can write the beats in whatever order
   * reads best and still get a monotonic stream.
   */
  const ordered = [...entries].sort((a, b) => a.atMs - b.atMs);
  return ordered.map((entry, index) => ({
    atMs: entry.atMs,
    event: {
      schema_version: "1.0",
      event_id: `evt_sample_${String(index + 1).padStart(4, "0")}`,
      sequence: index + 1,
      occurred_at: new Date(EPOCH + entry.atMs).toISOString(),
    // Ordered above, so sequence and occurred_at never disagree.
      // Pure fixture data, not impersonating either real backend plane — the
      // legacy top-level `collection_id` is intentionally not set here.
      // `parseProductEvent`'s I2 normalization strips it for any non-
      // `"collection"` scope, so setting it would only be overwritten.
      mode: "demo",
      scope: { kind: "demo" },
      ...entry.draft,
    } as ProductEvent,
  }));
}

/**
 * MESS → DISCOVER → ROUTE → RECOVER → WORLD.
 *
 * The stream stops at `world_state.activated.v1`. Everything after that is
 * driven by the visitor — TRUTH is a resolution they watch, CHANGE is an edit
 * they make, ASK is a question they send — so replaying those on a timer would
 * be the fake progress §11.1 calls out.
 */
export const DEMO_COMPILE_STREAM: readonly ScheduledEvent[] = build([
  { atMs: 0, draft: { event_type: "collection.discovery.progress.v1", payload: { discovered_files: 1207 } } },
  // Named files, so the stream says what it found and not only how many. The
  // three chosen are the ones the rest of the story turns on.
  { atMs: 210, draft: { event_type: "file.discovered.v1", payload: { file_name: "warranty_policy_FINAL_v4 (1).pdf", sha256_prefix: "9f2c41" } } },
  { atMs: 340, draft: { event_type: "file.discovered.v1", payload: { file_name: "Contract_182_signed.pdf", sha256_prefix: "c07ab8" } } },
  { atMs: 470, draft: { event_type: "file.discovered.v1", payload: { file_name: "2024 서비스 매뉴얼_scan.pdf", sha256_prefix: "41de60" } } },
  { atMs: 620, draft: { event_type: "collection.discovery.progress.v1", payload: { discovered_files: 3164 } } },
  { atMs: 900, draft: { event_type: "collection.discovery.progress.v1", payload: { discovered_files: DEMO_DISCOVERY.filesDiscovered } } },
  { atMs: 1280, draft: { event_type: "revision.family.detected.v1", payload: { families_total: DEMO_DISCOVERY.revisionFamilies, confidence: "probable" } } },
  { atMs: 1700, draft: { event_type: "file.duplicate.detected.v1", payload: { duplicates_total: DEMO_DISCOVERY.duplicates } } },
  { atMs: 2160, draft: { event_type: "document.profiled.v1", payload: { documents_profiled: 4738, complex_tables_total: DEMO_DISCOVERY.complexTables } } },
  {
    atMs: 2640,
    draft: {
      event_type: "page.route.selected.v1",
      document_id: "d_policy_2026",
      page_number: DEMO_DISCOVERY.deepInspectionPage,
      payload: { lane: "FAST", attempt: 1, reason: "Native text layer present" },
    },
  },
  {
    atMs: 3080,
    draft: {
      event_type: "verification.failed.v1",
      document_id: "d_policy_2026",
      page_number: DEMO_DISCOVERY.deepInspectionPage,
      payload: {
        finding_code: "table.row_total_mismatch",
        detail: "Reconstructed table totals do not match the printed total",
      },
    },
  },
  {
    atMs: 3480,
    draft: {
      event_type: "document.rerouted.v1",
      document_id: "d_policy_2026",
      page_number: DEMO_DISCOVERY.deepInspectionPage,
      payload: { from_lane: "FAST", to_lane: "PRECISION", attempt: 2 },
    },
  },
  {
    atMs: 4160,
    draft: {
      event_type: "recovery.completed.v1",
      document_id: "d_policy_2026",
      page_number: DEMO_DISCOVERY.deepInspectionPage,
      payload: { attempt: 2, verified: true },
    },
  },
  ...DEMO_ENTITIES.map((entity, index) => ({
    atMs: 4700 + index * 130,
    draft: {
      event_type: "entity.resolved.v1" as const,
      payload: { entity_id: entity.id, entity_type: entity.kind, label: entity.label },
    },
  })),
  ...DEMO_RELATIONS.map((relation, index) => ({
    atMs: 4820 + index * 110,
    draft: {
      event_type: "relation.created.v1" as const,
      payload: {
        relation_id: relation.id,
        from_entity_id: relation.from,
        to_entity_id: relation.to,
        predicate: relation.predicate,
      },
    },
  })),
  ...DEMO_UNITS.map((unit, index) => ({
    atMs: 6500 + index * 160,
    draft: {
      event_type: "knowledge.unit.created.v1" as const,
      document_id: unit.source.document_id,
      page_number: unit.source.page_number,
      payload: {
        unit_id: unit.id,
        title: `${unit.subject} — ${unit.value}`,
        source_ref: unit.source,
      },
    },
  })),
  // The conflict is found and settled *before* the world activates — a world
  // state that goes ACTIVE with an unresolved conflict in it is the partial
  // publish CLAUDE.md forbids. TRUTH replays these two on its own source.
  {
    atMs: 6900,
    draft: {
      event_type: "conflict.detected.v1",
      payload: {
        conflict_id: "cfl_sample_0001",
        subject: WARRANTY_SUBJECT,
        candidate_unit_ids: DEMO_UNITS.map((unit) => unit.id),
      },
    },
  },
  {
    atMs: 7180,
    draft: {
      event_type: "authority.resolved.v1",
      payload: {
        conflict_id: "cfl_sample_0001",
        winner_unit_id: "u_warranty_2026",
        basis: DEMO_RESOLUTION_BASIS,
        outcomes: DEMO_UNITS.map((unit) => ({ unit_id: unit.id, status: unit.status })),
      },
    },
  },
  {
    atMs: 7500,
    draft: {
      event_type: "world_state.activated.v1",
      payload: {
        // Revision 1, and the first activation of the session, so it replaces
        // nothing. Written from the module-level constants rather than from
        // `DEMO_INITIAL_WORLD`: this array is built at module load and that
        // object is declared further down the file.
        world_state_id: DEMO_WORLD_STATE_ID,
        revision: 1,
        entities: DEMO_ENTITIES.length,
        relations: DEMO_RELATIONS.length,
        knowledge_units: DEMO_IMPACT.worldUnitsTotal,
      },
    },
  },
]);

/** TRUTH — replayed when the visitor reaches the resolution, not on a timer. */
export const DEMO_TRUTH_STREAM: readonly ScheduledEvent[] = build([
  {
    atMs: 0,
    draft: {
      event_type: "conflict.detected.v1",
      payload: {
        conflict_id: "cfl_sample_0001",
        subject: WARRANTY_SUBJECT,
        candidate_unit_ids: DEMO_UNITS.map((unit) => unit.id),
      },
    },
  },
  {
    atMs: 900,
    draft: {
      event_type: "authority.resolved.v1",
      payload: {
        conflict_id: "cfl_sample_0001",
        winner_unit_id: "u_warranty_2026",
        basis: DEMO_RESOLUTION_BASIS,
        outcomes: DEMO_UNITS.map((unit) => ({ unit_id: unit.id, status: unit.status })),
      },
    },
  },
]);

/**
 * The world the page is currently answering from.
 *
 * The demo is one state machine — `change → impact → activation → ask →
 * evidence` — so the chosen value cannot stay local to the CHANGE act. It
 * revises a source, the revision activates a new world state, and every act
 * downstream reads that state. A visitor who sets five years and then asks the
 * world must be told five years; anything else is a page arguing against its
 * own headline.
 *
 * The state it replaced is kept rather than discarded. `previous` is what
 * makes activation a transition that can be read both ways, and it is the
 * reason the original two-year world is still addressable after a change.
 */
export interface DemoWorldState {
  id: string;
  revision: number;
  /** The warranty term this world resolves to. */
  term: string;
  previous: { id: string; revision: number; term: string } | undefined;
}

export const DEMO_INITIAL_WORLD: DemoWorldState = {
  id: DEMO_WORLD_STATE_ID,
  revision: 1,
  term: DEMO_ANSWER,
  previous: undefined,
};

/** The state a source revision to `term` activates, given the current one. */
export function nextWorldState(
  current: DemoWorldState,
  term: string,
): DemoWorldState {
  const revision = current.revision + 1;
  return {
    id: `ws_sample_${String(revision).padStart(4, "0")}`,
    revision,
    term,
    previous: { id: current.id, revision: current.revision, term: current.term },
  };
}

/**
 * CHANGE — source revision, impact, recompilation, activation.
 *
 * The recompile emits one progress event per affected unit and stops. It does
 * not sweep to 100% of the world, because not updating the whole world is the
 * entire claim of this act.
 *
 * It ends on `world_state.activated.v1` rather than on the last unit: the
 * units are recompiled *into* a world state, and until that state is active
 * nothing downstream should be answering from it.
 */
export function buildChangeStream(
  from: DemoWorldState,
  to: DemoWorldState,
): ScheduledEvent[] {
  return build([
    {
      atMs: 0,
      draft: {
        event_type: "source.revision.created.v1",
        document_id: "d_policy_2026",
        page_number: 17,
        payload: {
          change_id: DEMO_IMPACT.changeId,
          document_id: "d_policy_2026",
          revision: to.revision,
          previous_revision: from.revision,
          locator: "Table 3",
          cell: "Cell B4",
          previous_value: from.term,
          new_value: to.term,
        },
      },
    },
    {
      atMs: 240,
      draft: {
        event_type: "impact.detected.v1",
        payload: {
          change_id: DEMO_IMPACT.changeId,
          changed_unit_id: DEMO_IMPACT.changedUnitId,
          sources_changed: DEMO_IMPACT.sourcesChanged,
          knowledge_units_affected: DEMO_IMPACT.knowledgeUnitsAffected,
          agent_contexts_stale: DEMO_IMPACT.agentContextsStale,
          retrieval_packages_invalidated: DEMO_IMPACT.retrievalPackagesInvalidated,
        },
      },
    },
    ...DEMO_AFFECTED_UNITS.map((unit, index) => ({
      atMs: 620 + index * 300,
      draft: {
        event_type: "recompile.progress.v1" as const,
        payload: {
          change_id: DEMO_IMPACT.changeId,
          recompiled: index + 1,
          scheduled: DEMO_AFFECTED_UNITS.length,
          world_units_total: DEMO_IMPACT.worldUnitsTotal,
          unit_id: unit.id,
        },
      },
    })),
    {
      atMs: 620 + DEMO_AFFECTED_UNITS.length * 300 + 240,
      draft: {
        event_type: "recompile.completed.v1",
        payload: {
          change_id: DEMO_IMPACT.changeId,
          recompiled: DEMO_AFFECTED_UNITS.length,
          world_units_total: DEMO_IMPACT.worldUnitsTotal,
        },
      },
    },
    {
      atMs: 620 + DEMO_AFFECTED_UNITS.length * 300 + 520,
      draft: {
        event_type: "world_state.activated.v1",
        payload: {
          world_state_id: to.id,
          revision: to.revision,
          previous_world_state_id: from.id,
          entities: DEMO_ENTITIES.length,
          relations: DEMO_RELATIONS.length,
          knowledge_units: DEMO_IMPACT.worldUnitsTotal,
        },
      },
    },
  ]);
}

/**
 * ASK — the resolution the visitor watches while the answer streams.
 *
 * Answered against the world state that is active *now*, not against the one
 * the page loaded with. `world` is threaded from `CinematicStage`, which is
 * the only thing holding the two acts to the same state machine.
 */
export function buildAskStream(
  world: DemoWorldState = DEMO_INITIAL_WORLD,
): ScheduledEvent[] {
  return build([
    {
      atMs: 0,
      draft: {
        event_type: "answer.resolution.started.v1",
        payload: { question_id: "q_sample_0001", question: DEMO_QUESTION },
      },
    },
    ...DEMO_UNITS.map((unit, index) => ({
      atMs: 520 + index * 560,
      draft: {
        event_type: "answer.source.resolved.v1" as const,
        document_id: unit.source.document_id,
        payload: {
          question_id: "q_sample_0001",
          document_label: unit.source.document_label,
          status: unit.status,
        },
      },
    })),
    {
      atMs: 520 + DEMO_UNITS.length * 560 + 320,
      draft: {
        event_type: "answer.emitted.v1",
        document_id: "d_policy_2026",
        page_number: 17,
        payload: {
          question_id: "q_sample_0001",
          answer: world.term,
          guarantees: DEMO_GUARANTEES.map((guarantee) => ({ ...guarantee })),
          trace: [...traceFor(world.revision)],
          source_ref: DEMO_UNITS[1]!.source,
        },
      },
    },
  ]);
}
