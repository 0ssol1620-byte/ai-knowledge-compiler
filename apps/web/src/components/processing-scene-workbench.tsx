"use client";

import {
  CheckCircle,
  Database,
  FileText,
  ShieldWarning,
} from "@phosphor-icons/react";
import { useMemo, useState } from "react";

import {
  FolyntaResizableGroup,
  FolyntaResizableHandle,
  FolyntaResizablePanel,
} from "@/components/system/folynta-resizable";
import { apiAbsoluteUrl } from "@/lib/api-client";
import {
  getProofCropUrl,
  type CollectionScene,
} from "@/lib/collection-runtime-client";
import type { ProcessingSceneModel } from "@/lib/processing-scene-model";
import type { StructaraLocale } from "@/lib/locale";

import styles from "./processing-scene-workbench.module.css";

type ScenePage = NonNullable<CollectionScene>["pages"][number];

export function ProcessingSceneWorkbench({
  scene,
  projection,
  locale,
  mobile,
}: {
  scene: CollectionScene | null;
  projection: ProcessingSceneModel;
  locale: StructaraLocale;
  mobile: boolean;
}) {
  const copy = COPY[locale];
  const pages = useMemo(() => scene?.pages ?? [], [scene?.pages]);
  const [selectedPageId, setSelectedPageId] = useState<string | null>(null);
  const effectiveSelectedPageId = pages.some(
    (page) => page.page_id === selectedPageId,
  )
    ? selectedPageId
    : (pages[0]?.page_id ?? null);
  const selected =
    pages.find((page) => page.page_id === effectiveSelectedPageId) ?? null;

  const sourcePanel = (
    <SourceRail
      scene={scene}
      pages={pages}
      selected={selected}
      onSelect={setSelectedPageId}
      locale={locale}
    />
  );
  const canvasPanel = (
    <PageCanvas page={selected} projection={projection} copy={copy} />
  );
  const structurePanel = (
    <StructureRail page={selected} projection={projection} copy={copy} />
  );
  const worldPanel = (
    <WorldRail scene={scene} projection={projection} copy={copy} />
  );

  if (mobile) {
    return (
      <section className={styles.mobileStack} aria-label={copy.sceneView}>
        {sourcePanel}
        {canvasPanel}
        {structurePanel}
        {worldPanel}
      </section>
    );
  }

  return (
    <section className={styles.workbench} aria-label={copy.sceneView}>
      <FolyntaResizableGroup
        orientation="horizontal"
        id="folynta-processing-scene"
      >
        <FolyntaResizablePanel id="source" defaultSize="20" minSize="16">
          {sourcePanel}
        </FolyntaResizablePanel>
        <FolyntaResizableHandle withHandle />
        <FolyntaResizablePanel id="page" defaultSize="34" minSize="26">
          {canvasPanel}
        </FolyntaResizablePanel>
        <FolyntaResizableHandle withHandle />
        <FolyntaResizablePanel id="structure" defaultSize="20" minSize="16">
          {structurePanel}
        </FolyntaResizablePanel>
        <FolyntaResizableHandle withHandle />
        <FolyntaResizablePanel id="world" defaultSize="26" minSize="18">
          {worldPanel}
        </FolyntaResizablePanel>
      </FolyntaResizableGroup>
    </section>
  );
}

function SourceRail({
  scene,
  pages,
  selected,
  onSelect,
  locale,
}: {
  scene: CollectionScene | null;
  pages: ScenePage[];
  selected: ScenePage | null;
  onSelect: (pageId: string) => void;
  locale: StructaraLocale;
}) {
  const copy = COPY[locale];
  return (
    <article className={styles.rail}>
      <header className={styles.panelHeader}>
        <span>01 · SOURCES</span>
        <strong>
          {scene
            ? copy.sourceSummary(scene.clusters.length, scene.total_pages)
            : copy.awaitingSnapshot}
        </strong>
        {scene ? (
          <code title={scene.scene_hash}>{scene.scene_hash.slice(0, 12)}</code>
        ) : null}
      </header>
      {scene?.clusters.length ? (
        <ol className={styles.clusterList}>
          {scene.clusters.map((cluster) => (
            <li key={cluster.cluster_id}>
              <Database size={15} aria-hidden="true" />
              <span>
                <strong>{cluster.strategy}</strong>
                <small>{copy.clusterFiles(cluster.member_count)}</small>
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className={styles.empty}>{copy.noClusters}</p>
      )}
      <div className={styles.pageRegister}>
        <span>{copy.pages}</span>
        {pages.length ? (
          <ol>
            {pages.map((page) => (
              <li key={page.page_id}>
                <button
                  type="button"
                  data-selected={
                    page.page_id === selected?.page_id || undefined
                  }
                  onClick={() => onSelect(page.page_id)}
                >
                  <FileText size={15} aria-hidden="true" />
                  <span>
                    <strong>{copy.page(page.page_number)}</strong>
                    <small>
                      {page.route ?? copy.unrouted} · {page.status}
                    </small>
                  </span>
                  {page.finding_count > 0 ? <b>{page.finding_count}</b> : null}
                </button>
              </li>
            ))}
          </ol>
        ) : (
          <p className={styles.empty}>{copy.noPages}</p>
        )}
      </div>
    </article>
  );
}

function PageCanvas({
  page,
  projection,
  copy,
}: {
  page: ScenePage | null;
  projection: ProcessingSceneModel;
  copy: (typeof COPY)[keyof typeof COPY];
}) {
  const projected = page
    ? projection.pages.find((item) => item.id === page.page_id)
    : projection.pages[0];
  const evidenceCounts = useMemo(
    () => ({
      regions: projected?.regionIds.length ?? 0,
      blocks: projected?.blockIds.length ?? 0,
      tables: projected?.tableIds.length ?? 0,
      proofs: projected?.proofIds.length ?? 0,
    }),
    [projected],
  );
  const firstProofId = projected?.proofIds[0];
  const proofCropUrl = useMemo(() => {
    if (!firstProofId) return null;
    try {
      return getProofCropUrl(firstProofId);
    } catch {
      return null;
    }
  }, [firstProofId]);
  return (
    <article className={styles.canvasPanel}>
      <header className={styles.panelHeader}>
        <span>02 · READ</span>
        <strong>
          {page
            ? `${copy.page(page.page_number)} · ${page.status}`
            : copy.awaitingPage}
        </strong>
        {page ? (
          <code title={page.page_id}>{page.page_id.slice(0, 12)}</code>
        ) : null}
      </header>
      <div
        className={styles.pageStage}
        data-available={Boolean(page?.preview_ref)}
      >
        {page?.preview_ref ? (
          // Authenticated API-derived image; Next Image optimization must not cache this proof surface.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={
              page.preview_ref.startsWith("/product/")
                ? page.preview_ref
                : apiAbsoluteUrl(page.preview_ref)
            }
            alt={copy.previewAlt(page.page_number)}
          />
        ) : (
          <div className={styles.noPreview}>
            <FileText size={34} aria-hidden="true" />
            <strong>{copy.previewUnavailable}</strong>
            <span>{copy.previewUnavailableBody}</span>
          </div>
        )}
        {page ? (
          <span className={styles.pageState}>
            {page.route ?? copy.unrouted}
          </span>
        ) : null}
        {proofCropUrl ? (
          <figure className={styles.proofCrop}>
            {/* Tenant-authorized, PII-masked crop; never route through a shared image cache. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={proofCropUrl} alt={copy.proofCropAlt} />
            <figcaption>
              <span>{copy.actualProof}</span>
              <code title={firstProofId}>{firstProofId?.slice(0, 12)}</code>
            </figcaption>
          </figure>
        ) : null}
      </div>
      <dl className={styles.evidenceStrip}>
        {Object.entries(evidenceCounts).map(([key, value]) => (
          <div key={key}>
            <dt>
              {copy.evidenceLabels[key as keyof typeof copy.evidenceLabels]}
            </dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

function StructureRail({
  page,
  projection,
  copy,
}: {
  page: ScenePage | null;
  projection: ProcessingSceneModel;
  copy: (typeof COPY)[keyof typeof COPY];
}) {
  const projected = page
    ? projection.pages.find((item) => item.id === page.page_id)
    : projection.pages[0];
  const structure = [
    [copy.regions, projected?.regionIds ?? []],
    [copy.blocks, projected?.blockIds ?? []],
    [copy.tables, projected?.tableIds ?? []],
  ] as const;
  return (
    <article className={styles.rail}>
      <header className={styles.panelHeader}>
        <span>03 · STRUCTURE</span>
        <strong>{copy.structureBody}</strong>
      </header>
      <dl className={styles.knowledgeCounts}>
        {structure.map(([label, ids]) => (
          <div key={label}><dt>{label}</dt><dd>{ids.length}</dd></div>
        ))}
      </dl>
      <ol className={styles.milestones} aria-label={copy.milestones}>
        {projection.milestones.slice(-6).map((milestone) => (
          <li key={milestone.id}><span /><div><strong>{milestone.kind}</strong><small>#{milestone.sequence}</small></div></li>
        ))}
      </ol>
      {projection.milestones.length === 0 ? <p className={styles.empty}>{copy.noMilestones}</p> : null}
    </article>
  );
}

function WorldRail({
  scene,
  projection,
  copy,
}: {
  scene: CollectionScene | null;
  projection: ProcessingSceneModel;
  copy: (typeof COPY)[keyof typeof COPY];
}) {
  const knowledge = scene?.knowledge;
  const integrity = scene?.integrity;
  const deltas = [
    [copy.notes, knowledge?.note_count ?? projection.knowledge.notes.length],
    [
      copy.entities,
      knowledge?.entity_count ?? projection.knowledge.entities.length,
    ],
    [
      copy.relations,
      knowledge?.relation_count ?? projection.knowledge.relations.length,
    ],
    [
      copy.packages,
      knowledge?.package_count ?? projection.knowledge.packages.length,
    ],
  ] as const;
  return (
    <article className={styles.rail}>
      <header className={styles.panelHeader}>
        <span>04 · WORLD</span>
        <strong>{copy.worldBody}</strong>
      </header>
      <dl className={styles.knowledgeCounts}>
        {deltas.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <ol className={styles.milestones} aria-label={copy.actualWorldObjects}>
        {[
          ...(knowledge?.note_ids ?? []).map((id) => [copy.notes, id] as const),
          ...(knowledge?.entity_ids ?? []).map((id) => [copy.entities, id] as const),
          ...(knowledge?.relation_ids ?? []).map((id) => [copy.relations, id] as const),
        ].slice(0, 12).map(([kind, id]) => (
          <li key={`${kind}:${id}`}><span /><div><strong>{kind}</strong><small title={id}>{id.slice(0, 12)}</small></div></li>
        ))}
      </ol>
      <div
        className={styles.integritySummary}
        data-alert={Boolean(
          integrity?.unresolved_count || integrity?.quarantined_count,
        )}
      >
        {integrity?.unresolved_count || integrity?.quarantined_count ? (
          <ShieldWarning size={18} weight="fill" aria-hidden="true" />
        ) : (
          <CheckCircle size={18} weight="fill" aria-hidden="true" />
        )}
        <span>
          <strong>
            {integrity
              ? copy.integrityCounts(
                  integrity.unresolved_count,
                  integrity.quarantined_count,
                )
              : copy.integrityPending}
          </strong>
          <small>
            {integrity?.blocker_codes.join(" · ") || copy.noBlockers}
          </small>
        </span>
      </div>
      {!knowledge || (knowledge.note_ids.length + knowledge.entity_ids.length + knowledge.relation_ids.length === 0) ? (
        <p className={styles.empty}>{copy.noWorldObjects}</p>
      ) : null}
    </article>
  );
}

const COPY = {
  en: {
    sceneView: "Live processing scene",
    collection: "Collection intelligence",
    sourceSummary: (clusters: number, pages: number) =>
      `${clusters} clusters · ${pages} pages`,
    awaitingSnapshot: "Waiting for the tenant-scoped scene snapshot",
    clusterFiles: (count: number) => `${count} files`,
    noClusters: "No persisted cluster projection is available yet.",
    pages: "Page register",
    page: (number: number) => `Page ${number}`,
    noPages: "No persisted page is available yet.",
    unrouted: "unrouted",
    pageIntelligence: "Page intelligence canvas",
    awaitingPage: "Waiting for a persisted page",
    previewAlt: (number: number) =>
      `Authenticated derived preview for page ${number}`,
    previewUnavailable: "Preview not generated",
    previewUnavailableBody:
      "Status and route remain visible; a page image is shown only after an integrity-checked derivative exists.",
    actualProof: "Actual source proof",
    proofCropAlt: "PII-masked crop from the persisted verification record",
    evidenceLabels: {
      regions: "Regions",
      blocks: "Blocks",
      tables: "Tables",
      proofs: "Proofs",
    },
    knowledge: "Knowledge formation",
    structureBody: "Persisted regions, blocks, tables, and milestones only.",
    worldBody: "Only persisted World IDs enter this rail.",
    regions: "Regions",
    blocks: "Blocks",
    tables: "Tables",
    notes: "Notes",
    entities: "Entities",
    relations: "Relations",
    packages: "Packages",
    integrityCounts: (unresolved: number, quarantined: number) =>
      `${unresolved} unresolved · ${quarantined} quarantined`,
    integrityPending: "Integrity projection pending",
    noBlockers: "No persisted blocker code",
    milestones: "Persisted milestones",
    noMilestones: "No persisted milestone is available yet.",
    actualWorldObjects: "Actual persisted World objects",
    noWorldObjects: "No persisted World objects yet. No graph is synthesized.",
  },
  ko: {
    sceneView: "실시간 처리 장면",
    collection: "컬렉션 인텔리전스",
    sourceSummary: (clusters: number, pages: number) =>
      `클러스터 ${clusters}개 · ${pages}페이지`,
    awaitingSnapshot: "테넌트 범위 장면 스냅샷을 기다리는 중",
    clusterFiles: (count: number) => `파일 ${count}개`,
    noClusters: "아직 저장된 클러스터 투영이 없습니다.",
    pages: "페이지 레지스터",
    page: (number: number) => `${number}페이지`,
    noPages: "아직 저장된 페이지가 없습니다.",
    unrouted: "경로 미지정",
    pageIntelligence: "페이지 인텔리전스 캔버스",
    awaitingPage: "저장된 페이지를 기다리는 중",
    previewAlt: (number: number) => `${number}페이지 인증 파생 미리보기`,
    previewUnavailable: "미리보기가 아직 생성되지 않았습니다",
    previewUnavailableBody:
      "상태와 경로는 계속 표시하며, 무결성 검사를 통과한 파생 이미지가 있을 때만 원문 화면을 엽니다.",
    actualProof: "실제 원문 근거",
    proofCropAlt: "저장된 검증 레코드에서 생성한 PII 마스킹 근거 크롭",
    evidenceLabels: {
      regions: "영역",
      blocks: "블록",
      tables: "표",
      proofs: "근거",
    },
    knowledge: "지식 형성",
    structureBody: "저장된 영역, 블록, 표, 마일스톤만 표시합니다.",
    worldBody: "저장된 World ID만 표시합니다.",
    regions: "영역",
    blocks: "블록",
    tables: "표",
    notes: "노트",
    entities: "엔터티",
    relations: "관계",
    packages: "패키지",
    integrityCounts: (unresolved: number, quarantined: number) =>
      `미해결 ${unresolved}건 · 격리 ${quarantined}건`,
    integrityPending: "무결성 투영 대기 중",
    noBlockers: "저장된 차단 코드 없음",
    milestones: "저장된 마일스톤",
    noMilestones: "아직 저장된 마일스톤이 없습니다.",
    actualWorldObjects: "실제 저장된 World 객체",
    noWorldObjects: "저장된 World 객체가 없습니다. 그래프를 합성하지 않습니다.",
  },
} as const;
