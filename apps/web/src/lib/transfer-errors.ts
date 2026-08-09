/**
 * Transfer errors with no API-client dependency.
 *
 * `MultipartTransferError` is raised by both the multipart upload path and the
 * hashing worker, and it extends plain `Error`. Keeping it here lets
 * `browser-hash.ts` throw it without importing `upload-client`, which is the
 * import that put zod on the marketing homepage.
 *
 * `PdfPasswordRequiredError` stays in `upload-client`: it extends `ApiError`,
 * so it genuinely belongs to the side that talks to the API.
 */
export class MultipartTransferError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MultipartTransferError";
  }
}
