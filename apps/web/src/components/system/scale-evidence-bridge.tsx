"use client";

import { useEffect, useMemo, useState } from "react";

import { MarkdownWorkspace } from "@/components/workspace/markdown-workspace";
import { PageRail } from "@/components/workspace/page-rail";
import type { ScaleEvidenceServerConfig } from "@/lib/scale-evidence-server";
import type { CanonicalBlock, PageSummary } from "@/lib/types";

type ScaleProfile =
  | "processing_ui_1000_pages"
  | "workspace_10000_blocks"
  | "graph_5000_nodes";

type ScaleEvidence = {
  ready: boolean;
  classification: "harness_contract";
  nonproduction_only: true;
  release_gate_closed: false;
  profile: ScaleProfile;
  target_revision: string;
  fixture_sha256: string;
  dataset: Record<string, number>;
  virtualization: {
    strategy: "bounded_window";
    total_items: number;
    rendered_items: number;
    window_start: number;
    window_end: number;
    overscan: number;
    renderer_component:
      | "PageRail"
      | "MarkdownWorkspace"
      | "BoundedKnowledgeGraph";
    data_contract: "PageSummary[]" | "CanonicalBlock[]" | "KnowledgeGraphNode[]";
  };
};

declare global {
  interface Window {
    __AKC_SCALE_EVIDENCE__?: ScaleEvidence;
  }
}

const PROFILE_SPEC: Record<
  ScaleProfile,
  {
    key: "pages" | "blocks" | "graph_nodes";
    total: number;
    rendered: number;
    renderer: ScaleEvidence["virtualization"]["renderer_component"];
    contract: ScaleEvidence["virtualization"]["data_contract"];
  }
> = {
  processing_ui_1000_pages: {
    key: "pages",
    total: 1_000,
    rendered: 72,
    renderer: "PageRail",
    contract: "PageSummary[]",
  },
  workspace_10000_blocks: {
    key: "blocks",
    total: 10_000,
    rendered: 32,
    renderer: "MarkdownWorkspace",
    contract: "CanonicalBlock[]",
  },
  graph_5000_nodes: {
    key: "graph_nodes",
    total: 5_000,
    rendered: 84,
    renderer: "BoundedKnowledgeGraph",
    contract: "KnowledgeGraphNode[]",
  },
};

export function ScaleEvidenceBridge({
  config,
}: {
  config: ScaleEvidenceServerConfig;
}) {
  const [profile, setProfile] = useState<ScaleProfile | undefined>();

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const requested = new URL(window.location.href).searchParams.get(
        "scale_profile",
      );
      setProfile(isScaleProfile(requested) ? requested : undefined);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);
  const evidence = useMemo(
    () =>
      profile
        ? buildScaleEvidenceSpec({
            enabled: config.enabled,
            environment: config.environment,
            profile,
            targetRevision: config.targetRevision,
            fixtureSha256: config.fixtureSha256,
          })
        : undefined,
    [config, profile],
  );

  useEffect(() => {
    if (!evidence) {
      delete window.__AKC_SCALE_EVIDENCE__;
      return;
    }
    let frameOne = 0;
    let frameTwo = 0;
    frameOne = window.requestAnimationFrame(() => {
      frameTwo = window.requestAnimationFrame(() => {
        const root = document.querySelector<HTMLElement>(
          `[data-akc-scale-root="${evidence.profile}"]`,
        );
        if (
          !root ||
          root.dataset.fixtureSha256 !== evidence.fixture_sha256 ||
          root.dataset.rendererComponent !==
            evidence.virtualization.renderer_component ||
          !root.querySelector('[data-akc-renderer-bound="true"]')
        ) {
          delete window.__AKC_SCALE_EVIDENCE__;
          return;
        }
        window.__AKC_SCALE_EVIDENCE__ = { ...evidence, ready: true };
        root.dataset.ready = "true";
      });
    });
    return () => {
      window.cancelAnimationFrame(frameOne);
      window.cancelAnimationFrame(frameTwo);
      delete window.__AKC_SCALE_EVIDENCE__;
    };
  }, [evidence]);

  if (!evidence) return null;
  return (
    <div
      className="akc-scale-evidence-fixture"
      data-akc-scale-root={evidence.profile}
      data-fixture-sha256={evidence.fixture_sha256}
      data-renderer-component={evidence.virtualization.renderer_component}
      data-ready="false"
      data-total-items={evidence.virtualization.total_items}
      aria-hidden="true"
    >
      <ScaleCoreRenderer profile={evidence.profile} />
    </div>
  );
}

export function buildScaleEvidenceSpec(input: {
  enabled: string | undefined;
  environment: string | undefined;
  profile: ScaleProfile;
  targetRevision: string | undefined;
  fixtureSha256: string | undefined;
}): ScaleEvidence | undefined {
  if (input.enabled !== "true") return undefined;
  if (!["development", "staging", "performance"].includes(input.environment ?? "")) {
    return undefined;
  }
  if (!/^[0-9a-f]{40}$/.test(input.targetRevision ?? "")) return undefined;
  if (!/^sha256:[0-9a-f]{64}$/.test(input.fixtureSha256 ?? "")) return undefined;
  const spec = PROFILE_SPEC[input.profile];
  return {
    ready: false,
    classification: "harness_contract",
    nonproduction_only: true,
    release_gate_closed: false,
    profile: input.profile,
    target_revision: input.targetRevision!,
    fixture_sha256: input.fixtureSha256!,
    dataset: { [spec.key]: spec.total },
    virtualization: {
      strategy: "bounded_window",
      total_items: spec.total,
      rendered_items: spec.rendered,
      window_start: 0,
      window_end: spec.rendered - 1,
      overscan: 12,
      renderer_component: spec.renderer,
      data_contract: spec.contract,
    },
  };
}

function ScaleCoreRenderer({ profile }: { profile: ScaleProfile }) {
  switch (profile) {
    case "processing_ui_1000_pages":
      return <ProcessingPageScaleAdapter />;
    case "workspace_10000_blocks":
      return <WorkspaceBlockScaleAdapter />;
    case "graph_5000_nodes":
      return <KnowledgeGraphScaleAdapter />;
  }
}

function ProcessingPageScaleAdapter() {
  const pages = useMemo<PageSummary[]>(
    () =>
      Array.from({ length: 1_000 }, (_, index) => ({
        id: `synthetic-page-${index + 1}`,
        page_number: index + 1,
        status: index % 37 === 0 ? "needs_review" : "completed",
        route_profile: index % 5 === 0 ? "visual_ocr_v1" : "native_pdf_v1",
        route_label: index % 5 === 0 ? "OCR" : "Native",
        quality_state: index % 37 === 0 ? "review" : "verified",
        blocks: [],
      })),
    [],
  );
  return (
    <div
      className="akc-scale-core-renderer"
      data-akc-renderer-bound="true"
      data-data-contract="PageSummary[]"
      data-source-total={pages.length}
    >
      <PageRail
        pages={pages}
        selectedPageId={pages[0]!.id}
        onSelect={() => undefined}
      />
    </div>
  );
}

function WorkspaceBlockScaleAdapter() {
  const allBlocks = useMemo<CanonicalBlock[]>(
    () =>
      Array.from({ length: 10_000 }, (_, index) => ({
        id: `synthetic-block-${index + 1}`,
        order: index + 1,
        type: index % 13 === 0 ? "table" : "paragraph",
        markdown: `Synthetic nonproduction block ${index + 1}`,
        source_text: `Synthetic source text ${index + 1}`,
        origin: index % 5 === 0 ? "ocr_extracted" : "native_extracted",
        content_layer: "structured",
        source_refs: [
          {
            document_id: "synthetic-scale-document",
            document_version_id: "synthetic-scale-version",
            page_index: index % 1_000,
            page_number: (index % 1_000) + 1,
            bbox1000: [80, 120, 920, 210],
            source_sha256: "a".repeat(64),
          },
        ],
        quality_flags: [],
        revision: 1,
      })),
    [],
  );
  const visible = allBlocks.slice(0, PROFILE_SPEC.workspace_10000_blocks.rendered);
  return (
    <div
      className="akc-scale-core-renderer"
      data-akc-renderer-bound="true"
      data-data-contract="CanonicalBlock[]"
      data-source-total={allBlocks.length}
      data-window-items={visible.length}
    >
      <MarkdownWorkspace
        blocks={visible}
        selectedBlockId={visible[0]!.id}
        onSelectBlock={() => undefined}
      />
    </div>
  );
}

type KnowledgeGraphNode = {
  id: string;
  label: string;
  type: "Document" | "Entity" | "Metric";
  evidenceRef: string;
};

function KnowledgeGraphScaleAdapter() {
  const allNodes = useMemo<KnowledgeGraphNode[]>(
    () =>
      Array.from({ length: 5_000 }, (_, index) => ({
        id: `synthetic-node-${index + 1}`,
        label: `Synthetic node ${index + 1}`,
        type: index % 3 === 0 ? "Document" : index % 3 === 1 ? "Entity" : "Metric",
        evidenceRef: `synthetic-block-${(index % 10_000) + 1}`,
      })),
    [],
  );
  const visible = allNodes.slice(0, PROFILE_SPEC.graph_5000_nodes.rendered);
  return (
    <div
      className="akc-scale-core-renderer akc-scale-graph-renderer"
      data-akc-renderer-bound="true"
      data-data-contract="KnowledgeGraphNode[]"
      data-source-total={allNodes.length}
      data-window-items={visible.length}
    >
      <table className="knowledge-accessible-table">
        <caption>Bounded synthetic graph node window</caption>
        <thead>
          <tr><th>Node</th><th>Type</th><th>Evidence</th></tr>
        </thead>
        <tbody>
          {visible.map((node) => (
            <tr key={node.id}>
              <th scope="row">{node.label}</th>
              <td>{node.type}</td>
              <td><code>{node.evidenceRef}</code></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function isScaleProfile(value: string | null): value is ScaleProfile {
  return value !== null && Object.hasOwn(PROFILE_SPEC, value);
}
