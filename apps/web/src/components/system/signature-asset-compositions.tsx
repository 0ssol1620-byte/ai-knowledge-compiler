import { DART_PUBLIC_FIXTURE } from "@/lib/dart-public-fixture";

import styles from "./signature-asset-compositions.module.css";

export type SignatureAssetId = "A01" | "A02" | "A03" | "A04" | "A05" | "A06";
export type CompositionDirection = "A" | "B" | "C";

type ManifestContract = {
  assetId: "A01";
  name: "Drop Everything";
  truthClass: "T1";
  collection_manifest_v1: {
    collectionId: string;
    files: Array<{ path: string; kind: string; state: string }>;
    duplicateCount: number;
  };
  signed_collection_preflight: {
    status: "available";
    outputSha256: string;
  };
};

type StructureContract = {
  assetId: "A02";
  name: "Source to Structure";
  truthClass: "T1";
  source: { id: string; page: number; bbox1000: [number, number, number, number]; text: string };
  canonical_blocks: Array<{
    id: string;
    type: "heading" | "paragraph" | "table" | "excluded_repeated_header";
    text: string;
    sourceRef: string;
  }>;
  processing_events: string[];
};

type ProofContract = {
  assetId: "A03";
  name: "Proof Link";
  truthClass: "T0";
  selectedResult: { label: string; value: string; unit: string; taxonomy: string };
  sourceTarget: { receiptNumber: string; sourceLine: number; sourceSha256: string };
  authority: { source: string; corporationCode: string; verified: true };
  qualityClaimEligible: false;
};

type ArchitectureContract = {
  assetId: "A04";
  name: "Knowledge Architecture";
  truthClass: "T1";
  architecture_plan: {
    planId: string;
    directories: Array<{ path: string; itemCount: number }>;
    mocs: string[];
    notes: Array<{ id: string; title: string; sourceRef: string }>;
    entities: string[];
    relations: Array<{ from: string; type: string; to: string; sourceRef: string }>;
  };
};

type GraphContract = {
  assetId: "A05";
  name: "Graph with Evidence";
  truthClass: "T0";
  entities: Array<{ id: string; label: string; type: string }>;
  typed_relations: Array<{ from: string; type: string; to: string; sourceRef: string }>;
  selectedRelation: string;
  verification_state: "authority_verified";
  source: { receiptNumber: string; sourceLine: number; archiveSha256: string };
};

type PackageContract = {
  assetId: "A06";
  name: "Deployable Package";
  truthClass: "T1";
  knowledge_package_manifest: {
    packageId: string;
    roots: Array<{ path: string; purpose: string; entries: number }>;
  };
  checksums_sha256: { status: "available"; manifestSha256: string };
  signature_status: "unavailable";
  round_trip_validation: "unavailable";
};

export type SignatureAssetContract =
  | ManifestContract
  | StructureContract
  | ProofContract
  | ArchitectureContract
  | GraphContract
  | PackageContract;

const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);
const revenue = DART_PUBLIC_FIXTURE.rows[0];

export const SIGNATURE_ASSET_CONTRACTS: Record<
  SignatureAssetId,
  SignatureAssetContract
> = {
  A01: {
    assetId: "A01",
    name: "Drop Everything",
    truthClass: "T1",
    collection_manifest_v1: {
      collectionId: "collection-reference-2026-07-30",
      files: [
        { path: "research/annual-report.pdf", kind: "PDF", state: "classified" },
        { path: "research/tables/revenue.xlsx", kind: "Spreadsheet", state: "classified" },
        { path: "research/archive/annual-report.pdf", kind: "PDF", state: "possible_duplicate" },
      ],
      duplicateCount: 1,
    },
    signed_collection_preflight: {
      status: "available",
      outputSha256: SHA_A,
    },
  },
  A02: {
    assetId: "A02",
    name: "Source to Structure",
    truthClass: "T1",
    source: {
      id: "annual-report-2025:p42",
      page: 42,
      bbox1000: [84, 112, 916, 824],
      text: "Revenue by operating segment — continued table and explanatory note.",
    },
    canonical_blocks: [
      { id: "b-001", type: "heading", text: "Revenue by operating segment", sourceRef: "annual-report-2025:p42#bbox84,112,916,168" },
      { id: "b-002", type: "excluded_repeated_header", text: "Annual Report 2025", sourceRef: "annual-report-2025:p42#bbox84,40,916,76" },
      { id: "b-003", type: "table", text: "Reconstructed 4 × 6 table", sourceRef: "annual-report-2025:p42#bbox84,190,916,654" },
      { id: "b-004", type: "paragraph", text: "Joined split paragraph with original reading order.", sourceRef: "annual-report-2025:p42#bbox84,680,916,824" },
    ],
    processing_events: ["block.completed.v1", "table.reconstructed.v1"],
  },
  A03: {
    assetId: "A03",
    name: "Proof Link",
    truthClass: "T0",
    selectedResult: {
      label: revenue.label,
      value: revenue.current,
      unit: DART_PUBLIC_FIXTURE.unit,
      taxonomy: revenue.taxonomy,
    },
    sourceTarget: {
      receiptNumber: DART_PUBLIC_FIXTURE.receiptNumber,
      sourceLine: revenue.sourceLine,
      sourceSha256: DART_PUBLIC_FIXTURE.sourceSha256,
    },
    authority: {
      source: DART_PUBLIC_FIXTURE.source,
      corporationCode: DART_PUBLIC_FIXTURE.corporationCode,
      verified: true,
    },
    qualityClaimEligible: false,
  },
  A04: {
    assetId: "A04",
    name: "Knowledge Architecture",
    truthClass: "T1",
    architecture_plan: {
      planId: "architecture-reference-v1",
      directories: [
        { path: "source/", itemCount: 3 },
        { path: "canonical/", itemCount: 4 },
        { path: "knowledge/mocs/", itemCount: 2 },
        { path: "knowledge/notes/", itemCount: 3 },
      ],
      mocs: ["MOC — Financial reporting", "MOC — Operating segments"],
      notes: [
        { id: "note-revenue", title: "Revenue — 2026 Q1", sourceRef: `OpenDART:${DART_PUBLIC_FIXTURE.receiptNumber}:L${revenue.sourceLine}` },
        { id: "note-gross-profit", title: "Gross profit — 2026 Q1", sourceRef: `OpenDART:${DART_PUBLIC_FIXTURE.receiptNumber}:L${DART_PUBLIC_FIXTURE.rows[2].sourceLine}` },
      ],
      entities: ["JTC", "2026 Q1", "Revenue"],
      relations: [
        { from: "JTC", type: "REPORTS", to: "Revenue", sourceRef: `OpenDART:${DART_PUBLIC_FIXTURE.receiptNumber}:L${revenue.sourceLine}` },
      ],
    },
  },
  A05: {
    assetId: "A05",
    name: "Graph with Evidence",
    truthClass: "T0",
    entities: [
      { id: "entity-jtc", label: "JTC", type: "Organization" },
      { id: "entity-revenue", label: "Revenue", type: "FinancialMetric" },
      { id: "entity-period", label: "2026 Q1", type: "ReportingPeriod" },
    ],
    typed_relations: [
      { from: "entity-jtc", type: "REPORTS", to: "entity-revenue", sourceRef: `OpenDART:${DART_PUBLIC_FIXTURE.receiptNumber}:L${revenue.sourceLine}` },
      { from: "entity-revenue", type: "FOR_PERIOD", to: "entity-period", sourceRef: `OpenDART:${DART_PUBLIC_FIXTURE.receiptNumber}:L${revenue.sourceLine}` },
    ],
    selectedRelation: "entity-jtc:REPORTS:entity-revenue",
    verification_state: "authority_verified",
    source: {
      receiptNumber: DART_PUBLIC_FIXTURE.receiptNumber,
      sourceLine: revenue.sourceLine,
      archiveSha256: DART_PUBLIC_FIXTURE.archiveSha256,
    },
  },
  A06: {
    assetId: "A06",
    name: "Deployable Package",
    truthClass: "T1",
    knowledge_package_manifest: {
      packageId: "knowledge-package-reference-v1",
      roots: [
        { path: "source/", purpose: "Original source registry", entries: 3 },
        { path: "canonical/", purpose: "Canonical blocks", entries: 4 },
        { path: "obsidian/", purpose: "Notes and MOCs", entries: 5 },
        { path: "ontology/", purpose: "Typed concepts", entries: 3 },
        { path: "graph/", purpose: "Neo4j nodes and relations", entries: 5 },
        { path: "rag/", purpose: "Retrieval chunks", entries: 4 },
        { path: "provenance/", purpose: "Source references", entries: 8 },
        { path: "validation/", purpose: "Validation receipts", entries: 2 },
      ],
    },
    checksums_sha256: { status: "available", manifestSha256: SHA_B },
    signature_status: "unavailable",
    round_trip_validation: "unavailable",
  },
};

export function SignatureAssetComposition({
  asset,
  direction,
}: {
  asset: SignatureAssetId;
  direction: CompositionDirection;
}) {
  const data = SIGNATURE_ASSET_CONTRACTS[asset];
  return (
    <article
      className={styles.composition}
      data-direction={direction}
      data-signature-asset={asset}
      data-truth-class={data.truthClass}
    >
      <header className={styles.header}>
        <span>{data.assetId}</span>
        <div>
          <p>{directionLabel(direction)}</p>
          <h1>{data.name}</h1>
        </div>
        <code>{data.truthClass}</code>
      </header>
      <div className={styles.body}>{renderContract(data)}</div>
      <footer>
        <span>Deterministic DOM composition</span>
        <code>{contractName(data)}</code>
      </footer>
    </article>
  );
}

function renderContract(data: SignatureAssetContract) {
  switch (data.assetId) {
    case "A01":
      return (
        <>
          <section className={styles.lead}>
            <small>Collection manifest</small>
            <strong>{data.collection_manifest_v1.files.length} files arrived with paths intact</strong>
            <span>{data.collection_manifest_v1.duplicateCount} possible duplicate · preflight {data.signed_collection_preflight.status}</span>
          </section>
          <section className={styles.panel}>
            <table><caption>Folder and file classification</caption><thead><tr><th>Relative path</th><th>Class</th><th>State</th></tr></thead><tbody>{data.collection_manifest_v1.files.map((file) => <tr key={file.path}><td><code>{file.path}</code></td><td>{file.kind}</td><td>{file.state}</td></tr>)}</tbody></table>
            <EvidenceHash label="Signed preflight" value={data.signed_collection_preflight.outputSha256} />
          </section>
        </>
      );
    case "A02":
      return (
        <>
          <section className={styles.lead}><small>Same source identity</small><strong>{data.source.id}</strong><span>{data.source.text}</span><code>bbox1000 [{data.source.bbox1000.join(", ")}]</code></section>
          <section className={styles.panel}><ol className={styles.blocks}>{data.canonical_blocks.map((block) => <li key={block.id} data-block-type={block.type}><b>{block.type}</b><span>{block.text}</span><code>{block.sourceRef}</code></li>)}</ol><div className={styles.chips}>{data.processing_events.map((event) => <code key={event}>{event}</code>)}</div></section>
        </>
      );
    case "A03":
      return (
        <>
          <section className={styles.lead}><small>Selected public-fixture result</small><strong>{data.selectedResult.value} {data.selectedResult.unit}</strong><span>{data.selectedResult.label} · {data.selectedResult.taxonomy}</span><b>Authority verified</b></section>
          <section className={styles.panel}><dl className={styles.register}><Row label="Authority" value={`${data.authority.source} · corp ${data.authority.corporationCode}`} /><Row label="Receipt" value={data.sourceTarget.receiptNumber} /><Row label="Exact source line" value={String(data.sourceTarget.sourceLine)} /><Row label="Quality claim eligible" value={String(data.qualityClaimEligible)} /></dl><EvidenceHash label="Source SHA-256" value={data.sourceTarget.sourceSha256} /></section>
        </>
      );
    case "A04":
      return (
        <>
          <section className={styles.lead}><small>Architecture plan</small><strong>{data.architecture_plan.planId}</strong><ul className={styles.tree}>{data.architecture_plan.directories.map((directory) => <li key={directory.path}><code>{directory.path}</code><span>{directory.itemCount}</span></li>)}</ul></section>
          <section className={styles.panel}><h2>Map of content → notes → source</h2>{data.architecture_plan.mocs.map((moc) => <h3 key={moc}>{moc}</h3>)}<ul className={styles.notes}>{data.architecture_plan.notes.map((note) => <li key={note.id}><strong>{note.title}</strong><code>{note.sourceRef}</code></li>)}</ul><RelationTable relations={data.architecture_plan.relations} /></section>
        </>
      );
    case "A05":
      return (
        <>
          <section className={styles.lead}><small>Selected typed relation</small><strong>{data.selectedRelation}</strong><div className={styles.nodes}>{data.entities.map((entity) => <span key={entity.id}><b>{entity.label}</b><small>{entity.type}</small></span>)}</div><b>{data.verification_state}</b></section>
          <section className={styles.panel}><RelationTable relations={data.typed_relations} /><dl className={styles.register}><Row label="Receipt" value={data.source.receiptNumber} /><Row label="Exact source line" value={String(data.source.sourceLine)} /></dl><EvidenceHash label="Archive SHA-256" value={data.source.archiveSha256} /></section>
        </>
      );
    case "A06":
      return (
        <>
          <section className={styles.lead}><small>Knowledge package manifest</small><strong>{data.knowledge_package_manifest.packageId}</strong><ul className={styles.tree}>{data.knowledge_package_manifest.roots.map((root) => <li key={root.path}><code>{root.path}</code><span>{root.entries}</span><small>{root.purpose}</small></li>)}</ul></section>
          <section className={styles.panel}><dl className={styles.register}><Row label="Checksums" value={data.checksums_sha256.status} /><Row label="Signature" value={data.signature_status} /><Row label="Round-trip validation" value={data.round_trip_validation} /></dl><EvidenceHash label="Manifest SHA-256" value={data.checksums_sha256.manifestSha256} /><p className={styles.boundary}>Unavailable states remain unavailable until signed or import-validation artifacts exist.</p></section>
        </>
      );
  }
}

function RelationTable({ relations }: { relations: Array<{ from: string; type: string; to: string; sourceRef: string }> }) {
  return <table><caption>Accessible typed relations</caption><thead><tr><th>From</th><th>Relation</th><th>To</th><th>Evidence</th></tr></thead><tbody>{relations.map((relation) => <tr key={`${relation.from}:${relation.type}:${relation.to}`}><td>{relation.from}</td><td><code>{relation.type}</code></td><td>{relation.to}</td><td><code>{relation.sourceRef}</code></td></tr>)}</tbody></table>;
}

function EvidenceHash({ label, value }: { label: string; value: string }) {
  return <p className={styles.hash}><span>{label}</span><code title={value}>{value}</code></p>;
}

function Row({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function directionLabel(direction: CompositionDirection): string {
  return { A: "Editorial transformation", B: "Proof-first product", C: "Knowledge architecture" }[direction];
}

function contractName(data: SignatureAssetContract): string {
  return {
    A01: "collection_manifest_v1 + signed_collection_preflight",
    A02: "canonical_blocks + source_refs_bbox1000 + processing_events",
    A03: "opendart_receipt + taxonomy + exact_source_line",
    A04: "architecture_plan + directories + mocs + notes + relations",
    A05: "entities + typed_relations + source_refs + verification_state",
    A06: "knowledge_package_manifest + checksums + validation_state",
  }[data.assetId];
}
