import { describe, expect, it } from "vitest";

import { buildScaleEvidenceSpec } from "@/components/system/scale-evidence-bridge";

const revision = "a".repeat(40);
const fixture = `sha256:${"b".repeat(64)}`;

describe("buildScaleEvidenceSpec", () => {
  it("binds the exact synthetic dataset to revision and fixture evidence", () => {
    expect(
      buildScaleEvidenceSpec({
        enabled: "true",
        environment: "performance",
        profile: "workspace_10000_blocks",
        targetRevision: revision,
        fixtureSha256: fixture,
      }),
    ).toEqual(
      expect.objectContaining({
        ready: false,
        classification: "harness_contract",
        nonproduction_only: true,
        release_gate_closed: false,
        profile: "workspace_10000_blocks",
        target_revision: revision,
        fixture_sha256: fixture,
        dataset: { blocks: 10_000 },
        virtualization: expect.objectContaining({
          strategy: "bounded_window",
          total_items: 10_000,
          rendered_items: 32,
          renderer_component: "MarkdownWorkspace",
          data_contract: "CanonicalBlock[]",
        }),
      }),
    );
  });

  it.each([
    { enabled: "false", environment: "performance", targetRevision: revision, fixtureSha256: fixture },
    { enabled: "true", environment: "production", targetRevision: revision, fixtureSha256: fixture },
    { enabled: "true", environment: "performance", targetRevision: "main", fixtureSha256: fixture },
    { enabled: "true", environment: "performance", targetRevision: revision, fixtureSha256: "fixture" },
  ])("fails closed for an invalid gate", (gate) => {
    expect(
      buildScaleEvidenceSpec({
        ...gate,
        profile: "processing_ui_1000_pages",
      }),
    ).toBeUndefined();
  });
});
