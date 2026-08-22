"use client";

import {
  ArrowRight,
  FileArrowUp,
  FileText,
  LockKey,
  ShieldCheck,
  X,
} from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { useStructaraLocale } from "@/components/locale-provider";
import { apiRequest, waitForAnalysis } from "@/lib/api-client";
import type { StructaraLocale } from "@/lib/locale";
import {
  PdfPasswordRequiredError,
  uploadAndAnalyze,
} from "@/lib/upload-client";
import {
  partitionFilesBySize,
  QUICK_CONVERT_MAX_FILE_LABEL,
  QUICK_CONVERT_MAX_FILES,
} from "@/lib/upload-policy";

const acceptedExtensions =
  ".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.docx,.pptx,.xlsx,.csv,.html,.htm,.txt,.md,.vtt,.srt";

const DEMO_MODE = process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true";

const COPY = {
  en: {
    title: "Documents to compile",
    addLimit: (count: number) => `Add up to ${count} files at a time.`,
    consent: "External providers require consent",
    dropLabel: "Drop files here or choose files",
    drop: "Drop documents here",
    formats: "PDF, DOCX, PPTX, XLSX, images, and HTML",
    choose: (limit: string) => `Or choose files manually · up to ${limit} each`,
    chooseInput: "Choose files to upload",
    remove: "Remove",
    assurance:
      "Sources are stored in an isolated area and checked for format, integrity, and malicious content before processing.",
    progress: (completed: number, total: number) =>
      `Security checks and analysis requested for ${completed}/${total} files.`,
    limit: (limit: string) =>
      `The current quick-convert limit is ${limit} per file.`,
    openPdf: "Open encrypted PDF",
    pdfBodyPrefix: "The password for",
    pdfBodySuffix:
      "remains in memory only during analysis and is discarded immediately after it expires.",
    documentPassword: "Document password",
    cancel: "Cancel",
    checkingPassword: "Checking password…",
    resume: "Resume secure analysis",
    pdfError: "The PDF password could not be verified.",
    demoError: "Demo mode does not upload sources or use credits.",
    analysisError: "File analysis could not be started.",
    uploading: "Uploading and analyzing…",
    runPreflight: (count: number) =>
      `Run preflight on ${count} document${count === 1 ? "" : "s"}`,
    select: "Select a document to continue",
  },
  ko: {
    title: "컴파일할 문서",
    addLimit: (count: number) =>
      `한 번에 최대 ${count}개 파일을 추가할 수 있습니다.`,
    consent: "외부 제공자 사용에는 동의가 필요합니다",
    dropLabel: "파일을 놓거나 직접 선택",
    drop: "문서를 여기에 놓으세요",
    formats: "PDF, DOCX, PPTX, XLSX, 이미지와 HTML",
    choose: (limit: string) => `또는 파일 직접 선택 · 파일당 최대 ${limit}`,
    chooseInput: "업로드할 파일 선택",
    remove: "제거",
    assurance:
      "원본은 격리된 영역에 저장되며 처리 전에 형식, 무결성과 악성 콘텐츠를 검사합니다.",
    progress: (completed: number, total: number) =>
      `${total}개 중 ${completed}개 파일의 보안 검사와 분석을 요청했습니다.`,
    limit: (limit: string) =>
      `현재 Quick Convert 제한은 파일당 ${limit}입니다.`,
    openPdf: "암호화된 PDF 열기",
    pdfBodyPrefix: "다음 파일의 비밀번호는",
    pdfBodySuffix:
      "분석 중에만 메모리에 유지되며 사용 기간이 끝나는 즉시 폐기됩니다.",
    documentPassword: "문서 비밀번호",
    cancel: "취소",
    checkingPassword: "비밀번호 확인 중…",
    resume: "안전한 분석 재개",
    pdfError: "PDF 비밀번호를 확인할 수 없습니다.",
    demoError:
      "데모 모드에서는 원본을 업로드하거나 크레딧을 사용하지 않습니다.",
    analysisError: "파일 분석을 시작할 수 없습니다.",
    uploading: "업로드 및 분석 중…",
    runPreflight: (count: number) => `${count}개 문서 사전 분석 실행`,
    select: "계속하려면 문서를 선택하세요",
  },
} as const;

export function UploadPanel({
  projectId,
  showPolicy = true,
}: {
  projectId?: string;
  showPolicy?: boolean;
}) {
  const { locale } = useStructaraLocale();
  const copy = COPY[locale];
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
    const { accepted, rejected } = partitionFilesBySize(candidates);
    setError(
      rejected.length > 0
        ? copy.limit(QUICK_CONVERT_MAX_FILE_LABEL)
        : undefined,
    );
    setFiles((current) =>
      [...current, ...accepted].slice(0, QUICK_CONVERT_MAX_FILES),
    );
  }

  return (
    <section
      className={`${showPolicy ? "panel " : ""}upload-panel`}
      data-locale={locale}
    >
      <header className="upload-panel-heading">
        <div>
          <h2>{copy.title}</h2>
          <p>{copy.addLimit(QUICK_CONVERT_MAX_FILES)}</p>
        </div>
        {showPolicy && (
          <span className="upload-policy-inline">
            <LockKey size={15} aria-hidden="true" />
            {copy.consent}
          </span>
        )}
      </header>
      <button
        type="button"
        className={`dropzone ${dragging ? "dragging" : ""}`}
        aria-label={copy.dropLabel}
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
        <strong>{copy.drop}</strong>
        <span>{copy.formats}</span>
        <small>{copy.choose(QUICK_CONVERT_MAX_FILE_LABEL)}</small>
      </button>
      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        aria-label={copy.chooseInput}
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
                <small>{formatBytes(file.size, locale)}</small>
              </span>
              <button
                type="button"
                className="icon-button compact"
                aria-label={`${copy.remove} ${file.name}`}
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
        <span>{copy.assurance}</span>
      </div>

      {uploading && (
        <p className="upload-progress" role="status">
          {copy.progress(completed, files.length)}
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
              .catch(() => {
                setError(copy.pdfError);
              })
              .finally(() => setSubmittingPassword(false));
          }}
        >
          <div className="pdf-password-copy">
            <span className="pdf-password-icon" aria-hidden="true">
              <LockKey size={18} weight="bold" />
            </span>
            <div>
              <h3 id="pdf-password-title">{copy.openPdf}</h3>
              <p>
                {copy.pdfBodyPrefix} <strong>{passwordRequest.filename}</strong>{" "}
                {copy.pdfBodySuffix}
              </p>
            </div>
          </div>
          <label className="field" htmlFor="pdf-password">
            <span>{copy.documentPassword}</span>
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
              {copy.cancel}
            </button>
            <button
              className="primary-button"
              type="submit"
              disabled={!password || submittingPassword}
            >
              {submittingPassword ? copy.checkingPassword : copy.resume}
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
            setError(copy.demoError);
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
            .catch(() => {
              setError(copy.analysisError);
            })
            .finally(() => setUploading(false));
        }}
      >
        {uploading
          ? copy.uploading
          : files.length > 0
            ? copy.runPreflight(files.length)
            : copy.select}
        <ArrowRight size={16} aria-hidden="true" />
      </button>
    </section>
  );
}

function formatBytes(bytes: number, locale: StructaraLocale): string {
  if (bytes < 1024)
    return `${bytes.toLocaleString(locale === "ko" ? "ko-KR" : "en-US")} B`;
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024).toLocaleString(locale === "ko" ? "ko-KR" : "en-US")} KB`;
  }
  return `${(bytes / (1024 * 1024)).toLocaleString(
    locale === "ko" ? "ko-KR" : "en-US",
    {
      maximumFractionDigits: 1,
      minimumFractionDigits: 1,
    },
  )} MB`;
}
