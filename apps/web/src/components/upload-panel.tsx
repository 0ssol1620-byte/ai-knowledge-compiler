"use client";

import {
  ArrowRight,
  FileArrowUp,
  FileText,
  LockKey,
  ShieldCheck,
  X,
} from "@phosphor-icons/react";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { apiRequest, waitForAnalysis } from "@/lib/api-client";
import {
  PdfPasswordRequiredError,
  uploadAndAnalyze,
} from "@/lib/upload-client";

const acceptedExtensions =
  ".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.docx,.pptx,.xlsx,.csv,.html,.htm,.txt,.md,.vtt,.srt";
const ANALYSIS_MAX_SOURCE_BYTES = 256 * 1024 * 1024;

const DEMO_MODE = process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true";

export function UploadPanel({
  projectId,
  showPolicy = true,
}: {
  projectId?: string;
  showPolicy?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const [dragging, setDragging] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [completed, setCompleted] = useState(0);
  const [error, setError] = useState<string>();
  const [passwordRequest, setPasswordRequest] = useState<{
    documentId: string;
    filename: string;
  }>();
  const [password, setPassword] = useState("");
  const [submittingPassword, setSubmittingPassword] = useState(false);

  function addFiles(next: FileList | null) {
    if (!next) return;
    const candidates = Array.from(next);
    const accepted = candidates.filter(
      (file) => file.size <= ANALYSIS_MAX_SOURCE_BYTES,
    );
    if (accepted.length !== candidates.length) {
      setError("The native analysis limit is 256 MB per file.");
    }
    setFiles((current) => [...current, ...accepted].slice(0, 30));
  }

  return (
    <section className={`${showPolicy ? "panel " : ""}upload-panel`}>
      <header className="upload-panel-heading">
        <div>
          <h2>Documents to compile</h2>
          <p>Add up to 30 files at a time.</p>
        </div>
        {showPolicy && (
          <span className="upload-policy-inline">
            <LockKey size={15} aria-hidden="true" />
            External APIs off
          </span>
        )}
      </header>
      <button
        type="button"
        className={`dropzone ${dragging ? "dragging" : ""}`}
        aria-label="Drop files here or choose files"
        disabled={uploading}
        onClick={() => inputRef.current?.click()}
        onDragEnter={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          addFiles(event.dataTransfer.files);
        }}
      >
        <span className="dropzone-icon">
          <FileArrowUp size={30} aria-hidden="true" />
        </span>
        <strong>Drop documents or a folder here</strong>
        <span>PDF, DOCX, PPTX, XLSX, images, and HTML</span>
        <small>Or choose files manually · up to 50 MB each</small>
      </button>
      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        aria-label="Choose files to upload"
        multiple
        disabled={uploading}
        accept={acceptedExtensions}
        onChange={(event) => addFiles(event.currentTarget.files)}
      />

      {files.length > 0 && (
        <div className="selected-files" aria-live="polite">
          {files.map((file, index) => (
            <div
              className="selected-file"
              key={`${file.name}-${file.lastModified}`}
            >
              <FileText size={17} weight="duotone" aria-hidden="true" />
              <span>
                <strong>{file.name}</strong>
                <small>{formatBytes(file.size)}</small>
              </span>
              <button
                type="button"
                className="icon-button compact"
                aria-label={`Remove ${file.name}`}
                disabled={uploading}
                onClick={() =>
                  setFiles((items) =>
                    items.filter((_, itemIndex) => itemIndex !== index),
                  )
                }
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="upload-assurance">
        <ShieldCheck size={18} aria-hidden="true" />
        <span>
          Sources are stored in an isolated area and checked for format,
          integrity, and malicious content before processing.
        </span>
      </div>

      {uploading && (
        <p className="upload-progress" role="status">
          Security checks and analysis requested for {completed}/{files.length}{" "}
          files.
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {passwordRequest && (
        <form
          className="pdf-password-resume"
          aria-labelledby="pdf-password-title"
          onSubmit={(event) => {
            event.preventDefault();
            if (!password || submittingPassword) return;
            setSubmittingPassword(true);
            setError(undefined);
            const submittedPassword = password;
            setPassword("");
            void apiRequest(
              `/v1/documents/${passwordRequest.documentId}/password`,
              {
                method: "POST",
                idempotencyKey: crypto.randomUUID(),
                body: JSON.stringify({ password: submittedPassword }),
              },
            )
              .then(() => waitForAnalysis(passwordRequest.documentId))
              .then(() => {
                router.push(
                  `/workspace?document=${passwordRequest.documentId}&estimate=1`,
                );
                setPasswordRequest(undefined);
              })
              .catch((reason: unknown) => {
                setError(
                  reason instanceof Error
                    ? reason.message
                    : "The PDF password could not be verified.",
                );
              })
              .finally(() => setSubmittingPassword(false));
          }}
        >
          <div className="pdf-password-copy">
            <span className="pdf-password-icon" aria-hidden="true">
              <LockKey size={18} weight="bold" />
            </span>
            <div>
              <h3 id="pdf-password-title">Open encrypted PDF</h3>
              <p>
                The password for <strong>{passwordRequest.filename}</strong>{" "}
                remains in memory only during analysis and is discarded
                immediately after it expires.
              </p>
            </div>
          </div>
          <label className="field" htmlFor="pdf-password">
            <span>Document password</span>
            <input
              id="pdf-password"
              type="password"
              autoComplete="off"
              value={password}
              disabled={submittingPassword}
              required
              maxLength={1024}
              onChange={(event) => setPassword(event.currentTarget.value)}
            />
          </label>
          <div className="pdf-password-actions">
            <button
              className="secondary-button"
              type="button"
              disabled={submittingPassword}
              onClick={() => {
                setPassword("");
                setPasswordRequest(undefined);
              }}
            >
              Cancel
            </button>
            <button
              className="primary-button"
              type="submit"
              disabled={!password || submittingPassword}
            >
              {submittingPassword
                ? "Checking password…"
                : "Resume secure analysis"}
              <ArrowRight size={16} aria-hidden="true" />
            </button>
          </div>
        </form>
      )}
      <button
        className="primary-button full-width"
        type="button"
        disabled={files.length === 0 || uploading}
        onClick={() => {
          if (DEMO_MODE) {
            setError("Demo mode does not upload sources or use credits.");
            return;
          }
          setUploading(true);
          setCompleted(0);
          setError(undefined);
          void (async () => {
            let lastDocumentId: string | undefined;
            for (const file of files) {
              try {
                const result = await uploadAndAnalyze(file, projectId);
                lastDocumentId = result.documentId;
                setCompleted((value) => value + 1);
              } catch (reason) {
                if (reason instanceof PdfPasswordRequiredError) {
                  setPasswordRequest({
                    documentId: reason.documentId,
                    filename: file.name,
                  });
                  continue;
                }
                throw reason;
              }
            }
            if (lastDocumentId) {
              router.push(`/workspace?document=${lastDocumentId}&estimate=1`);
            }
          })()
            .catch((reason: unknown) => {
              setError(
                reason instanceof Error
                  ? reason.message
                  : "File analysis could not be started.",
              );
            })
            .finally(() => setUploading(false));
        }}
      >
        {uploading
          ? "Uploading and analyzing…"
          : files.length > 0
            ? `Run preflight on ${files.length} document${files.length === 1 ? "" : "s"}`
            : "Select a document to continue"}
        <ArrowRight size={16} aria-hidden="true" />
      </button>
    </section>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
