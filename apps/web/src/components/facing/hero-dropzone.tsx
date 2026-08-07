"use client";

import { ArrowRight, FileArrowUp, ShieldCheck } from "@phosphor-icons/react";
import Link from "next/link";
import { useId, useRef, useState } from "react";

import {
  abbreviateDigest,
  formatBytes,
  inspectDroppedFile,
  type DroppedFile,
} from "@/lib/facing/dropped-file";

/**
 * The hero drop zone — DESIGN_MASTER_V3 §12.2, three states.
 *
 *   ①  resting        the frozen sample spread is shown, this layer is inert
 *   ②  hover / focus  the frame announces that it takes a document
 *   ③  after a drop   what this browser can establish about the file, and the
 *                     real next step
 *
 * §9.2 chose the affordance over the 3D scene precisely so the first thing on
 * the page does something. §14.3 then requires that it actually work, and
 * §25.7 forbids inventing progress — so state ③ shows measurements taken here,
 * in this browser, and says plainly what it cannot know.
 *
 * The file is not uploaded. Every ingest path in the API is tenant-scoped and
 * the marketing surface has no session; opening an anonymous one is a backend
 * contract change, which §24.4 stops on. It is a separate, security-reviewed
 * change — see decision.md. Until it lands, "did not leave this device" is
 * true, and it is the product's own argument shown rather than asserted.
 */
export function HeroDropzone({
  onStateChange,
}: {
  /** Lets the surrounding scene dim the sample spread while ③ is showing. */
  onStateChange?: (active: boolean) => void;
}) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [reading, setReading] = useState(false);
  const [dropped, setDropped] = useState<DroppedFile>();

  async function accept(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    setReading(true);
    onStateChange?.(true);
    try {
      setDropped(await inspectDroppedFile(file));
    } finally {
      setReading(false);
    }
  }

  function reset() {
    setDropped(undefined);
    onStateChange?.(false);
    if (inputRef.current) inputRef.current.value = "";
  }

  if (dropped) {
    return <DroppedReport file={dropped} onReset={reset} />;
  }

  return (
    <div
      className="tv-dropzone"
      data-dragging={dragging || undefined}
      data-reading={reading || undefined}
      onDragEnter={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragOver={(event) => {
        // Required by the HTML drag-and-drop model for a drop to be accepted.
        event.preventDefault();
      }}
      onDragLeave={(event) => {
        // Ignore the events fired while crossing child elements.
        if (event.currentTarget.contains(event.relatedTarget as Node)) return;
        setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        void accept(event.dataTransfer.files);
      }}
    >
      {/*
        A real <input type="file"> with a real <label>. Keyboard and screen
        reader support come from the platform rather than from a div with a
        keydown handler, which §21 asks for and which a custom widget here
        would only approximate.
      */}
      <input
        ref={inputRef}
        id={inputId}
        className="visually-hidden"
        type="file"
        accept=".pdf,.docx,.pptx,.xlsx,.html,.htm,.md,.txt,.png,.jpg,.jpeg,.tif,.tiff,.webp"
        onChange={(event) => void accept(event.currentTarget.files)}
      />
      <label htmlFor={inputId} className="tv-dropzone-target">
        <FileArrowUp size={20} weight="regular" aria-hidden="true" />
        <strong>
          {reading ? "Reading your document…" : "Try it with your own document"}
        </strong>
        <span>
          Drop a file here, or choose one. It stays in your browser — nothing is
          uploaded.
        </span>
      </label>
    </div>
  );
}

/**
 * State ③. Every figure here was measured in this browser; the two things a
 * browser cannot determine are named as unknown rather than estimated.
 */
function DroppedReport({
  file,
  onReset,
}: {
  file: DroppedFile;
  onReset: () => void;
}) {
  return (
    <div className="tv-dropzone" data-report="true">
      <div className="tv-dropzone-report">
        <p className="tv-dropzone-privacy">
          <ShieldCheck size={15} weight="fill" aria-hidden="true" />
          Read in your browser. This file was not uploaded.
        </p>

        <dl>
          <div>
            <dt>File</dt>
            <dd title={file.name}>{file.name}</dd>
          </div>
          <div>
            <dt>Size</dt>
            <dd data-numeric>{formatBytes(file.size)}</dd>
          </div>
          <div>
            <dt>Type</dt>
            <dd>{file.type || (file.extension ? `.${file.extension}` : "unknown")}</dd>
          </div>
          {file.sha256 && (
            <div>
              <dt>SHA-256</dt>
              <dd data-numeric title={file.sha256}>
                {abbreviateDigest(file.sha256)}
              </dd>
            </div>
          )}
        </dl>

        {file.rejection ? (
          <p className="tv-dropzone-note" data-state="review">
            {file.rejection}
          </p>
        ) : (
          <p className="tv-dropzone-note">
            {/* §25.7 — a page count needs a parser this build does not have.
                Saying so is the alternative to guessing. */}
            Page count, structure, and evidence coverage are measured during
            compilation, which runs on our side.
          </p>
        )}

        <div className="tv-dropzone-actions">
          {!file.rejection && (
            <Link href="/signup" className="tv-dropzone-cta">
              Start compiling
              <ArrowRight size={15} weight="bold" aria-hidden="true" />
            </Link>
          )}
          <button type="button" className="tv-dropzone-reset" onClick={onReset}>
            {file.rejection ? "Try another file" : "Back to the sample"}
          </button>
        </div>
      </div>
    </div>
  );
}
