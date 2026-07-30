"use client";

import {
  ArrowClockwise,
  Check,
  GitDiff,
  Warning,
  X,
} from "@phosphor-icons/react";
import clsx from "clsx";
import { useId, useRef, useState, type KeyboardEvent } from "react";

import { ApiError } from "@/lib/api-client";
import type {
  BlockModelMergeRequest,
  BlockModelMergeResponse,
  CanonicalBlock,
} from "@/lib/types";
import { useDialogFocus } from "@/lib/use-dialog-focus";

type MergeChoice = "base" | "user" | "new-model" | "auto-merge" | "custom";

interface StableKey {
  fingerprint: string;
  key: string;
}

function stableIdempotencyKey(
  current: StableKey | undefined,
  fingerprint: string,
): StableKey {
  return current?.fingerprint === fingerprint
    ? current
    : { fingerprint, key: crypto.randomUUID() };
}

export function ModelMergeDialog({
  block,
  open,
  onClose,
  onPreview,
  onApply,
  onStale,
}: {
  block: CanonicalBlock;
  open: boolean;
  onClose: () => void;
  onPreview: (
    block: CanonicalBlock,
    request: BlockModelMergeRequest,
    idempotencyKey: string,
  ) => Promise<BlockModelMergeResponse>;
  onApply: (
    block: CanonicalBlock,
    preview: BlockModelMergeResponse,
    resolvedMarkdown: string,
    idempotencyKey: string,
  ) => Promise<void>;
  onStale: () => void;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const paneRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const previewKeyRef = useRef<StableKey | undefined>(undefined);
  const applyKeyRef = useRef<StableKey | undefined>(undefined);
  const [baseRevision, setBaseRevision] = useState(String(block.revision));
  const [modelRevision, setModelRevision] = useState("");
  const [newModelMarkdown, setNewModelMarkdown] = useState("");
  const [preview, setPreview] = useState<BlockModelMergeResponse>();
  const [choice, setChoice] = useState<MergeChoice>();
  const [resolvedMarkdown, setResolvedMarkdown] = useState("");
  const [pending, setPending] = useState<"preview" | "apply">();
  const [error, setError] = useState<string>();
  const [announcement, setAnnouncement] = useState("");
  const dialogRef = useDialogFocus<HTMLElement>({
    open,
    onClose,
    initialFocusRef: closeButtonRef,
  });

  if (!open) return null;

  function handleFailure(reason: unknown, fallback: string) {
    if (reason instanceof ApiError && [409, 412].includes(reason.status)) {
      setPreview(undefined);
      setChoice(undefined);
      setResolvedMarkdown("");
      setError(
        "This block changed after the comparison opened. The latest revision was refreshed; run the comparison again.",
      );
      onStale();
      return;
    }
    setError(reason instanceof Error ? reason.message : fallback);
  }

  function selectChoice(next: Exclude<MergeChoice, "custom">, value: string) {
    setChoice(next);
    setResolvedMarkdown(value);
    setAnnouncement(`${choiceLabel(next)} selected for explicit apply.`);
  }

  function movePaneFocus(
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      return;
    }
    event.preventDefault();
    const last = paneRefs.current.length - 1;
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? last
          : event.key === "ArrowRight"
            ? (index + 1) % paneRefs.current.length
            : (index - 1 + paneRefs.current.length) % paneRefs.current.length;
    paneRefs.current[next]?.focus();
  }

  const panes = preview
    ? [
        { id: "base" as const, label: "Base", value: preview.base },
        { id: "user" as const, label: "User", value: preview.user },
        {
          id: "new-model" as const,
          label: "New model",
          value: preview.new_model,
        },
      ]
    : [];

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !pending) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className="modal-card model-merge-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        aria-busy={Boolean(pending)}
        tabIndex={-1}
      >
        <div className="modal-heading">
          <div>
            <p className="eyebrow">Revision-safe comparison</p>
            <h2 id={titleId}>Resolve model changes</h2>
            <p id={descriptionId}>
              Compare the saved base, your current text, and a new model
              proposal. Nothing is applied until you choose and confirm.
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className="icon-button"
            onClick={onClose}
            disabled={Boolean(pending)}
            aria-label="Close model comparison"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            const parsedBaseRevision = Number(baseRevision);
            if (
              !Number.isInteger(parsedBaseRevision) ||
              parsedBaseRevision < 1 ||
              !modelRevision.trim() ||
              !newModelMarkdown.trim()
            ) {
              setError(
                "Enter a valid base revision, model revision, and model Markdown.",
              );
              return;
            }
            const request: BlockModelMergeRequest = {
              base_revision: parsedBaseRevision,
              model_revision: modelRevision.trim(),
              new_model_markdown: newModelMarkdown,
              apply_non_conflicting: false,
            };
            const fingerprint = JSON.stringify(request);
            previewKeyRef.current = stableIdempotencyKey(
              previewKeyRef.current,
              fingerprint,
            );
            setPending("preview");
            setError(undefined);
            setAnnouncement("");
            void onPreview(block, request, previewKeyRef.current.key)
              .then((response) => {
                setPreview(response);
                setChoice(undefined);
                setResolvedMarkdown("");
                applyKeyRef.current = undefined;
                setAnnouncement(
                  `Comparison ready. ${response.conflict_count} conflicts found. Choose a result before applying.`,
                );
                window.requestAnimationFrame(() =>
                  paneRefs.current[0]?.focus(),
                );
              })
              .catch((reason: unknown) =>
                handleFailure(reason, "The comparison could not be prepared."),
              )
              .finally(() => setPending(undefined));
          }}
        >
          <div className="model-merge-inputs">
            <label className="field">
              <span>Base revision</span>
              <input
                type="number"
                min={1}
                step={1}
                value={baseRevision}
                onChange={(event) => {
                  setBaseRevision(event.currentTarget.value);
                  setPreview(undefined);
                }}
                disabled={Boolean(pending)}
              />
            </label>
            <label className="field">
              <span>Model revision</span>
              <input
                value={modelRevision}
                onChange={(event) => {
                  setModelRevision(event.currentTarget.value);
                  setPreview(undefined);
                }}
                placeholder="provider/model@revision"
                disabled={Boolean(pending)}
              />
            </label>
          </div>
          <label className="field">
            <span>New model Markdown</span>
            <textarea
              rows={7}
              value={newModelMarkdown}
              onChange={(event) => {
                setNewModelMarkdown(event.currentTarget.value);
                setPreview(undefined);
              }}
              disabled={Boolean(pending)}
            />
          </label>
          <div className="model-merge-preview-action">
            <span>
              Current block revision: {block.revision}. Preview is read-only.
            </span>
            <button
              type="submit"
              className="secondary-button"
              disabled={Boolean(pending)}
            >
              <GitDiff size={16} aria-hidden="true" />
              {pending === "preview" ? "Comparing..." : "Compare revisions"}
            </button>
          </div>
        </form>

        {preview && (
          <div className="model-merge-resolution">
            <div className="model-merge-status">
              <span className={clsx(preview.conflict_count > 0 && "conflict")}>
                {preview.conflict_count > 0 ? (
                  <Warning size={15} weight="fill" aria-hidden="true" />
                ) : (
                  <Check size={15} weight="bold" aria-hidden="true" />
                )}
                {preview.conflict_count} conflicts
              </span>
              <span>
                Base r{preview.base_revision} / current r
                {preview.current_revision}
              </span>
            </div>
            <div
              className="model-merge-panes"
              role="listbox"
              aria-label="Choose a revision result"
              aria-orientation="horizontal"
            >
              {panes.map((pane, index) => (
                <button
                  ref={(element) => {
                    paneRefs.current[index] = element;
                  }}
                  key={pane.id}
                  type="button"
                  className={clsx(
                    "model-merge-pane",
                    choice === pane.id && "selected",
                  )}
                  role="option"
                  aria-selected={choice === pane.id}
                  tabIndex={index === 0 ? 0 : -1}
                  onKeyDown={(event) => movePaneFocus(event, index)}
                  onClick={() => selectChoice(pane.id, pane.value)}
                >
                  <span>{pane.label}</span>
                  <small>{choiceLabel(pane.id)}</small>
                  <pre>{pane.value}</pre>
                </button>
              ))}
            </div>
            {preview.merged !== null && (
              <button
                type="button"
                className={clsx(
                  "secondary-button model-merge-auto",
                  choice === "auto-merge" && "selected",
                )}
                aria-pressed={choice === "auto-merge"}
                onClick={() =>
                  selectChoice("auto-merge", preview.merged ?? preview.user)
                }
              >
                <ArrowClockwise size={16} aria-hidden="true" />
                Use backend auto-merge result
              </button>
            )}
            <label className="field model-merge-resolved">
              <span>Resolved Markdown</span>
              <textarea
                aria-label="Resolved Markdown"
                rows={8}
                value={resolvedMarkdown}
                disabled={!choice || Boolean(pending)}
                onChange={(event) => {
                  setChoice("custom");
                  setResolvedMarkdown(event.currentTarget.value);
                }}
              />
              <small>
                Selected result: {choice ? choiceLabel(choice) : "none"}
              </small>
            </label>
          </div>
        )}

        {error && (
          <p className="form-error model-merge-error" role="alert">
            {error}
          </p>
        )}
        <p className="visually-hidden" aria-live="polite">
          {announcement}
        </p>
        <div className="modal-actions model-merge-actions">
          <button
            type="button"
            className="secondary-button"
            onClick={onClose}
            disabled={Boolean(pending)}
          >
            Cancel
          </button>
          <button
            type="button"
            className="primary-button"
            disabled={
              !preview ||
              !choice ||
              !resolvedMarkdown.trim() ||
              Boolean(pending)
            }
            onClick={() => {
              if (!preview || !choice || !resolvedMarkdown.trim()) return;
              const fingerprint = `${preview.etag}\u0000${resolvedMarkdown}`;
              applyKeyRef.current = stableIdempotencyKey(
                applyKeyRef.current,
                fingerprint,
              );
              setPending("apply");
              setError(undefined);
              void onApply(
                block,
                preview,
                resolvedMarkdown,
                applyKeyRef.current.key,
              )
                .then(onClose)
                .catch((reason: unknown) =>
                  handleFailure(
                    reason,
                    "The selected resolution could not be applied.",
                  ),
                )
                .finally(() => setPending(undefined));
            }}
          >
            <Check size={16} weight="bold" aria-hidden="true" />
            {pending === "apply" ? "Applying..." : "Apply selected result"}
          </button>
        </div>
      </section>
    </div>
  );
}

function choiceLabel(choice: MergeChoice): string {
  return {
    base: "Use saved base",
    user: "Keep user text",
    "new-model": "Use new model",
    "auto-merge": "Use auto-merge",
    custom: "Custom resolution",
  }[choice];
}
