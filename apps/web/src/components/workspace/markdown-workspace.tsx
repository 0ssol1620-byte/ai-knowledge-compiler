"use client";

import {
  Check,
  Code,
  Eye,
  FileMagnifyingGlass,
  FloppyDisk,
  GitDiff,
  LinkSimple,
  NotePencil,
  PushPin,
  Sparkle,
  UserCircle,
  Warning,
} from "@phosphor-icons/react";
import clsx from "clsx";
import dynamic from "next/dynamic";
import { useState } from "react";

import { SafeMarkdown } from "@/components/safe-markdown";
import { measuredQualityBreakdown } from "@/lib/quality-evidence";
import type { BlockOrigin, CanonicalBlock, SourceRef } from "@/lib/types";

// §22 — the editor was a static import, so CodeMirror shipped in the workspace
// bundle for every reader who never edits a block. It is only mounted behind
// the Edit affordance, so it loads there too.
const CodeMirror = dynamic(() => import("@uiw/react-codemirror"), {
  ssr: false,
  loading: () => (
    <div className="block-editor-loading" role="status">
      Loading editor…
    </div>
  ),
});

const originPresentation: Record<
  BlockOrigin,
  { label: string; className: string; icon: typeof FileMagnifyingGlass }
> = {
  native_extracted: {
    label: "Extracted",
    className: "origin-native",
    icon: FileMagnifyingGlass,
  },
  ocr_extracted: { label: "OCR Extracted", className: "origin-ocr", icon: Eye },
  rule_reconstructed: {
    label: "Structure Rebuilt",
    className: "origin-structure",
    icon: Code,
  },
  ai_reconstructed: {
    label: "AI Reconstructed",
    className: "origin-ai",
    icon: Sparkle,
  },
  ai_summarized: { label: "AI Summary", className: "origin-ai", icon: Sparkle },
  ai_inferred: {
    label: "AI Inference",
    className: "origin-inference",
    icon: Warning,
  },
  user_edited: {
    label: "User Edited",
    className: "origin-user",
    icon: UserCircle,
  },
};

type EvidenceAction = "focus" | "blur" | "select" | "pin";

interface PinnedEvidence {
  block: CanonicalBlock;
  source: SourceRef;
}

export function MarkdownWorkspace({
  blocks,
  selectedBlockId,
  onSelectBlock,
  onSave,
  onCompareModel,
  onEvidenceInteraction,
  qualityEvidence,
}: {
  blocks: CanonicalBlock[];
  selectedBlockId?: string;
  onSelectBlock: (blockId: string) => void;
  onSave?: (block: CanonicalBlock, markdown: string) => Promise<void>;
  onCompareModel?: (block: CanonicalBlock) => void;
  onEvidenceInteraction?: (
    block: CanonicalBlock,
    source: SourceRef,
    action: EvidenceAction,
  ) => void;
  qualityEvidence?: Record<string, unknown> | null;
}) {
  const [view, setView] = useState<"preview" | "source">("preview");
  const [editingId, setEditingId] = useState<string>();
  const [draft, setDraft] = useState("");
  const [savingId, setSavingId] = useState<string>();
  const [saveError, setSaveError] = useState<string>();
  const [pinnedEvidence, setPinnedEvidence] = useState<PinnedEvidence[]>([]);
  const quality = measuredQualityBreakdown(qualityEvidence);

  function pinEvidence(block: CanonicalBlock, source: SourceRef) {
    const key = evidenceKey(block, source);
    setPinnedEvidence((current) => {
      if (
        current.some((item) => evidenceKey(item.block, item.source) === key)
      ) {
        return current.filter(
          (item) => evidenceKey(item.block, item.source) !== key,
        );
      }
      return [...current.slice(-1), { block, source }];
    });
    onEvidenceInteraction?.(block, source, "pin");
  }

  return (
    <section
      className="workspace-panel markdown-panel"
      aria-label="Markdown output"
    >
      <header className="workspace-panel-header">
        <div>
          <strong>Markdown</strong>
          <span>{blocks.length} completed blocks</span>
        </div>
        <div className="segmented-control" aria-label="Markdown display">
          <button
            type="button"
            className={view === "preview" ? "active" : undefined}
            aria-pressed={view === "preview"}
            onClick={() => setView("preview")}
          >
            <Eye size={14} aria-hidden="true" />
            Preview
          </button>
          <button
            type="button"
            className={view === "source" ? "active" : undefined}
            aria-pressed={view === "source"}
            onClick={() => setView("source")}
          >
            <Code size={14} aria-hidden="true" />
            Source
          </button>
        </div>
      </header>

      {(quality.overall !== undefined || quality.metrics.length > 0) && (
        <details className="quality-breakdown">
          <summary>
            {quality.overall !== undefined
              ? `Quality score ${quality.overall.toFixed(1)} / 100`
              : "Measured quality breakdown"}
          </summary>
          <dl>
            {quality.metrics.map((metric) => (
              <div key={metric.key}>
                <dt>{metric.label}</dt>
                <dd>{metric.score.toFixed(1)} / 100</dd>
              </div>
            ))}
          </dl>
          <small>
            Only backend measurements present for this page are shown.
          </small>
        </details>
      )}

      {pinnedEvidence.length > 0 && (
        <section
          className="evidence-diff"
          aria-label="Pinned evidence comparison"
        >
          <header>
            <div>
              <strong>Pinned evidence</strong>
              <span>
                {pinnedEvidence.length === 1
                  ? "Pin one more source to compare."
                  : "Side-by-side source comparison"}
              </span>
            </div>
            <button
              type="button"
              className="edit-block-button"
              onClick={() => setPinnedEvidence([])}
            >
              Clear
            </button>
          </header>
          <div>
            {pinnedEvidence.map(({ block, source }) => (
              <article key={evidenceKey(block, source)}>
                <strong>
                  Page {source.page_number} · {block.type}
                </strong>
                <code>
                  {source.bbox1000
                    ? `bbox1000 ${source.bbox1000.join(", ")}`
                    : "Page-level evidence"}
                </code>
                <p>{block.source_text || "No extracted source text stored."}</p>
              </article>
            ))}
          </div>
        </section>
      )}

      <div className="block-stream">
        {blocks.map((block) => {
          const active = block.id === selectedBlockId;
          const origin = originPresentation[block.origin];
          const OriginIcon = origin.icon;
          const isEditing = editingId === block.id;
          return (
            <article
              className={clsx(
                "result-block",
                active && "active",
                isEditing && "editing",
              )}
              key={block.id}
              onMouseEnter={() => {
                const source = block.source_refs[0];
                if (source) onEvidenceInteraction?.(block, source, "focus");
              }}
              onMouseLeave={() => {
                const source = block.source_refs[0];
                if (source) onEvidenceInteraction?.(block, source, "blur");
              }}
            >
              <button
                type="button"
                className="result-block-select"
                aria-label={`Link ${block.type} block ${block.order} to source`}
                onClick={() => onSelectBlock(block.id)}
              >
                <span className="block-type">{block.type}</span>
                <span className={clsx("origin-badge", origin.className)}>
                  <OriginIcon size={12} weight="fill" aria-hidden="true" />
                  {origin.label}
                </span>
                {block.quality_flags.length > 0 && (
                  <span className="warning-badge">
                    <Warning size={12} weight="fill" aria-hidden="true" />
                    Review
                  </span>
                )}
              </button>

              {isEditing ? (
                <div className="block-editor">
                  <CodeMirror
                    value={draft}
                    minHeight="128px"
                    basicSetup={{
                      lineNumbers: true,
                      foldGutter: false,
                      highlightActiveLine: true,
                    }}
                    onChange={setDraft}
                    aria-label={`${block.type} Markdown editor`}
                  />
                  <div className="editor-actions">
                    <span>revision {block.revision} · optimistic lock</span>
                    <button
                      type="button"
                      className="secondary-button compact"
                      disabled={savingId === block.id}
                      onClick={() => setEditingId(undefined)}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="primary-button compact"
                      disabled={!onSave || savingId === block.id}
                      title={
                        onSave
                          ? "Save this revision."
                          : "Changes are disabled in demo mode."
                      }
                      onClick={() => {
                        if (!onSave) return;
                        setSavingId(block.id);
                        setSaveError(undefined);
                        void onSave(block, draft)
                          .then(() => setEditingId(undefined))
                          .catch((reason: unknown) => {
                            setSaveError(
                              reason instanceof Error
                                ? reason.message
                                : "The change could not be saved.",
                            );
                          })
                          .finally(() => setSavingId(undefined));
                      }}
                    >
                      <FloppyDisk size={14} aria-hidden="true" />
                      {savingId === block.id ? "Saving..." : "Save change"}
                    </button>
                  </div>
                  {saveError && (
                    <p className="form-error" role="alert">
                      {saveError}
                    </p>
                  )}
                </div>
              ) : (
                <>
                  {view === "preview" ? (
                    <SafeMarkdown source={block.markdown} />
                  ) : (
                    <pre className="markdown-source">
                      <code>{block.markdown}</code>
                    </pre>
                  )}
                  <footer className="block-footer">
                    <div
                      className="evidence-chips"
                      aria-label={`${block.source_refs.length} evidence sources`}
                    >
                      {block.source_refs.length > 0 ? (
                        block.source_refs.map((source, index) => {
                          const key = evidenceKey(block, source);
                          const pinned = pinnedEvidence.some(
                            (item) =>
                              evidenceKey(item.block, item.source) === key,
                          );
                          return (
                            <span className="evidence-chip-group" key={key}>
                              <button
                                type="button"
                                className="evidence-chip"
                                aria-label={`Evidence ${index + 1}, p.${
                                  source.page_number
                                }${
                                  source.bbox1000
                                    ? `, bbox ${source.bbox1000.join(", ")}`
                                    : ""
                                }. Shift Enter to pin.`}
                                aria-keyshortcuts="Shift+Enter"
                                onMouseEnter={() =>
                                  onEvidenceInteraction?.(
                                    block,
                                    source,
                                    "focus",
                                  )
                                }
                                onMouseLeave={() =>
                                  onEvidenceInteraction?.(block, source, "blur")
                                }
                                onFocus={() =>
                                  onEvidenceInteraction?.(
                                    block,
                                    source,
                                    "focus",
                                  )
                                }
                                onBlur={() =>
                                  onEvidenceInteraction?.(block, source, "blur")
                                }
                                onKeyDown={(event) => {
                                  if (event.key === "Enter" && event.shiftKey) {
                                    event.preventDefault();
                                    pinEvidence(block, source);
                                  }
                                }}
                                onClick={(event) => {
                                  if (event.shiftKey) {
                                    pinEvidence(block, source);
                                    return;
                                  }
                                  onSelectBlock(block.id);
                                  onEvidenceInteraction?.(
                                    block,
                                    source,
                                    "select",
                                  );
                                }}
                              >
                                <LinkSimple
                                  size={13}
                                  weight="bold"
                                  aria-hidden="true"
                                />
                                p.{source.page_number}
                                {source.bbox1000 && (
                                  <span>{source.bbox1000.join(", ")}</span>
                                )}
                              </button>
                              <button
                                type="button"
                                className="evidence-pin"
                                aria-label={`${
                                  pinned ? "Unpin" : "Pin"
                                } evidence ${index + 1} on page ${
                                  source.page_number
                                }`}
                                aria-pressed={pinned}
                                onClick={() => pinEvidence(block, source)}
                              >
                                <PushPin
                                  size={12}
                                  weight={pinned ? "fill" : "regular"}
                                  aria-hidden="true"
                                />
                              </button>
                            </span>
                          );
                        })
                      ) : (
                        <span className="evidence-missing">
                          No source reference
                        </span>
                      )}
                    </div>
                    <span className="block-quality">
                      {block.quality_flags.length === 0 ? (
                        <>
                          <Check size={13} weight="bold" aria-hidden="true" />
                          {measuredConfidenceLabel(block.confidence) ??
                            "No review flags"}
                        </>
                      ) : (
                        <>
                          <Warning size={13} weight="fill" aria-hidden="true" />
                          {block.quality_flags.join(", ")}
                        </>
                      )}
                    </span>
                    {onCompareModel && (
                      <button
                        type="button"
                        className="edit-block-button"
                        onClick={() => onCompareModel(block)}
                      >
                        <GitDiff size={14} aria-hidden="true" />
                        Compare rerun
                      </button>
                    )}
                    <button
                      type="button"
                      className="edit-block-button"
                      onClick={() => {
                        setSaveError(undefined);
                        setDraft(block.markdown);
                        setEditingId(block.id);
                      }}
                    >
                      <NotePencil size={14} aria-hidden="true" />
                      Edit
                    </button>
                  </footer>
                </>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function evidenceKey(block: CanonicalBlock, source: SourceRef): string {
  return [
    block.id,
    source.document_version_id,
    source.page_number,
    source.bbox1000?.join(",") ?? "page",
  ].join(":");
}

function measuredConfidenceLabel(
  value: number | undefined,
): string | undefined {
  if (
    value === undefined ||
    !Number.isFinite(value) ||
    value < 0 ||
    value > 100
  ) {
    return undefined;
  }
  const score = value <= 1 ? value * 100 : value;
  return `Measured confidence ${score.toFixed(1)} / 100`;
}
