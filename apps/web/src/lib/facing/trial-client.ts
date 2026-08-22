import { browserSha256 } from "@/lib/browser-hash";

import type { DroppedFile } from "./dropped-file";

/**
 * Client for the anonymous trial ingest contract — ADR-006.
 *
 * The hero has two modes and the difference is visible to the visitor, which is
 * the point:
 *
 *   flag off  the file is read in this browser and never sent. "Not uploaded"
 *             is literally true.
 *   flag on   the file is sent, scanned, and preflighted, and the copy says so
 *             — what is sent, how long it is kept, and when it is deleted.
 *
 * Nothing here decides which mode is honest. `TRIAL_INGEST_ENABLED` mirrors the
 * server flag, and the server refuses with 404 when they disagree, so a
 * mis-set build fails closed rather than promising an upload that cannot
 * happen.
 */

export const TRIAL_INGEST_ENABLED =
  process.env.NEXT_PUBLIC_AKC_TRIAL_INGEST_ENABLED === "true";

const API_URL = process.env.NEXT_PUBLIC_AKC_API_URL ?? "http://localhost:8000";

export type TrialSession = {
  sessionId: string;
  expiresAt: string;
  maxBytes: number;
  maxPages: number;
};

export type TrialPreflight = {
  status:
    | "UPLOADED"
    | "SECURITY_SCANNING"
    | "SECURITY_VERIFIED"
    | "SECURITY_REJECTED"
    | "PREFLIGHTING"
    | "PREFLIGHTED"
    | "FAILED";
  pageCount: number | null;
  pagesInspected: number;
  truncated: boolean;
  /** Named refusal reason when the document was rejected. */
  errorCode: string | null;
  expiresAt: string;
};

export class TrialIngestError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "TrialIngestError";
  }
}

async function readError(response: Response, fallback: string) {
  let code = "TRIAL_ERROR";
  try {
    const body = await response.json();
    code = body?.error?.code ?? code;
  } catch {
    // A non-JSON body is itself the error; the status carries the meaning.
  }
  return new TrialIngestError(messageFor(code, fallback), code, response.status);
}

/** Server codes the visitor can act on. Anything else gets the generic line. */
function messageFor(code: string, fallback: string) {
  switch (code) {
    case "TRIAL_FILE_TOO_LARGE":
      return "That file is larger than the trial limit.";
    case "UNSUPPORTED_FILE_TYPE":
      return "The compiler does not read that format yet.";
    case "TRIAL_DOCUMENT_ALREADY_SUBMITTED":
      return "This trial already has a document.";
    case "TRIAL_SESSION_NOT_FOUND":
      return "This trial has expired. Start another.";
    case "CAPTCHA_REQUIRED":
      return "Please confirm you are not a robot to continue.";
    case "RATE_LIMITED":
      return "Too many trials from this network. Try again later.";
    case "NOT_FOUND":
      // The capability is off server-side. Never surfaced as "missing page".
      return "The live trial is not available right now.";
    default:
      return fallback;
  }
}

export async function createTrialSession(): Promise<TrialSession> {
  const response = await fetch(`${API_URL}/v1/trial/sessions`, {
    method: "POST",
  });
  if (!response.ok) {
    throw await readError(response, "Could not start a trial just now.");
  }
  const body = await response.json();
  return {
    sessionId: body.session_id,
    expiresAt: body.expires_at,
    maxBytes: body.max_bytes,
    maxPages: body.max_pages,
  };
}

/**
 * Send the file, then confirm the server sees the digest this browser computed.
 *
 * The digest is computed locally either way — under the flag it is the
 * integrity check, and without it, it is what the hero shows. One code path,
 * so the number on screen is the number that was sent.
 */
export async function uploadTrialDocument(
  session: TrialSession,
  file: File,
  inspected: DroppedFile,
): Promise<{ documentId: string; preflight: TrialPreflight }> {
  const sha256 = inspected.sha256 || (await browserSha256(file));

  const initiated = await fetch(
    `${API_URL}/v1/trial/sessions/${session.sessionId}/uploads`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: file.name,
        size: file.size,
        content_type: file.type || "application/octet-stream",
        sha256,
      }),
    },
  );
  if (!initiated.ok) {
    throw await readError(initiated, "Could not accept that document.");
  }
  const target = await initiated.json();

  // In production this is an absolute presigned S3 URL and the bytes never
  // touch the API. The development adapter returns a path on the API instead,
  // and a relative URL would resolve against the web origin rather than the
  // API's — so only the relative form gets a prefix.
  const uploadUrl: string = target.upload_url.startsWith("/")
    ? `${API_URL}${target.upload_url}`
    : target.upload_url;

  const stored = await fetch(uploadUrl, {
    method: "PUT",
    headers: target.headers ?? {},
    body: file,
  });
  if (!stored.ok) {
    throw new TrialIngestError(
      "The upload did not complete.",
      "UPLOAD_FAILED",
      stored.status,
    );
  }

  // Storing the bytes is not submitting them. Completion is what runs the
  // security path, and until it is called the document sits in quarantine
  // having been read by nothing.
  const completed = await fetch(
    `${API_URL}/v1/trial/sessions/${session.sessionId}` +
      `/uploads/${target.upload_id}/complete`,
    { method: "POST" },
  );
  if (!completed.ok) {
    throw await readError(completed, "The document could not be checked.");
  }

  return {
    documentId: target.document_id,
    preflight: toPreflight(await completed.json()),
  };
}

export async function readTrialPreflight(
  session: TrialSession,
): Promise<TrialPreflight> {
  const response = await fetch(
    `${API_URL}/v1/trial/sessions/${session.sessionId}`,
  );
  if (!response.ok) {
    throw await readError(response, "Could not read the result.");
  }
  return toPreflight(await response.json());
}

/** One decoder, so completion and polling cannot disagree about a field. */
function toPreflight(body: Record<string, unknown>): TrialPreflight {
  return {
    status: body.status as TrialPreflight["status"],
    pageCount: (body.page_count as number | null) ?? null,
    pagesInspected: (body.pages_inspected as number) ?? 0,
    truncated: Boolean(body.truncated),
    errorCode: (body.error_code as string | null) ?? null,
    expiresAt: body.expires_at as string,
  };
}

/** Terminal states — polling stops here. */
export function isSettled(status: TrialPreflight["status"]): boolean {
  return (
    status === "PREFLIGHTED" ||
    status === "SECURITY_REJECTED" ||
    status === "FAILED"
  );
}

/** How long the visitor's copy survives, phrased for the privacy line. */
export function retentionSentence(expiresAt: string): string {
  const minutes = Math.max(
    1,
    Math.round((Date.parse(expiresAt) - Date.now()) / 60_000),
  );
  return minutes >= 60
    ? `Deleted automatically in about ${Math.round(minutes / 60)} hour${minutes >= 120 ? "s" : ""}.`
    : `Deleted automatically in about ${minutes} minutes.`;
}
