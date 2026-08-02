import { describe, expect, it } from "vitest";

import { integrityCompatibilityTarget } from "@/lib/integrity-compatibility";

describe("legacy review compatibility boundary", () => {
  it("redirects an empty legacy route to the Integrity Console", () => {
    expect(integrityCompatibilityTarget({})).toBe("/integrity");
  });

  it("preserves collection, job, and repeated query context", () => {
    expect(
      integrityCompatibilityTarget({
        collection: "018f0000-0000-7000-8000-000000000001",
        job: "018f0000-0000-7000-8000-000000000002",
        filter: ["unresolved", "quarantined"],
        omitted: undefined,
        access_token: "must-not-be-forwarded",
      }),
    ).toBe(
      "/integrity?collection=018f0000-0000-7000-8000-000000000001&job=018f0000-0000-7000-8000-000000000002&filter=unresolved&filter=quarantined",
    );
  });

  it("drops unknown and secret-bearing query fields instead of reflecting them", () => {
    expect(
      integrityCompatibilityTarget({
        collection: "collection-1",
        redirect_uri: "https://attacker.invalid",
        password: "never-forward",
        token: "never-forward",
      }),
    ).toBe("/integrity?collection=collection-1");
  });

  it("binds a document route without discarding existing context", () => {
    expect(
      integrityCompatibilityTarget(
        { document: "stale", collection: "collection-1", reference: "1" },
        { documentId: "document-9" },
      ),
    ).toBe(
      "/integrity?document=document-9&collection=collection-1&reference=1",
    );
  });
});
