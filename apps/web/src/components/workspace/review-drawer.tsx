"use client";

import {
  ArrowClockwise,
  Check,
  CheckCircle,
  FileMagnifyingGlass,
  NotePencil,
  Prohibit,
  StackSimple,
  Warning,
  X,
} from "@phosphor-icons/react";
import clsx from "clsx";
import { useId, useMemo, useRef, useState } from "react";

import type {
  ReviewItem,
  ReviewResolution,
  ReviewScopePreview,
} from "@/lib/types";
import { useDialogFocus } from "@/lib/use-dialog-focus";

const severityOrder: Record<ReviewItem["severity"], number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
};

export function ReviewDrawer({
  items,
  open,
  onClose,
  onSelectEvidence,
  onResolve,
  onReprocess,
  onPreviewRule,
  onApplyRule,
}: {
  items: ReviewItem[];
  open: boolean;
  onClose: () => void;
  onSelectEvidence: (item: ReviewItem) => void;
  onResolve?: (item: ReviewItem, resolution: ReviewResolution) => Promise<void>;
  onReprocess?: (item: ReviewItem) => Promise<void>;
  onPreviewRule?: (item: ReviewItem) => Promise<ReviewScopePreview>;
  onApplyRule?: (
    item: ReviewItem,
    action: "accept" | "adopt_source" | "reject",
    previewSha256: string,
  ) => Promise<void>;
}) {
  const [resolved, setResolved] = useState<string[]>([]);
  const [pendingId, setPendingId] = useState<string>();
  const [error, setError] = useState<string>();
  const [directEdits, setDirectEdits] = useState<Record<string, string>>({});
  const [scopePreviews, setScopePreviews] = useState<
    Record<string, ReviewScopePreview>
  >({});
  const titleId = useId();
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useDialogFocus<HTMLElement>({
    open,
    onClose,
    initialFocusRef: closeButtonRef,
  });
  const sorted = useMemo(
    () =>
      [...items].sort(
        (left, right) =>
          severityOrder[right.severity] - severityOrder[left.severity],
      ),
    [items],
  );
  const openCount = items.filter(
    (item) => item.status !== "resolved" && !resolved.includes(item.id),
  ).length;

  function resolve(item: ReviewItem, resolution: ReviewResolution) {
    if (!onResolve) return;
    setPendingId(item.id);
    setError(undefined);
    void onResolve(item, resolution)
      .then(() => setResolved((current) => [...current, item.id]))
      .catch((reason: unknown) => {
        setError(
          reason instanceof Error
            ? reason.message
            : "The review decision could not be saved.",
        );
      })
      .finally(() => setPendingId(undefined));
  }

  function previewRule(item: ReviewItem) {
    if (!onPreviewRule) return;
    setPendingId(item.id);
    setError(undefined);
    void onPreviewRule(item)
      .then((preview) =>
        setScopePreviews((current) => ({ ...current, [item.id]: preview })),
      )
      .catch((reason: unknown) => {
        setError(
          reason instanceof Error
            ? reason.message
            : "The document rule scope could not be previewed.",
        );
      })
      .finally(() => setPendingId(undefined));
  }

  function applyRule(
    item: ReviewItem,
    action: "accept" | "adopt_source" | "reject",
  ) {
    const preview = scopePreviews[item.id];
    if (!onApplyRule || !preview) return;
    setPendingId(item.id);
    setError(undefined);
    void onApplyRule(item, action, preview.preview_sha256)
      .then(() =>
        setResolved((current) => [
          ...new Set([...current, ...preview.review_ids]),
        ]),
      )
      .catch((reason: unknown) => {
        setScopePreviews((current) => {
          const next = { ...current };
          delete next[item.id];
          return next;
        });
        setError(
          reason instanceof Error
            ? reason.message
            : "The document rule could not be applied.",
        );
      })
      .finally(() => setPendingId(undefined));
  }

  return (
    <aside
      ref={drawerRef}
      className={clsx("review-drawer", open && "open")}
      role="dialog"
      aria-modal={open ? "true" : undefined}
      aria-labelledby={titleId}
      aria-hidden={!open}
      inert={open ? undefined : true}
      tabIndex={-1}
    >
      <header>
        <div>
          <span className="review-title-icon">
            <Warning size={17} weight="fill" aria-hidden="true" />
          </span>
          <div>
            <strong id={titleId}>Review queue</strong>
            <span>{openCount} items need a decision</span>
          </div>
        </div>
        <button
          ref={closeButtonRef}
          className="icon-button compact"
          type="button"
          onClick={onClose}
          aria-label="Close review queue"
        >
          <X size={17} aria-hidden="true" />
        </button>
      </header>
      <div className="review-list">
        {sorted.map((item) => {
          const isResolved =
            item.status === "resolved" || resolved.includes(item.id);
          const isPending = pendingId === item.id;
          const directEdit = directEdits[item.id] ?? "";
          const scopePreview = scopePreviews[item.id];
          return (
            <article
              className={clsx("review-card", isResolved && "resolved")}
              key={item.id}
            >
              <div className="review-card-heading">
                <span className={`severity-badge ${item.severity}`}>
                  {severityLabel(item.severity)}
                </span>
                <span>{categoryLabel(item.category)}</span>
              </div>
              <p>{item.message}</p>
              {item.candidates && item.candidates.length > 0 && (
                <div className="candidate-compare" aria-label="A/B candidates">
                  {item.candidates.map((candidate) => (
                    <button
                      type="button"
                      key={candidate.engine}
                      disabled={isResolved || isPending || !onResolve}
                      onClick={() =>
                        resolve(item, {
                          action: "replace",
                          value: candidate.value,
                          note: `Selected candidate ${candidate.engine}`,
                        })
                      }
                    >
                      <span>{candidate.engine}</span>
                      <strong>{candidate.value}</strong>
                      <small>Use this value</small>
                    </button>
                  ))}
                </div>
              )}
              {item.block_id && onResolve && (
                <div className="review-direct-edit">
                  <label htmlFor={`review-edit-${item.id}`}>
                    Direct replacement
                  </label>
                  <textarea
                    id={`review-edit-${item.id}`}
                    rows={4}
                    value={directEdit}
                    disabled={isResolved || isPending}
                    onChange={(event) => {
                      const value = event.currentTarget.value;
                      setDirectEdits((current) => ({
                        ...current,
                        [item.id]: value,
                      }));
                    }}
                  />
                  <button
                    type="button"
                    className="secondary-button compact"
                    disabled={
                      isResolved || isPending || directEdit.trim().length === 0
                    }
                    onClick={() =>
                      resolve(item, {
                        action: "replace",
                        value: directEdit,
                        note: "Direct edit from review queue",
                      })
                    }
                  >
                    <NotePencil size={14} aria-hidden="true" />
                    Apply edit
                  </button>
                </div>
              )}
              {onPreviewRule && onApplyRule && (
                <div className="review-rule-scope">
                  <div>
                    <StackSimple size={15} aria-hidden="true" />
                    <span>
                      <strong>Document-wide rule</strong>
                      <small>
                        Preview matching open items before applying one audited
                        decision.
                      </small>
                    </span>
                  </div>
                  {!scopePreview ? (
                    <button
                      type="button"
                      className="secondary-button compact"
                      disabled={isResolved || isPending}
                      onClick={() => previewRule(item)}
                    >
                      Preview matching items
                    </button>
                  ) : (
                    <div className="review-rule-confirm">
                      <p>
                        {scopePreview.item_count} open{" "}
                        <strong>{categoryLabel(scopePreview.category)}</strong>{" "}
                        items will be resolved. Scope{" "}
                        <code>{scopePreview.preview_sha256.slice(0, 10)}</code>
                      </p>
                      <div>
                        <button
                          type="button"
                          className="secondary-button compact"
                          disabled={isPending}
                          onClick={() => applyRule(item, "adopt_source")}
                        >
                          Adopt each source
                        </button>
                        <button
                          type="button"
                          className="secondary-button compact"
                          disabled={isPending}
                          onClick={() => applyRule(item, "reject")}
                        >
                          Ignore &amp; approve
                        </button>
                        <button
                          type="button"
                          className="primary-button compact"
                          disabled={isPending}
                          onClick={() => applyRule(item, "accept")}
                        >
                          Approve all
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
              <div className="review-actions">
                <button
                  type="button"
                  className="secondary-button compact"
                  onClick={() => onSelectEvidence(item)}
                  disabled={isResolved || isPending}
                >
                  <FileMagnifyingGlass size={14} aria-hidden="true" />
                  Source
                </button>
                <button
                  type="button"
                  className="secondary-button compact"
                  disabled={isResolved || isPending || !onReprocess}
                  onClick={() => {
                    if (!onReprocess) return;
                    setPendingId(item.id);
                    setError(undefined);
                    void onReprocess(item)
                      .catch((reason: unknown) => {
                        setError(
                          reason instanceof Error
                            ? reason.message
                            : "Page reprocessing could not be requested.",
                        );
                      })
                      .finally(() => setPendingId(undefined));
                  }}
                >
                  <ArrowClockwise size={14} aria-hidden="true" />
                  Reprocess
                </button>
                <button
                  type="button"
                  className="secondary-button compact"
                  disabled={
                    isResolved || isPending || !onResolve || !item.block_id
                  }
                  onClick={() =>
                    resolve(item, {
                      action: "adopt_source",
                      note: "Adopted immutable source text from review queue",
                    })
                  }
                >
                  <Check size={14} aria-hidden="true" />
                  Adopt source
                </button>
                <button
                  type="button"
                  className="secondary-button compact"
                  disabled={isResolved || isPending || !onResolve}
                  onClick={() =>
                    resolve(item, {
                      action: "reject",
                      note: "Ignored from review queue",
                    })
                  }
                >
                  <Prohibit size={14} aria-hidden="true" />
                  Ignore &amp; approve
                </button>
                <button
                  type="button"
                  className="primary-button compact"
                  disabled={isResolved || isPending || !onResolve}
                  onClick={() =>
                    resolve(item, {
                      action: "accept",
                      note: "Approved from review queue",
                    })
                  }
                >
                  {isResolved ? (
                    <CheckCircle size={14} weight="fill" aria-hidden="true" />
                  ) : (
                    <Check size={14} aria-hidden="true" />
                  )}
                  {isResolved
                    ? "Resolved"
                    : isPending
                      ? "Saving..."
                      : "Approve"}
                </button>
              </div>
            </article>
          );
        })}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </aside>
  );
}

function severityLabel(severity: ReviewItem["severity"]): string {
  return {
    critical: "Critical",
    high: "High risk",
    medium: "Review",
    low: "Notice",
  }[severity];
}

function categoryLabel(category: string): string {
  return (
    {
      number_mismatch: "Number mismatch",
      merged_cell: "Complex table",
      unsupported_claim: "Unsupported claim",
      reading_order: "Reading order",
    }[category] ?? category
  );
}
