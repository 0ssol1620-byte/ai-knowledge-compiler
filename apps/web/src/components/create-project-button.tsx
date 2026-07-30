"use client";

import { Plus, X } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useId, useRef, useState } from "react";

import { createProject } from "@/lib/api-client";
import { useDialogFocus } from "@/lib/use-dialog-focus";

const DEMO_MODE = process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true";

export function CreateProjectButton({
  variant = "primary",
  label,
}: {
  variant?: "primary" | "secondary" | "inline";
  label?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();
  const titleId = useId();
  const queryClient = useQueryClient();
  const nameInputRef = useRef<HTMLInputElement>(null);
  const closeDialog = () => {
    if (!submitting) setOpen(false);
  };
  const dialogRef = useDialogFocus<HTMLElement>({
    open,
    onClose: closeDialog,
    initialFocusRef: nameInputRef,
  });

  return (
    <>
      <button
        className={
          variant === "inline"
            ? "inline-create-button"
            : variant === "secondary"
              ? "secondary-button"
              : "primary-button"
        }
        type="button"
        onClick={() => {
          setError(undefined);
          setOpen(true);
        }}
      >
        {label ?? (
          <>
            <Plus size={17} weight="bold" aria-hidden="true" />
            New project
          </>
        )}
      </button>
      {open && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeDialog();
          }}
        >
          <section
            ref={dialogRef}
            className="modal-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
          >
            <div className="modal-heading">
              <div>
                <h2 id={titleId}>Create project</h2>
              </div>
              <button
                type="button"
                className="icon-button"
                disabled={submitting}
                onClick={closeDialog}
                aria-label="Close dialog"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (DEMO_MODE) {
                  setError("Projects are not saved in demo mode.");
                  return;
                }
                const form = new FormData(event.currentTarget);
                setSubmitting(true);
                setError(undefined);
                void createProject({
                  name: String(form.get("name") ?? ""),
                  description:
                    String(form.get("description") ?? "") || undefined,
                  mode: String(form.get("mode") ?? "balanced"),
                })
                  .then(() => {
                    void queryClient.invalidateQueries({
                      queryKey: ["dashboard"],
                    });
                    setOpen(false);
                  })
                  .catch((reason: unknown) => {
                    setError(
                      reason instanceof Error
                        ? reason.message
                        : "The project could not be created.",
                    );
                  })
                  .finally(() => setSubmitting(false));
              }}
            >
              <label className="field">
                <span>Project name</span>
                <input
                  ref={nameInputRef}
                  required
                  name="name"
                  maxLength={120}
                  placeholder="Example: Product manual knowledge base"
                />
              </label>
              <label className="field">
                <span>
                  Description <small>Optional</small>
                </span>
                <textarea
                  name="description"
                  rows={3}
                  maxLength={500}
                  placeholder="What will be compiled and how it will be used"
                />
              </label>
              <fieldset className="mode-fieldset">
                <legend>Default processing mode</legend>
                {[
                  ["balanced", "Balanced", "Balance quality and cost", true],
                  [
                    "precision",
                    "Precision",
                    "Cross-check critical documents",
                    false,
                  ],
                  ["private", "Private", "No external model APIs", false],
                ].map(([value, name, description, checked]) => (
                  <label className="mode-option" key={String(value)}>
                    <input
                      type="radio"
                      name="mode"
                      value={String(value)}
                      defaultChecked={Boolean(checked)}
                    />
                    <span>
                      <strong>{name}</strong>
                      <small>{description}</small>
                    </span>
                  </label>
                ))}
              </fieldset>
              {error && (
                <p className="form-error" role="alert">
                  {error}
                </p>
              )}
              <div className="modal-actions">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={submitting}
                  onClick={closeDialog}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="primary-button"
                  disabled={submitting}
                >
                  {submitting ? "Creating…" : "Create project"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </>
  );
}
