"use client";

import { useEffect, useMemo, useState } from "react";

import { ProcessingSceneWorkbench } from "@/components/processing-scene-workbench";
import { DART_PUBLIC_FIXTURE } from "@/lib/dart-public-fixture";
import type {
  CollectionEvent,
  CollectionScene,
} from "@/lib/collection-runtime-client";
import type { StructaraLocale } from "@/lib/locale";
import { projectProcessingScene } from "@/lib/processing-scene-model";

const COLLECTION_ID = "public-dart-replay-20260730000413";
const PAGE_ID = "public-dart-page-13";

function event(
  sequence: number,
  eventType: CollectionEvent["event_type"],
  payload: Record<string, string | number | string[]>,
): CollectionEvent {
  return {
    event_id: `public-dart-event-${String(sequence).padStart(2, "0")}`,
    collection_id: COLLECTION_ID,
    job_id: "public-dart-job",
    sequence,
    event_type: eventType,
    timestamp: `2026-07-30T09:${String(sequence).padStart(2, "0")}:00Z`,
    payload: { collection_id: COLLECTION_ID, ...payload },
    schema_version: "1.0",
  } as CollectionEvent;
}

const REPLAY_EVENTS: CollectionEvent[] = [
  event(1, "collection.files.planned.v1", {
    total_files: 12,
    total_bytes: 9_204_016,
    status: "ready",
  }),
  event(2, "preflight.cluster.created.v1", {
    cluster_id: "public-filings",
    category: "public-filing",
    member_files: 1,
    feature_records: 31,
  }),
  event(3, "estimate.final.ready.v1", {
    detail_ref: "public-replay:estimate",
  }),
  event(4, "processing.started.v1", {
    processing_job_id: "public-dart-job",
  }),
  event(5, "page.route.selected.v1", {
    page_id: PAGE_ID,
    page_number1: 13,
    route: "native-xbrl-table",
    worker_lane_id: "lane-native",
  }),
  event(6, "region.route.selected.v1", {
    page_id: PAGE_ID,
    region_id: "income-statement",
  }),
  event(7, "block.completed.v1", {
    page_id: PAGE_ID,
    block_id: "revenue-row",
  }),
  event(8, "table.reconstructed.v1", {
    page_id: PAGE_ID,
    table_id: "comprehensive-income",
  }),
  event(9, "numeric.authority.verified.v1", {
    page_id: PAGE_ID,
  }),
  event(10, "note.created.v1", {
    note_id: "jtc-2026-q1-revenue",
    note_count: 1,
  }),
  event(11, "entity.resolved.v1", {
    entity_id: "jtc",
    entity_count: 1,
  }),
  event(12, "relation.created.v1", {
    relation_id: "jtc-reported-revenue",
    relation_count: 1,
  }),
  event(13, "architecture.folder.created.v1", {
    folder_id: "financial-statements",
    folder_count: 1,
  }),
  event(14, "package.validated.v1", {
    package_manifest_id: "dart-public-package",
    detail_ref: `receipt:${DART_PUBLIC_FIXTURE.receiptNumber}`,
  }),
  event(15, "package.signed.v1", {
    package_manifest_id: "dart-public-package",
    signature_status: "signed",
  }),
];

const PROJECTION = projectProcessingScene(COLLECTION_ID, REPLAY_EVENTS).scene;

const REPLAY_SCENE: CollectionScene = {
  collection_id: COLLECTION_ID,
  collection_status: "COMPLETED",
  manifest_revision: 1,
  sequence: 15,
  total_pages: 18,
  projected_page_count: 1,
  route_state_counts: { "native-xbrl-table": 1 },
  clusters: [
    {
      cluster_id: "public-filings",
      strategy: "public-filing",
      member_count: 1,
      representative_file_ids: ["jtc-2026-q1"],
      outlier_count: 0,
    },
  ],
  pages: [
    {
      page_id: PAGE_ID,
      document_id: "jtc-2026-q1",
      document_version_id: "opendart-20260730000413",
      page_number: 13,
      status: "authority_verified",
      route: "native-xbrl-table",
      preview_ref: "/product/processing.webp",
      finding_count: 0,
    },
  ],
  knowledge: {
    note_ids: ["jtc-2026-q1-revenue"],
    entity_ids: ["jtc"],
    relation_ids: ["jtc-reported-revenue"],
    package_ids: ["dart-public-package"],
    note_count: 1,
    entity_count: 1,
    relation_count: 1,
    package_count: 1,
  },
  integrity: {
    file_status_counts: { verified: 1 },
    verification_status_counts: { authority_verified: 1 },
    authority_mapping_status_counts: { mapped: 1 },
    package_status_counts: { signed: 1 },
    unresolved_count: 0,
    quarantined_count: 0,
    blocker_codes: [],
  },
  scene_hash: PROJECTION.sceneHash,
};

const COPY = {
  en: {
    label: "02 · Live collection processing",
    title: "A collection becomes inspectable knowledge, event by event.",
    body: "Files, pages, routes, blocks, verification, notes, relations, and the final package remain visible in one customer-facing scene.",
    disclosure: `Frozen contract replay · OpenDART receipt ${DART_PUBLIC_FIXTURE.receiptNumber} · no simulated timer`,
  },
  ko: {
    label: "02 · 실시간 컬렉션 처리",
    title: "컬렉션이 이벤트 단위로 검증 가능한 지식이 됩니다.",
    body: "파일, 페이지, 처리 경로, 블록, 검증, 노트, 관계와 최종 패키지를 하나의 고객용 장면에서 확인합니다.",
    disclosure: `고정된 계약 리플레이 · OpenDART 접수번호 ${DART_PUBLIC_FIXTURE.receiptNumber} · 가상 타이머 없음`,
  },
} as const;

export function HomepageProcessingScene({
  locale,
}: {
  locale: StructaraLocale;
}) {
  const [mobile, setMobile] = useState(false);
  const copy = COPY[locale];
  const projection = useMemo(() => PROJECTION, []);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(max-width: 760px)");
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return (
    <section
      className="folynta-processing-scene folynta-scene"
      data-scene="02-processing"
      data-replay="frozen-public-contract"
      data-truth-class="registered-public-fixture-replay-t0"
    >
      <header className="folynta-section-heading">
        <p>{copy.label}</p>
        <h2>{copy.title}</h2>
        <span>{copy.body}</span>
      </header>
      <div className="folynta-processing-frame">
        <div className="folynta-processing-disclosure">{copy.disclosure}</div>
        <ProcessingSceneWorkbench
          scene={REPLAY_SCENE}
          projection={projection}
          locale={locale}
          mobile={mobile}
        />
      </div>
    </section>
  );
}
