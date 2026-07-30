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

import { uploadAndAnalyze } from "@/lib/upload-client";

const acceptedExtensions =
  ".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.docx,.pptx,.xlsx,.csv,.html,.htm,.txt,.md,.vtt,.srt";
const ANALYSIS_MAX_SOURCE_BYTES = 256 * 1024 * 1024;

const DEMO_MODE = process.env.NEXT_PUBLIC_AKC_DEMO_MODE === "true";

export function UploadPanel({ projectId }: { projectId?: string }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const [dragging, setDragging] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [completed, setCompleted] = useState(0);
  const [error, setError] = useState<string>();

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
    <section className="panel upload-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Quick convert</p>
          <h2>자료 추가</h2>
          <p>보안 검사 후 비용 범위를 먼저 계산합니다.</p>
        </div>
        <span className="private-badge">
          <LockKey size={14} weight="fill" aria-hidden="true" />
          외부 API 꺼짐
        </span>
      </div>
      <button
        type="button"
        className={`dropzone ${dragging ? "dragging" : ""}`}
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
          <FileArrowUp size={28} weight="duotone" aria-hidden="true" />
        </span>
        <strong>파일을 끌어놓거나 선택하세요</strong>
        <span>PDF · Office · 이미지 · HTML · 텍스트 · 자막</span>
        <small>파일당 최대 50MB · Free 기준 · 네이티브 분석 최대 256MB</small>
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
        <ShieldCheck size={18} weight="fill" aria-hidden="true" />
        <span>
          원본은 격리 저장되며, 처리 전 유형·checksum·악성 파일 검사를
          수행합니다.
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
              const result = await uploadAndAnalyze(file, projectId);
              lastDocumentId = result.documentId;
              setCompleted((value) => value + 1);
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
            ? `${files.length}개 파일 분석하기`
            : "파일을 먼저 선택하세요"}
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
