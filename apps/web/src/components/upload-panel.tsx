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
      setError("파일별 네이티브 분석 한도는 256MB입니다.");
    }
    setFiles((current) => [...current, ...accepted].slice(0, 30));
  }

  return (
    <section className={`${showPolicy ? "panel " : ""}upload-panel`}>
      <header className="upload-panel-heading">
        <div>
          <h2>변환할 문서</h2>
          <p>한 번에 30개까지 추가할 수 있습니다.</p>
        </div>
        {showPolicy && (
          <span className="upload-policy-inline">
            <LockKey size={15} aria-hidden="true" />
            외부 API 꺼짐
          </span>
        )}
      </header>
      <button
        type="button"
        className={`dropzone ${dragging ? "dragging" : ""}`}
        aria-label="파일을 끌어놓거나 선택하세요"
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
        <strong>문서 또는 폴더를 여기에 놓으세요</strong>
        <span>PDF, DOCX, PPTX, XLSX, 이미지, HTML</span>
        <small>클릭해서 직접 선택할 수도 있습니다 · 파일당 최대 50MB</small>
      </button>
      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        aria-label="업로드할 파일 선택"
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
                aria-label={`${file.name} 제거`}
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
          원본은 격리 영역에 저장되며, 변환 전에 파일 형식·무결성·악성 파일
          여부를 검사합니다.
        </span>
      </div>

      {uploading && (
        <p className="upload-progress" role="status">
          {completed}/{files.length}개 파일의 보안 검사·분석을 요청했습니다.
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
                    : "PDF 암호를 확인하지 못했습니다.",
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
              <h3 id="pdf-password-title">암호화된 PDF 열기</h3>
              <p>
                <strong>{passwordRequest.filename}</strong>의 암호는 분석 중
                메모리에만 보관되며 만료 후 즉시 폐기됩니다.
              </p>
            </div>
          </div>
          <label className="field" htmlFor="pdf-password">
            <span>문서 암호</span>
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
              취소
            </button>
            <button
              className="primary-button"
              type="submit"
              disabled={!password || submittingPassword}
            >
              {submittingPassword ? "암호 확인 중" : "안전하게 분석 재개"}
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
            setError("Demo mode에서는 원본을 업로드하거나 과금하지 않습니다.");
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
                  : "파일 분석을 시작하지 못했습니다.",
              );
            })
            .finally(() => setUploading(false));
        }}
      >
        {uploading
          ? "업로드·분석 중"
          : files.length > 0
            ? `${files.length}개 문서 사전 분석`
            : "문서를 선택하면 계속할 수 있습니다"}
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
