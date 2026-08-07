import { FacingPages } from "@/components/facing/facing-pages";
import { bboxStyle } from "@/lib/bbox";
import type { ThreadAnchor } from "@/lib/facing/thread";

/**
 * Hero static comps — DESIGN_MASTER_V3 §12.2, W1.
 *
 * Three variations for the owner to rank, and one gate decision each. §12.2
 * fixes the concept (facing pages) and varies only the composition, so this
 * file holds one frame and three arrangements of it rather than three designs.
 *
 * This is a COMP, not the shipped hero. §24.1 forbids hero implementation code
 * before one of these is approved, so nothing here is wired: the drop zone is
 * drawn in its resting state, and W2 builds the working affordance from
 * whichever variant wins.
 *
 * Copy is the §3.3 direction under test, passed in rather than hardcoded, so
 * the §25.1 blind test can put the same layout behind three headlines.
 */

export type HeroVariant = "frame" | "overlap" | "fullbleed";

export type HeroCopy = {
  id: "d1" | "d2" | "d3";
  headline: readonly string[]; // manual line breaks — §7.4 forbids reflowing these
  lead: string;
};

/** §3.3 — three directions, all at or under the §25.3 ten-word cap. */
export const HERO_COPY: Record<HeroCopy["id"], HeroCopy> = {
  d1: {
    id: "d1",
    headline: ["Every output returns", "to its source."],
    lead: "Documents become structured, verified knowledge that people and AI can reuse — with every value traceable to the page it came from.",
  },
  d2: {
    id: "d2",
    headline: ["Nothing enters your", "knowledge unverified."],
    lead: "Every value is checked against the source page before it reaches your knowledge base. What fails verification stays visible, not hidden.",
  },
  d3: {
    id: "d3",
    headline: ["Scattered documents,", "one verified knowledge base."],
    lead: "Compile files, folders, and batches into structured knowledge with the evidence for every claim attached.",
  },
};

/**
 * The evidence anchors are the real bboxes from the frozen fixture in
 * demo-data.ts, not values chosen to make the curve look good. §4.4 means a
 * comp that cannot source its coordinates has to ship with none.
 */
const ANCHORS: readonly ThreadAnchor[] = [
  {
    id: "thread-title",
    bbox: [112, 94, 882, 158],
    targetY: 0.16,
    label: "Title block",
    state: "verified",
  },
  {
    id: "thread-table",
    bbox: [112, 402, 888, 644],
    targetY: 0.72,
    label: "Table 3, evidence fidelity",
    state: "review",
  },
];

export function HeroComp({
  variant,
  copy,
}: {
  variant: HeroVariant;
  copy: HeroCopy;
}) {
  return (
    <section className="tv-hero-comp" data-variant={variant}>
      <div className="tv-hero-comp-copy">
        <p className="tv-hero-comp-eyebrow">The Knowledge Compiler</p>
        <h1>
          {copy.headline.map((line, index) => (
            <span key={line}>
              {line}
              {index < copy.headline.length - 1 && <br />}
            </span>
          ))}
        </h1>
        <p className="tv-hero-comp-lead">{copy.lead}</p>

        {/* §3.4 — exactly two CTAs, different labels, primary once. */}
        <div className="tv-hero-comp-actions">
          <span className="tv-hero-comp-cta" data-kind="primary">
            Start compiling
          </span>
          <span className="tv-hero-comp-cta" data-kind="secondary">
            Inspect the proof
          </span>
        </div>

        <p className="tv-hero-comp-trust">
          Source-linked output · KO DART / US SEC · No unverified claims
        </p>
      </div>

      <div className="tv-hero-comp-stage">
        <FacingPages
          ratio="hero"
          sourcePageNumber={8}
          anchors={ANCHORS}
          meta={
            <>
              <span>Sample · Journal of Reliable AI Systems · Page 8</span>
              <span data-state="verified">Verified</span>
            </>
          }
          caption="Drop a document here to compile your own — sample shown"
          verso={<VersoPage />}
          recto={<RectoOutput />}
        />
      </div>
    </section>
  );
}

/**
 * The source side. §4.2 is explicit that the differentiator is not the facing
 * layout — Resend, Retool, and Cursor all have one — but the nature of the
 * left panel: a document page nobody here authored.
 *
 * The real thing needs PDF.js, which W4 introduces with the G-E coordinate
 * contract. Until then this reuses the page facsimile the product already
 * ships in source-viewer.tsx, carrying its own label so the comp never claims
 * to be showing a real filing. The bounding boxes are drawn at the exact
 * coordinates the threads start from, so what the curve connects is visible
 * rather than asserted.
 */
function VersoPage() {
  return (
    <div className="tv-hero-comp-page">
      <article className="tv-hero-comp-paper">
        <div className="tv-hero-comp-paper-head">
          SAMPLE · JOURNAL OF RELIABLE AI SYSTEMS
          <span>Demo document · not an actual source</span>
        </div>

        {PAGE_BLOCKS.map((block) => (
          <div
            key={block.id}
            className="tv-hero-comp-block"
            data-kind={block.kind}
            style={bboxStyle(block.bbox)}
          >
            {block.body}
          </div>
        ))}

        <span className="tv-hero-comp-paper-number">8</span>
      </article>

      {ANCHORS.map((anchor) =>
        anchor.bbox ? (
          <span
            key={anchor.id}
            className="tv-hero-comp-bbox"
            data-state={anchor.state}
            style={bboxStyle(anchor.bbox)}
            aria-hidden="true"
          />
        ) : null,
      )}
    </div>
  );
}

/**
 * The page blocks, laid out at their stored bbox1000 coordinates rather than in
 * document flow.
 *
 * This matters: a facsimile that flows freely would put its table somewhere
 * other than the coordinates the fixture records, so the highlight over "Table
 * 3" would sit on a paragraph — a thread pointing at the wrong thing, which is
 * the failure §4.4 exists to prevent, one level down. Placing the blocks from
 * the same numbers the threads read makes the page and the coordinate contract
 * agree by construction.
 */
const PAGE_BLOCKS = [
  {
    id: "blk_title",
    kind: "title" as const,
    bbox: [112, 94, 882, 158] as const,
    body: "Evaluating evidence fidelity in retrieval-augmented generation",
  },
  {
    id: "blk_heading",
    kind: "heading" as const,
    bbox: [106, 194, 452, 240] as const,
    body: "4.2 Experimental results",
  },
  {
    id: "blk_paragraph",
    kind: "paragraph" as const,
    bbox: [108, 258, 892, 364] as const,
    body: "This content is a UI validation sample. Production mode displays only the API-issued source preview and the stored bounding boxes.",
  },
  {
    id: "blk_table",
    kind: "table" as const,
    bbox: [112, 402, 888, 644] as const,
    body: (
      <table>
        <caption>Table 3. Sample comparison</caption>
        <thead>
          <tr>
            <th>Configuration</th>
            <th>Evidence fidelity</th>
            <th>Unsupported claim</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Baseline</td>
            <td>0.86</td>
            <td>3.8%</td>
          </tr>
          <tr>
            <td>Verification enabled</td>
            <td>0.94</td>
            <td>1.1%</td>
          </tr>
        </tbody>
      </table>
    ),
  },
].map((block) => ({ ...block, bbox: [...block.bbox] as [number, number, number, number] }));

/**
 * The knowledge side. Real product vocabulary — typed blocks, a source
 * reference, a review flag. §25.7 rejects a DOM-rewritten table presented as
 * the source; this is explicitly labelled as the output.
 */
function RectoOutput() {
  return (
    <div className="tv-hero-comp-output">
      <div className="tv-hero-comp-row" data-kind="title">
        <span className="tv-hero-comp-tag">Title</span>
        <strong>Evaluating Evidence Fidelity in Retrieval-Augmented Generation</strong>
        <span className="tv-hero-comp-ref">p.8 · 112, 94, 882, 158</span>
      </div>

      <div className="tv-hero-comp-row" data-kind="heading">
        <span className="tv-hero-comp-tag">Heading</span>
        <strong>4.2 Experimental Results</strong>
      </div>

      <div className="tv-hero-comp-row" data-kind="table" data-state="review">
        <span className="tv-hero-comp-tag">Table</span>
        <table>
          <thead>
            <tr>
              <th>Configuration</th>
              <th>Evidence fidelity</th>
              <th>Unsupported claims</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Baseline</td>
              <td>0.86</td>
              <td>3.8%</td>
            </tr>
            <tr>
              <td>Verification enabled</td>
              <td>0.94</td>
              <td>1.1%</td>
            </tr>
          </tbody>
        </table>
        <span className="tv-hero-comp-ref" data-state="review">
          p.8 · numeric cross-check required
        </span>
      </div>
    </div>
  );
}
