"use client";

// The /dist/ssr entry, matching the rest of the marketing surface. The
// client entry ships the icon runtime this component does not use.
import {
  ArrowRight,
  FileArrowUp,
  ShieldCheck,
} from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import {
  abbreviateDigest,
  formatBytes,
  inspectDroppedFile,
  type DroppedFile,
} from "@/lib/facing/dropped-file";
import {
  createTrialSession,
  isSettled,
  readTrialPreflight,
  retentionSentence,
  TrialIngestError,
  TRIAL_INGEST_ENABLED,
  uploadTrialDocument,
  type TrialPreflight,
  type TrialSession,
} from "@/lib/facing/trial-client";

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
 * Two modes, and the visitor can tell which one they are in:
 *
 *   capability off  the file is read here and never sent. "Not uploaded" is
 *                   literally true, and it is the product's privacy argument
 *                   demonstrated rather than asserted.
 *   capability on   the file is sent for scanning and preflight (ADR-006), and
 *                   the copy says what is sent, where it stops, and when it is
 *                   deleted. Keeping the old line here would be a false claim.
 *
 * The client flag only chooses which path to attempt. The server answers 404
 * when it disagrees, so a mis-set build falls back to the local mode instead of
 * promising an upload that cannot happen.
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
  const [session, setSession] = useState<TrialSession>();
  const [preflight, setPreflight] = useState<TrialPreflight>();
  const [sendError, setSendError] = useState<string>();

  async function accept(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    setReading(true);
    setSendError(undefined);
    onStateChange?.(true);
    try {
      const inspected = await inspectDroppedFile(file);
      setDropped(inspected);
      // A file this browser already refused is not sent. The local checks
      // mirror the server's, so failing here saves a round trip and a row.
      if (!TRIAL_INGEST_ENABLED || inspected.rejection) return;
      try {
        const opened = await createTrialSession();
        // Completion runs the security path inside the request, so the result
        // is already final here. The poller below stays as the fallback for a
        // completion that returns before the document settles.
        const { preflight: settled } = await uploadTrialDocument(
          opened,
          file,
          inspected,
        );
        setSession(opened);
        setPreflight(settled);
      } catch (error) {
        // The local report still stands — it was measured here. Only the
        // server half is missing, and the visitor is told which half.
        setSendError(
          error instanceof TrialIngestError
            ? error.message
            : "Could not reach the compiler. The reading above was done here.",
        );
      }
    } finally {
      setReading(false);
    }
  }

  // Poll only while the document is moving through the quarantine path, and
  // stop at a terminal state. §10.4 forbids anything that runs forever.
  useEffect(() => {
    if (!session || (preflight && isSettled(preflight.status))) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    // A self-scheduling timeout rather than setInterval: an interval fires
    // again whether or not the previous request finished, so a slow response
    // stacks requests, and an async interval callback swallows its own
    // rejection. This waits for each round trip before booking the next.
    const poll = () => {
      readTrialPreflight(session)
        .then((next) => {
          if (cancelled) return;
          setPreflight(next);
          if (!isSettled(next.status)) timer = setTimeout(poll, 2000);
        })
        .catch(() => {
          if (!cancelled) setSession(undefined);
        });
    };

    timer = setTimeout(poll, 1000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [session, preflight]);

  function reset() {
    setDropped(undefined);
    setSession(undefined);
    setPreflight(undefined);
    setSendError(undefined);
    onStateChange?.(false);
    if (inputRef.current) inputRef.current.value = "";
  }

  if (dropped) {
    return (
      <DroppedReport
        file={dropped}
        retention={session ? retentionSentence(session.expiresAt) : undefined}
        preflight={preflight}
        sendError={sendError}
        onReset={reset}
      />
    );
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
          {TRIAL_INGEST_ENABLED
            ? "Drop a file here, or choose one. It is scanned, previewed, and deleted within the hour."
            : "Drop a file here, or choose one. It stays in your browser — nothing is uploaded."}
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
  retention,
  preflight,
  sendError,
  onReset,
}: {
  file: DroppedFile;
  /** Set only when the file was actually sent. Drives the privacy line. */
  retention?: string;
  preflight?: TrialPreflight;
  sendError?: string;
  onReset: () => void;
}) {
  return (
    <div className="tv-dropzone" data-report="true">
      <div className="tv-dropzone-report">
        {/*
          The privacy line has to match what actually happened. Without the
          trial capability nothing is sent and "not uploaded" is literally
          true; with it, the file leaves the device and the line says what is
          sent, where it stops, and when it is deleted. Saying "not uploaded"
          in the second case would be the kind of claim §25.7 exists to stop.
        */}
        {retention ? (
          <p className="tv-dropzone-privacy" data-state="sent">
            <ShieldCheck size={15} weight="fill" aria-hidden="true" />
            Sent for security scanning and preflight only — never used for
            training. {retention}
          </p>
        ) : (
          <p className="tv-dropzone-privacy">
            <ShieldCheck size={15} weight="fill" aria-hidden="true" />
            Read in your browser. This file was not uploaded.
          </p>
        )}

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
        ) : sendError ? (
          <p className="tv-dropzone-note" data-state="review">
            {sendError}
          </p>
        ) : preflight ? (
          <PreflightNote preflight={preflight} />
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

/**
 * Say what was actually wrong with the file, where the server named it.
 *
 * "Rejected" alone reads as an accusation and leaves the visitor with nothing
 * to do. Most refusals are mundane — a renamed file, an empty one — and saying
 * which is both more useful and more accurate. The reasons are already public
 * in the sense that the visitor supplied the file; none of these tells them
 * anything about the scanner they could not learn by trying twice.
 */
function rejectionWording(code: string | null): string {
  switch (code) {
    case "file_signature_mismatch":
      return "This file's contents do not match its extension, so it was not accepted.";
    case "claimed_mime_mismatch":
      return "This file's type does not match what the browser reported, so it was not accepted.";
    case "extension_not_allowed":
    case "extension_blocked":
      return "The compiler does not accept this file type.";
    case "file_empty":
      return "This file is empty.";
    case "file_too_large":
      return "This file is larger than the trial limit.";
    case "MALWARE_DETECTED":
      return "Security scanning found malware in this file.";
    default:
      // Including CDR refusals and anything added later: the state is true
      // even when this build does not know the specific code.
      return "Security scanning rejected this file.";
  }
}

/**
 * What the server established, once it has. Every branch is a real state from
 * the ADR-004 quarantine path — none of them is a progress bar, and none
 * reports a figure the server has not sent (§25.7).
 */
function PreflightNote({ preflight }: { preflight: TrialPreflight }) {
  if (preflight.status === "SECURITY_REJECTED") {
    return (
      <p className="tv-dropzone-note" data-state="review">
        {rejectionWording(preflight.errorCode)} Nothing was compiled from it.
      </p>
    );
  }

  if (preflight.status === "FAILED") {
    return (
      <p className="tv-dropzone-note" data-state="review">
        The compiler could not read this document.
      </p>
    );
  }

  if (preflight.status !== "PREFLIGHTED") {
    // Named states, not a percentage. §25.7 rejects progress literals, and the
    // server does not publish a fraction to report even if it did not.
    const wording: Record<string, string> = {
      UPLOADED: "Queued for security scanning…",
      SECURITY_SCANNING: "Scanning for malware and unsafe structure…",
      SECURITY_VERIFIED: "Scan passed. Reading the page structure…",
      PREFLIGHTING: "Reading the page structure…",
    };
    return (
      <p className="tv-dropzone-note" role="status">
        {wording[preflight.status] ?? "Working…"}
      </p>
    );
  }

  return (
    <p className="tv-dropzone-note">
      {preflight.pageCount === null && preflight.truncated ? (
        // The document is longer than the trial reads, and the parser stopped
        // before counting it — so no number is offered here, because none was
        // measured.
        <>
          This document is longer than the trial reads. Compiling covers the
          whole of it.
        </>
      ) : preflight.pageCount === null ? (
        "Preflight complete."
      ) : preflight.truncated ? (
        <>
          Preflight read the first {preflight.pagesInspected} of{" "}
          {preflight.pageCount} pages — the trial stops there. Compiling covers
          the whole document.
        </>
      ) : (
        <>
          Preflight read all {preflight.pageCount}{" "}
          {preflight.pageCount === 1 ? "page" : "pages"}. Compiling turns them
          into source-linked knowledge.
        </>
      )}
    </p>
  );
}
