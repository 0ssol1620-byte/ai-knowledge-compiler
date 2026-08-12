"use client";

import {
  Archive,
  BracketsCurly,
  Check,
  DownloadSimple,
  FileMd,
  Graph,
  ShieldCheck,
  Warning,
  X,
} from "@phosphor-icons/react";
import { useId, useRef, useState } from "react";

import { apiAbsoluteUrl } from "@/lib/api-client";
import { useDialogFocus } from "@/lib/use-dialog-focus";

const profiles = [
  {
    id: "portable",
    name: "Portable Markdown",
    description: "CommonMark + GFM, source map, assets",
    icon: FileMd,
    defaultChecked: true,
  },
  {
    id: "obsidian",
    name: "Obsidian Vault",
    description: "MOC, notes, attachments, quality queue",
    icon: Archive,
    defaultChecked: true,
  },
  {
    id: "rag",
    name: "RAG JSONL",
    description: "documents, adaptive chunks, provenance",
    icon: BracketsCurly,
    defaultChecked: true,
  },
  {
    id: "jsonld",
    name: "JSON-LD",
    description: "entities, relations, evidence assertions",
    icon: Graph,
    defaultChecked: false,
  },
] as const;

type MergePolicy =
  | "error"
  | "keep_existing"
  | "rename_incoming"
  | "replace_same_source"
  | "update_managed";

export interface ExportCreated {
  exportId: string;
  downloadUrl: string;
}

export interface VaultMergePreview {
  policy: MergePolicy;
  existing_file_count: number;
  incoming_file_count: number;
  output_file_count: number;
  conflict_count: number;
  unresolved_conflict_count: number;
  broken_link_count: number;
  safe_to_apply: boolean;
  plan_sha256: string;
  conflicts: Array<{
    existing_path: string;
    incoming_path: string;
    reason: string;
    resolution: string | null;
    resolved_path: string | null;
  }>;
  broken_links: Array<{
    source_path: string;
    target: string;
    resolved_path: string | null;
    reason: string;
  }>;
}

export function ExportDialog({
  open,
  onClose,
  onExport,
  onVaultPreview,
  summary,
}: {
  open: boolean;
  onClose: () => void;
  onExport?: (profiles: string[]) => Promise<ExportCreated>;
  onVaultPreview?: (
    exportId: string,
    vault: File,
    policy: MergePolicy,
  ) => Promise<VaultMergePreview>;
  summary?: {
    pages: number;
    blocks: number;
    knowledgeNotes: number;
    reviewWarnings: number;
  };
}) {
  const titleId = useId();
  const [started, setStarted] = useState(false);
  const [error, setError] = useState<string>();
  const [selected, setSelected] = useState<string[]>(
    profiles
      .filter((profile) => profile.defaultChecked)
      .map((profile) => profile.id),
  );
  const [vault, setVault] = useState<File>();
  const [policy, setPolicy] = useState<MergePolicy>("error");
  const [created, setCreated] = useState<ExportCreated>();
  const [preview, setPreview] = useState<VaultMergePreview>();
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useDialogFocus<HTMLElement>({
    open,
    onClose,
    initialFocusRef: closeButtonRef,
  });

  if (!open) return null;
  const vaultPreviewEnabled =
    selected.includes("obsidian") && Boolean(onVaultPreview);

  async function createExport() {
    if (!onExport) return;
    setStarted(true);
    setError(undefined);
    setPreview(undefined);
    try {
      const result = await onExport(selected);
      setCreated(result);
      if (vault && onVaultPreview) {
        setPreview(await onVaultPreview(result.exportId, vault, policy));
      } else {
        window.location.assign(apiAbsoluteUrl(result.downloadUrl));
        onClose();
      }
    } catch (reason: unknown) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The export package could not be created.",
      );
    } finally {
      setStarted(false);
    }
  }

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !started) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className="modal-card export-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={started}
        tabIndex={-1}
      >
        <div className="modal-heading">
          <div>
            <h2 id={titleId}>Create knowledge package</h2>
            <p>The same CIR snapshot and options produce the same checksum.</p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className="icon-button"
            onClick={onClose}
            disabled={started}
            aria-label="Close export"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        {!preview ? (
          <>
            <fieldset className="export-options">
              <legend>Profiles to include</legend>
              {profiles.map(({ id, name, description, icon: Icon }) => (
                <label key={id}>
                  <input
                    type="checkbox"
                    checked={selected.includes(id)}
                    disabled={started}
                    onChange={(event) => {
                      const checked = event.currentTarget.checked;
                      setSelected((current) =>
                        checked
                          ? [...current, id]
                          : current.filter((value) => value !== id),
                      );
                    }}
                  />
                  <span className="export-option-icon">
                    <Icon size={19} weight="duotone" aria-hidden="true" />
                  </span>
                  <span>
                    <strong>{name}</strong>
                    <small>{description}</small>
                  </span>
                  <Check
                    className="option-check"
                    size={15}
                    weight="bold"
                    aria-hidden="true"
                  />
                </label>
              ))}
            </fieldset>

            {vaultPreviewEnabled && (
              <section
                className="vault-merge-tool"
                aria-labelledby="vault-merge-title"
              >
                <div>
                  <div>
                    <h3 id="vault-merge-title">
                      Compare with an existing Obsidian Vault
                    </h3>
                  </div>
                  <span>
                    <ShieldCheck size={14} weight="fill" aria-hidden="true" />
                    The source Vault is never modified
                  </span>
                </div>
                <p>
                  Select an existing Vault ZIP to calculate path collisions and
                  broken links before download. The ZIP is used only for
                  comparison.
                </p>
                <div className="vault-merge-inputs">
                  <label className="field">
                    <span>Existing Vault ZIP (optional)</span>
                    <input
                      type="file"
                      accept=".zip,application/zip"
                      disabled={started}
                      onChange={(event) =>
                        setVault(event.currentTarget.files?.[0])
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Collision policy</span>
                    <select
                      value={policy}
                      disabled={!vault || started}
                      onChange={(event) =>
                        setPolicy(event.currentTarget.value as MergePolicy)
                      }
                    >
                      <option value="error">Stop on conflict</option>
                      <option value="keep_existing">Keep existing</option>
                      <option value="rename_incoming">Rename incoming</option>
                      <option value="replace_same_source">
                        Replace same source
                      </option>
                      <option value="update_managed">Update AKC-managed</option>
                    </select>
                  </label>
                </div>
              </section>
            )}

            <div className="export-summary">
              {summary ? (
                <>
                  <span>{summary.pages} pages</span>
                  <span>{summary.blocks} blocks</span>
                  <span>{summary.knowledgeNotes} knowledge notes</span>
                  <span>{summary.reviewWarnings} integrity findings included</span>
                </>
              ) : (
                <span>Generated from the stored CIR snapshot.</span>
              )}
            </div>
          </>
        ) : (
          <VaultPreviewResult preview={preview} />
        )}

        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button
            type="button"
            className="secondary-button"
            disabled={started}
            onClick={onClose}
          >
            {preview ? "Close" : "Cancel"}
          </button>
          {preview && created ? (
            <button
              type="button"
              className="primary-button"
              onClick={() =>
                window.location.assign(apiAbsoluteUrl(created.downloadUrl))
              }
            >
              <DownloadSimple size={16} aria-hidden="true" />
              Download validated package
            </button>
          ) : (
            <button
              type="button"
              className="primary-button"
              disabled={started || selected.length === 0 || !onExport}
              onClick={() => void createExport()}
            >
              {started ? (
                <>
                  <span className="spinner" aria-hidden="true" />
                  {vault ? "Comparing Vault…" : "Creating package…"}
                </>
              ) : (
                <>
                  <DownloadSimple size={16} aria-hidden="true" />
                  {vault ? "Create and preview conflicts" : "Export package"}
                </>
              )}
            </button>
          )}
        </div>
      </section>
    </div>
  );
}

function VaultPreviewResult({ preview }: { preview: VaultMergePreview }) {
  return (
    <section className="vault-preview-result" aria-live="polite">
      <header>
        <span className={preview.safe_to_apply ? "safe" : "warning"}>
          {preview.safe_to_apply ? (
            <ShieldCheck size={18} weight="fill" aria-hidden="true" />
          ) : (
            <Warning size={18} weight="fill" aria-hidden="true" />
          )}
        </span>
        <div>
          <p className="metadata-label">
            Plan ID {preview.plan_sha256.slice(0, 12)}
          </p>
          <h3>
            {preview.safe_to_apply
              ? "Safe to merge with the selected policy"
              : "Unresolved conflicts require an explicit decision"}
          </h3>
          <p>
            This is a read-only plan. No changes have been applied to the
            existing Vault.
          </p>
        </div>
      </header>
      <dl className="vault-preview-metrics">
        <div>
          <dt>Existing</dt>
          <dd>{preview.existing_file_count}</dd>
        </div>
        <div>
          <dt>Incoming</dt>
          <dd>{preview.incoming_file_count}</dd>
        </div>
        <div>
          <dt>Conflicts</dt>
          <dd>{preview.conflict_count}</dd>
        </div>
        <div>
          <dt>Broken links</dt>
          <dd>{preview.broken_link_count}</dd>
        </div>
      </dl>
      {preview.conflicts.length > 0 && (
        <details open>
          <summary>Path conflicts ({preview.conflicts.length})</summary>
          <ul>
            {preview.conflicts.map((conflict) => (
              <li key={`${conflict.existing_path}:${conflict.incoming_path}`}>
                <code>{conflict.incoming_path}</code>
                <span>{conflict.resolution ?? conflict.reason}</span>
                {conflict.resolved_path && (
                  <small>→ {conflict.resolved_path}</small>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      {preview.broken_links.length > 0 && (
        <details>
          <summary>Broken links ({preview.broken_links.length})</summary>
          <ul>
            {preview.broken_links.map((link) => (
              <li key={`${link.source_path}:${link.target}`}>
                <code>{link.source_path}</code>
                <span>{link.target}</span>
                <small>{link.reason}</small>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
