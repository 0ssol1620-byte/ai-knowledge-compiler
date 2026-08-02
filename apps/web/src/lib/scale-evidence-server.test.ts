import { describe, expect, it } from "vitest";

import { scaleEvidenceServerConfig } from "@/lib/scale-evidence-server";

describe("scaleEvidenceServerConfig", () => {
  it("binds scale evidence to the server deployment revision", () => {
    expect(
      scaleEvidenceServerConfig({
        AKC_SCALE_TESTS_ENABLED: "true",
        AKC_SCALE_ENVIRONMENT: "performance",
        AKC_DEPLOYMENT_REVISION: "a".repeat(40),
        AKC_SCALE_FIXTURE_SHA256: `sha256:${"b".repeat(64)}`,
        NEXT_PUBLIC_AKC_DEPLOYMENT_REVISION: "c".repeat(40),
      }),
    ).toEqual({
      enabled: "true",
      environment: "performance",
      targetRevision: "a".repeat(40),
      fixtureSha256: `sha256:${"b".repeat(64)}`,
    });
  });
});
