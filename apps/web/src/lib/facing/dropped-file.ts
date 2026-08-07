import { browserSha256 } from "@/lib/upload-client";
import {
  QUICK_CONVERT_MAX_FILE_BYTES,
  QUICK_CONVERT_MAX_FILE_LABEL,
} from "@/lib/upload-policy";

/**
 * What can be said about a dropped file without a server — DESIGN_MASTER_V3
 * §12.2 state ③.
 *
 * The hero sits on the marketing surface, where there is no session, and every
 * ingest path in the API is tenant-scoped. §24.4 stops on "a backend contract
 * change is needed", so nothing here uploads anything.
 *
 * What is computed is computed for real: the size and type come from the File,
 * and the digest is the same SHA-256 the authenticated upload path sends as
 * its integrity check. That makes the claim on screen — the file did not leave
 * this device — literally true rather than a marketing line, and it is the
 * product's own argument demonstrated in the first interaction.
 *
 * What cannot be known without a server is reported as unknown. §25.7 rejects
 * invented figures, and a page count needs a parser that does not ship until
 * W4 brings in PDF.js.
 */

export type DroppedFile = {
  name: string;
  /** Bytes, as reported by the File object. */
  size: number;
  /** MIME type, or "" when the browser could not determine one. */
  type: string;
  /** Lowercase extension without the dot, or "" when there is none. */
  extension: string;
  /** Hex SHA-256 of the file contents, computed in this browser. */
  sha256: string;
  /** Whether this repository's pipeline claims support for the format. */
  supported: boolean;
  /** Set when the file cannot proceed, with the reason to show. */
  rejection?: string;
};

/**
 * Formats the pipeline accepts today. Kept in step with the accept attribute
 * on the authenticated upload input; a format missing here is reported as
 * unrecognised rather than silently accepted.
 */
const SUPPORTED_EXTENSIONS = new Set([
  "pdf",
  "docx",
  "pptx",
  "xlsx",
  "html",
  "htm",
  "md",
  "txt",
  "png",
  "jpg",
  "jpeg",
  "tif",
  "tiff",
  "webp",
]);

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  if (dot <= 0 || dot === name.length - 1) return "";
  return name.slice(dot + 1).toLowerCase();
}

/**
 * Reads a dropped file and reports only what this browser can establish.
 *
 * Hashing streams in 4 MB slices, so a large file does not materialise in
 * memory. The caller is expected to show a working state: on a mid-range
 * laptop a 50 MB file takes a few hundred milliseconds.
 */
export async function inspectDroppedFile(file: File): Promise<DroppedFile> {
  const extension = extensionOf(file.name);
  const base: Omit<DroppedFile, "sha256"> = {
    name: file.name,
    size: file.size,
    type: file.type,
    extension,
    supported: SUPPORTED_EXTENSIONS.has(extension),
  };

  if (file.size === 0) {
    return { ...base, sha256: "", rejection: "That file is empty." };
  }

  if (file.size > QUICK_CONVERT_MAX_FILE_BYTES) {
    return {
      ...base,
      sha256: "",
      rejection: `Files are limited to ${QUICK_CONVERT_MAX_FILE_LABEL} each.`,
    };
  }

  if (!base.supported) {
    return {
      ...base,
      sha256: "",
      rejection: extension
        ? `.${extension} is not a format the compiler reads yet.`
        : "That file has no extension the compiler recognises.",
    };
  }

  return { ...base, sha256: await browserSha256(file) };
}

/** Binary units, because that is what the size is measured in. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

/**
 * A digest is 64 hex characters — too long to read and too important to
 * truncate silently. Shows the ends and marks the elision, the way a commit
 * hash or a certificate fingerprint is shown.
 */
export function abbreviateDigest(hex: string): string {
  if (hex.length <= 20) return hex;
  return `${hex.slice(0, 10)}…${hex.slice(-10)}`;
}
