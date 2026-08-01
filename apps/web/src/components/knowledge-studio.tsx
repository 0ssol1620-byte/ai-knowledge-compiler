"use client";

import {
  ArrowSquareOut,
  ClockCounterClockwise,
  FileText,
  Funnel,
  Graph,
  ListBullets,
  MagnifyingGlass,
  ShieldCheck,
  TreeStructure,
  Warning,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { apiRequest } from "@/lib/api-client";
import type { StructaraLocale } from "@/lib/locale";
import {
  publicOriginLabel,
  publicRouteLabel,
} from "@/lib/public-processing-labels";

type ProvenanceNote = {
  note_id: string;
  stable_key: string;
  content_origin: string;
  review_status: string;
  evidence_block_ids: string[];
  compile_provenance: Record<string, unknown>;
};

type ProvenanceRelation = {
  relation_id: string;
  source_relation_key: string | null;
  subject_id: string;
  predicate: string;
  object_id: string;
  evidence_block_ids: string[];
  compile_provenance: Record<string, unknown>;
};

type ProvenanceBlock = {
  block_id: string;
  page_id: string | null;
  page_number: number | null;
  block_order: number;
  block_type: string;
  origin: string;
  bbox1000: number[] | null;
  content_hash: string | null;
  engine: string | null;
  engine_revision: string | null;
  revision: number;
};

type ProvenanceResponse = {
  document_id: string;
  project_id: string;
  cir_schema_version: string;
  active_version: number;
  source: {
    sha256: string;
    mime_type: string;
    size_bytes: number;
    original_filename: string;
  };
  blocks: ProvenanceBlock[];
  knowledge_notes: ProvenanceNote[];
  relations: ProvenanceRelation[];
  source_coverage_ratio: number;
};

type KnowledgeNoteResponse = {
  id: string;
  stable_key: string;
  title: string;
  note_type: string;
  content_markdown: string;
  metadata: Record<string, unknown>;
  evidence_block_ids: string[];
  content_origin: string;
  review_status: string;
  document_id: string | null;
  document_version: number | null;
  updated_at: string;
};

type KnowledgeNode = {
  id: string;
  title: string;
  type: string;
  status: string;
  origin: string;
  content: string;
  evidenceBlockIds: string[];
};

type KnowledgeRelation = {
  id: string;
  subjectId: string;
  predicate: string;
  objectId: string;
  evidenceBlockIds: string[];
};

type Tab = "Graph" | "Notes" | "Relations" | "Evidence";
type Perspective = "Document" | "Entity" | "Risk" | "Timeline" | "Evidence";

const DEMO_MODE = process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true";

const sampleNodes: KnowledgeNode[] = [
  {
    id: "company:jtc",
    title: "JTC Corporation",
    type: "Entity",
    status: "verified",
    origin: "public filing fixture",
    content: "The reporting entity represented in the canonical DART fixture.",
    evidenceBlockIds: ["blk_company_profile", "blk_revenue_table"],
  },
  {
    id: "metric:revenue-2025",
    title: "Revenue · FY2025",
    type: "Metric",
    status: "verified",
    origin: "XBRL-derived",
    content:
      "Revenue fact preserved with unit, period, taxonomy, and source cell.",
    evidenceBlockIds: ["blk_revenue_table"],
  },
  {
    id: "segment:industrial",
    title: "Industrial segment",
    type: "Segment",
    status: "reviewed",
    origin: "structured extraction",
    content: "Segment boundary compiled from the source filing hierarchy.",
    evidenceBlockIds: ["blk_segment_note"],
  },
  {
    id: "risk:supply-chain",
    title: "Supply-chain concentration",
    type: "Risk",
    status: "unresolved",
    origin: "source-linked note",
    content:
      "Risk note remains unresolved; no unsupported severity score is shown.",
    evidenceBlockIds: ["blk_risk_note"],
  },
  {
    id: "filing:2025-annual",
    title: "2025 annual filing",
    type: "Document",
    status: "verified",
    origin: "OpenDART receipt",
    content:
      "Canonical source document for this deterministic interactive sample.",
    evidenceBlockIds: ["blk_title", "blk_company_profile"],
  },
];

const sampleRelations: KnowledgeRelation[] = [
  {
    id: "rel-1",
    subjectId: "filing:2025-annual",
    predicate: "reports_on",
    objectId: "company:jtc",
    evidenceBlockIds: ["blk_company_profile"],
  },
  {
    id: "rel-2",
    subjectId: "company:jtc",
    predicate: "reports_metric",
    objectId: "metric:revenue-2025",
    evidenceBlockIds: ["blk_revenue_table"],
  },
  {
    id: "rel-3",
    subjectId: "company:jtc",
    predicate: "operates_segment",
    objectId: "segment:industrial",
    evidenceBlockIds: ["blk_segment_note"],
  },
  {
    id: "rel-4",
    subjectId: "company:jtc",
    predicate: "discloses_risk",
    objectId: "risk:supply-chain",
    evidenceBlockIds: ["blk_risk_note"],
  },
];

const sampleBlocks: ProvenanceBlock[] = [
  {
    block_id: "blk_revenue_table",
    page_id: "page-8",
    page_number: 8,
    block_order: 18,
    block_type: "table",
    origin: "native_extracted",
    bbox1000: [112, 326, 892, 634],
    content_hash: "sha256:sample-revenue-cell",
    engine: "native-xbrl",
    engine_revision: "canonical-fixture-v1",
    revision: 1,
  },
  {
    block_id: "blk_segment_note",
    page_id: "page-14",
    page_number: 14,
    block_order: 31,
    block_type: "paragraph",
    origin: "structured_extracted",
    bbox1000: [98, 210, 904, 512],
    content_hash: "sha256:sample-segment-note",
    engine: "native",
    engine_revision: "canonical-fixture-v1",
    revision: 1,
  },
  {
    block_id: "blk_risk_note",
    page_id: "page-27",
    page_number: 27,
    block_order: 66,
    block_type: "paragraph",
    origin: "native_extracted",
    bbox1000: [104, 188, 899, 528],
    content_hash: "sha256:sample-risk-note",
    engine: "native",
    engine_revision: "canonical-fixture-v1",
    revision: 1,
  },
];

const KNOWLEDGE_COPY = {
  en: {
    title: "Knowledge Studio",
    selectTitle: "Select a compiled document",
    selectBody:
      "Knowledge exploration requires an exact document version so notes, relations, and evidence can remain source-bound.",
    openProjects: "Open projects",
    loading: "Loading the knowledge package…",
    loadError: "The knowledge package could not be loaded",
    retry: "Retry",
    breadcrumb: "Knowledge",
    fixture: "Canonical public-filing fixture",
    sample: "Interactive deterministic sample",
    version: "Document v",
    health: "Knowledge package health",
    notes: "notes",
    relations: "relations",
    evidenceLocated: "located evidence",
    upload: "Upload document",
    publishUnavailable:
      "Publishing is unavailable in the deterministic demo workspace.",
    publish: "Publish package",
    views: "Knowledge views",
    tabs: {
      Graph: "Graph",
      Notes: "Notes",
      Relations: "Relations",
      Evidence: "Evidence",
    },
    searchPlaceholder: "Search notes, entities, risks…",
    searchLabel: "Search knowledge",
    perspectives: "Perspectives",
    perspectiveLabels: {
      Document: "Document",
      Entity: "Entity",
      Risk: "Risk",
      Timeline: "Timeline",
      Evidence: "Evidence",
    },
    canvas: "Knowledge canvas",
    matching: "matching notes",
    perspective: "perspective",
    principle: "Search before spectacle. Proof before inference.",
    neighborhood: "Selected knowledge neighborhood",
    noNeighborhood: "No matching neighborhood",
    noNeighborhoodBody: "Clear the search or choose another perspective.",
    selectedObject: "Selected knowledge object",
    related: "related",
    evidenceBlocks: "evidence block(s)",
    notesCaption: "Evidence-bound knowledge notes",
    note: "Note",
    type: "Type",
    status: "Status",
    relationsCaption: "Relations with adjacent source evidence",
    subject: "Subject",
    predicate: "Predicate",
    object: "Object",
    evidence: "Evidence",
    page: "Page",
    block: "Block",
    origin: "Origin",
    engine: "Processing route",
    notRecorded: "not recorded",
    revision: "Revision",
    content: "KNOWLEDGE CONTENT",
    connected: "CONNECTED RELATIONS",
    noRelation: "No relation is asserted without evidence.",
    sourceEvidence: "SOURCE EVIDENCE",
    noSource: "No located source block is registered for this object.",
    openLedger: "Open source ledger",
    selectObject: "Select a knowledge object to inspect its proof.",
  },
  ko: {
    title: "지식 Studio",
    selectTitle: "컴파일된 문서를 선택하세요",
    selectBody:
      "노트, 관계와 근거를 원본에 연결하려면 정확한 문서 버전이 필요합니다.",
    openProjects: "프로젝트 열기",
    loading: "지식 패키지를 불러오는 중…",
    loadError: "지식 패키지를 불러올 수 없습니다",
    retry: "다시 시도",
    breadcrumb: "지식",
    fixture: "공개 공시 기준 fixture",
    sample: "결정적 인터랙티브 샘플",
    version: "문서 v",
    health: "지식 패키지 상태",
    notes: "노트",
    relations: "관계",
    evidenceLocated: "위치가 확인된 근거",
    upload: "문서 업로드",
    publishUnavailable:
      "결정적 데모 워크스페이스에서는 패키지를 게시할 수 없습니다.",
    publish: "패키지 게시",
    views: "지식 보기",
    tabs: {
      Graph: "그래프",
      Notes: "노트",
      Relations: "관계",
      Evidence: "근거",
    },
    searchPlaceholder: "노트, 엔티티, 위험 검색…",
    searchLabel: "지식 검색",
    perspectives: "관점",
    perspectiveLabels: {
      Document: "문서",
      Entity: "엔티티",
      Risk: "위험",
      Timeline: "타임라인",
      Evidence: "근거",
    },
    canvas: "지식 캔버스",
    matching: "개 일치 노트",
    perspective: "관점",
    principle: "화려함보다 검색을, 추론보다 근거를 우선합니다.",
    neighborhood: "선택한 지식 주변 관계",
    noNeighborhood: "일치하는 지식 주변 관계가 없습니다",
    noNeighborhoodBody: "검색을 초기화하거나 다른 관점을 선택하세요.",
    selectedObject: "선택한 지식 객체",
    related: "관련",
    evidenceBlocks: "개 근거 블록",
    notesCaption: "근거 연결 지식 노트",
    note: "노트",
    type: "유형",
    status: "상태",
    relationsCaption: "인접 원본 근거가 있는 관계",
    subject: "주어",
    predicate: "관계",
    object: "목적어",
    evidence: "근거",
    page: "페이지",
    block: "블록",
    origin: "출처",
    engine: "처리 경로",
    notRecorded: "기록 없음",
    revision: "리비전",
    content: "지식 콘텐츠",
    connected: "연결된 관계",
    noRelation: "근거 없는 관계는 단정하지 않습니다.",
    sourceEvidence: "원본 근거",
    noSource: "이 객체에 등록된 위치 기반 원본 블록이 없습니다.",
    openLedger: "원본 원장 열기",
    selectObject: "근거를 확인할 지식 객체를 선택하세요.",
  },
} as const;

export function KnowledgeStudio({
  locale = "en",
}: {
  locale?: StructaraLocale;
}) {
  const copy = KNOWLEDGE_COPY[locale];
  const searchParams = useSearchParams();
  const documentId = searchParams.get("document");
  const [tab, setTab] = useState<Tab>("Graph");
  const [perspective, setPerspective] = useState<Perspective>("Document");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("company:jtc");

  const provenance = useQuery({
    queryKey: ["knowledge-provenance", documentId],
    queryFn: () =>
      apiRequest<ProvenanceResponse>(`/v1/documents/${documentId}/provenance`),
    enabled: !DEMO_MODE && Boolean(documentId),
  });

  const notes = useQuery({
    queryKey: ["project-knowledge", provenance.data?.project_id],
    queryFn: () =>
      apiRequest<KnowledgeNoteResponse[]>(
        `/v1/projects/${provenance.data?.project_id}/knowledge?limit=200`,
      ),
    enabled: !DEMO_MODE && Boolean(provenance.data?.project_id),
  });

  const nodes = useMemo<KnowledgeNode[]>(() => {
    if (DEMO_MODE) return sampleNodes;
    if (!provenance.data) return [];
    const fullByStableKey = new Map(
      (notes.data ?? []).map((note) => [note.stable_key, note]),
    );
    return provenance.data.knowledge_notes.map((note) => {
      const full = fullByStableKey.get(note.stable_key);
      return {
        id: note.note_id,
        title: full?.title || note.stable_key,
        type: full?.note_type || "Knowledge note",
        status: note.review_status,
        origin: note.content_origin,
        content:
          full?.content_markdown ||
          "This note is available in the evidence-bound project knowledge package.",
        evidenceBlockIds: note.evidence_block_ids,
      };
    });
  }, [notes.data, provenance.data]);

  const relations = useMemo<KnowledgeRelation[]>(() => {
    if (DEMO_MODE) return sampleRelations;
    return (provenance.data?.relations ?? []).map((relation) => ({
      id: relation.relation_id,
      subjectId: relation.subject_id,
      predicate: relation.predicate,
      objectId: relation.object_id,
      evidenceBlockIds: relation.evidence_block_ids,
    }));
  }, [provenance.data]);

  const blocks = DEMO_MODE ? sampleBlocks : (provenance.data?.blocks ?? []);
  const normalizedQuery = query.trim().toLowerCase();
  const filteredNodes = nodes.filter((node) => {
    const matchesQuery =
      normalizedQuery.length === 0 ||
      `${node.title} ${node.type} ${node.content}`
        .toLowerCase()
        .includes(normalizedQuery);
    const matchesPerspective =
      perspective === "Document" ||
      (perspective === "Entity" && /entity|company|segment/i.test(node.type)) ||
      (perspective === "Risk" &&
        /risk|unresolved/i.test(`${node.type} ${node.status}`)) ||
      (perspective === "Timeline" &&
        /filing|document|date|year/i.test(`${node.type} ${node.title}`)) ||
      (perspective === "Evidence" && node.evidenceBlockIds.length > 0);
    return matchesQuery && matchesPerspective;
  });

  const selected =
    nodes.find((node) => node.id === selectedId) ||
    filteredNodes[0] ||
    nodes[0];
  const selectedRelations = relations.filter(
    (relation) =>
      relation.subjectId === selected?.id || relation.objectId === selected?.id,
  );
  const neighborIds = new Set(
    selectedRelations.flatMap((relation) => [
      relation.subjectId,
      relation.objectId,
    ]),
  );
  const neighborhood = nodes.filter(
    (node) => node.id === selected?.id || neighborIds.has(node.id),
  );
  const evidenceBlocks = blocks.filter((block) =>
    selected?.evidenceBlockIds.includes(block.block_id),
  );
  const coverage = DEMO_MODE
    ? 1
    : (provenance.data?.source_coverage_ratio ?? 0);

  if (!DEMO_MODE && !documentId) {
    return (
      <div className="simple-page">
        <h1>{copy.title}</h1>
        <div className="honest-state panel">
          <TreeStructure size={28} aria-hidden="true" />
          <div>
            <h2>{copy.selectTitle}</h2>
            <p>{copy.selectBody}</p>
            <Link className="primary-button compact" href="/projects">
              {copy.openProjects}
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if ((provenance.isPending || notes.isPending) && !DEMO_MODE) {
    return <div className="st-document-loading">{copy.loading}</div>;
  }

  if ((provenance.isError || notes.isError) && !DEMO_MODE) {
    const message = provenance.error?.message || notes.error?.message;
    return (
      <div className="simple-page">
        <h1>{copy.title}</h1>
        <div className="honest-state panel">
          <Warning size={28} weight="fill" aria-hidden="true" />
          <div>
            <h2>{copy.loadError}</h2>
            <p>{message}</p>
            <button
              type="button"
              className="primary-button compact"
              onClick={() => {
                void provenance.refetch();
                void notes.refetch();
              }}
            >
              {copy.retry}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="knowledge-studio-page"
      data-knowledge-mode={DEMO_MODE ? "sample" : "live"}
      data-locale={locale}
    >
      <header className="knowledge-context-header">
        <div>
          <p>
            {copy.breadcrumb} /{" "}
            {DEMO_MODE
              ? copy.fixture
              : provenance.data?.source.original_filename}
          </p>
          <h1>{copy.title}</h1>
        </div>
        <span className="demo-sample-chip">
          {DEMO_MODE
            ? copy.sample
            : `${copy.version}${provenance.data?.active_version}`}
        </span>
        <div className="knowledge-health-inline" aria-label={copy.health}>
          <span>
            <strong>{nodes.length}</strong> {copy.notes}
          </span>
          <span>
            <strong>{relations.length}</strong> {copy.relations}
          </span>
          <span>
            <strong>{Math.round(coverage * 100)}%</strong>{" "}
            {copy.evidenceLocated}
          </span>
        </div>
      </header>

      <nav className="knowledge-view-tabs" aria-label={copy.views}>
        {(["Graph", "Notes", "Relations", "Evidence"] as const).map((item) => (
          <button
            type="button"
            className={tab === item ? "active" : undefined}
            aria-pressed={tab === item}
            onClick={() => setTab(item)}
            key={item}
          >
            {item === "Graph" && <Graph size={15} />}
            {item === "Notes" && <ListBullets size={15} />}
            {item === "Relations" && <TreeStructure size={15} />}
            {item === "Evidence" && <ShieldCheck size={15} />}
            {copy.tabs[item]}
          </button>
        ))}
      </nav>

      <div className="knowledge-layout">
        <aside className="knowledge-explorer">
          <label>
            <MagnifyingGlass size={15} />
            <input
              value={query}
              onInput={(event) => setQuery(event.currentTarget.value)}
              placeholder={copy.searchPlaceholder}
              aria-label={copy.searchLabel}
            />
          </label>
          <span>
            <Funnel size={13} /> {copy.perspectives}
          </span>
          {(
            ["Document", "Entity", "Risk", "Timeline", "Evidence"] as const
          ).map((item) => (
            <button
              type="button"
              aria-label={copy.perspectiveLabels[item]}
              className={perspective === item ? "active" : undefined}
              aria-pressed={perspective === item}
              onClick={() => setPerspective(item)}
              key={item}
            >
              {item === "Document" && <FileText size={16} />}
              {item === "Entity" && <TreeStructure size={16} />}
              {item === "Risk" && <Warning size={16} />}
              {item === "Timeline" && <ClockCounterClockwise size={16} />}
              {item === "Evidence" && <ShieldCheck size={16} />}
              <span>{copy.perspectiveLabels[item]}</span>
            </button>
          ))}
        </aside>

        <section className="knowledge-canvas" aria-label={copy.canvas}>
          <header>
            <div>
              <strong>{copy.tabs[tab]}</strong>
              <span>
                {filteredNodes.length} {copy.matching} ·{" "}
                {copy.perspectiveLabels[perspective]} {copy.perspective}
              </span>
            </div>
            <small>{copy.principle}</small>
          </header>

          {tab === "Graph" && (
            <section
              className="knowledge-neighborhood"
              aria-label={copy.neighborhood}
            >
              {!selected || neighborhood.length === 0 ? (
                <div className="knowledge-empty-result">
                  <MagnifyingGlass size={24} />
                  <h2>{copy.noNeighborhood}</h2>
                  <p>{copy.noNeighborhoodBody}</p>
                </div>
              ) : (
                <>
                  <div className="knowledge-neighborhood-core">
                    <span>{copy.selectedObject}</span>
                    <button
                      type="button"
                      className="selected"
                      onClick={() => setSelectedId(selected.id)}
                    >
                      <i data-kind={selected.type.toLowerCase()} />
                      <strong>{selected.title}</strong>
                      <small>
                        {selected.type} · {selected.status}
                      </small>
                    </button>
                  </div>
                  <div className="knowledge-neighbor-grid">
                    {neighborhood
                      .filter((node) => node.id !== selected.id)
                      .map((node) => {
                        const relation = selectedRelations.find(
                          (candidate) =>
                            candidate.subjectId === node.id ||
                            candidate.objectId === node.id,
                        );
                        return (
                          <button
                            type="button"
                            onClick={() => setSelectedId(node.id)}
                            key={node.id}
                          >
                            <span>
                              {relation?.predicate.replaceAll("_", " ") ||
                                copy.related}
                            </span>
                            <strong>{node.title}</strong>
                            <small>
                              {node.type} · {node.evidenceBlockIds.length}{" "}
                              {copy.evidenceBlocks}
                            </small>
                          </button>
                        );
                      })}
                  </div>
                </>
              )}
            </section>
          )}

          {tab === "Notes" && (
            <div className="knowledge-table-wrap">
              <table className="knowledge-accessible-table">
                <caption>{copy.notesCaption}</caption>
                <thead>
                  <tr>
                    <th>{copy.note}</th>
                    <th>{copy.type}</th>
                    <th>{copy.status}</th>
                    <th>{copy.evidence}</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredNodes.map((node) => (
                    <tr key={node.id} data-selected={selected?.id === node.id}>
                      <th scope="row">
                        <button
                          type="button"
                          onClick={() => setSelectedId(node.id)}
                        >
                          {node.title}
                        </button>
                      </th>
                      <td>{node.type}</td>
                      <td>{node.status}</td>
                      <td>{node.evidenceBlockIds.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {tab === "Relations" && (
            <div className="knowledge-table-wrap">
              <table className="knowledge-accessible-table">
                <caption>{copy.relationsCaption}</caption>
                <thead>
                  <tr>
                    <th>{copy.subject}</th>
                    <th>{copy.predicate}</th>
                    <th>{copy.object}</th>
                    <th>{copy.evidence}</th>
                  </tr>
                </thead>
                <tbody>
                  {relations.map((relation) => (
                    <tr key={relation.id}>
                      <td>{nodeTitle(nodes, relation.subjectId)}</td>
                      <td>
                        <code>{relation.predicate}</code>
                      </td>
                      <td>{nodeTitle(nodes, relation.objectId)}</td>
                      <td>{relation.evidenceBlockIds.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {tab === "Evidence" && (
            <div className="knowledge-evidence-ledger">
              {blocks.map((block) => (
                <article
                  key={block.block_id}
                  data-selected={selected?.evidenceBlockIds.includes(
                    block.block_id,
                  )}
                >
                  <header>
                    <span>
                      {copy.page} {block.page_number ?? "—"}
                    </span>
                    <strong>{block.block_type}</strong>
                  </header>
                  <dl>
                    <div>
                      <dt>{copy.block}</dt>
                      <dd>{block.block_id}</dd>
                    </div>
                    <div>
                      <dt>{copy.origin}</dt>
                      <dd>{publicOriginLabel(block.origin, locale)}</dd>
                    </div>
                    <div>
                      <dt>{copy.engine}</dt>
                      <dd>
                        {block.engine
                          ? publicRouteLabel(block.engine, locale)
                          : copy.notRecorded}
                      </dd>
                    </div>
                    <div>
                      <dt>{copy.revision}</dt>
                      <dd>{block.revision}</dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
          )}
        </section>

        <aside className="knowledge-evidence-panel">
          {selected ? (
            <>
              <header>
                <span>{selected.type}</span>
                <div>
                  <strong>{selected.title}</strong>
                  <small>
                    {publicOriginLabel(selected.origin, locale)} ·{" "}
                    {selected.status}
                  </small>
                </div>
              </header>
              <section>
                <span>{copy.content}</span>
                <p>{selected.content}</p>
              </section>
              <section>
                <span>{copy.connected}</span>
                {selectedRelations.length > 0 ? (
                  <ul>
                    {selectedRelations.map((relation) => (
                      <li key={relation.id}>
                        <code>{relation.predicate}</code>
                        <span>
                          {nodeTitle(
                            nodes,
                            relation.subjectId === selected.id
                              ? relation.objectId
                              : relation.subjectId,
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>{copy.noRelation}</p>
                )}
              </section>
              <section>
                <span>{copy.sourceEvidence}</span>
                {evidenceBlocks.length > 0 ? (
                  evidenceBlocks.map((block) => (
                    <div className="knowledge-proof-card" key={block.block_id}>
                      <strong>
                        {copy.page} {block.page_number ?? "—"} ·{" "}
                        {block.block_type}
                      </strong>
                      <small>
                        {publicOriginLabel(block.origin, locale)} ·{" "}
                        {copy.revision} {block.revision}
                      </small>
                      <code>{block.block_id}</code>
                    </div>
                  ))
                ) : (
                  <p>{copy.noSource}</p>
                )}
              </section>
              <Link
                className="primary-button compact"
                href={`/documents/${documentId || "sample-dart"}/sources`}
                data-app-header-action
              >
                {copy.openLedger} <ArrowSquareOut size={14} />
              </Link>
              {DEMO_MODE && (
                <button
                  type="button"
                  className="secondary-button compact"
                  data-sample-static-control
                  disabled
                  title={copy.publishUnavailable}
                >
                  {copy.publish}
                </button>
              )}
            </>
          ) : (
            <div className="knowledge-empty-result">
              <TreeStructure size={24} />
              <p>{copy.selectObject}</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function nodeTitle(nodes: KnowledgeNode[], id: string): string {
  return nodes.find((node) => node.id === id)?.title || id;
}
