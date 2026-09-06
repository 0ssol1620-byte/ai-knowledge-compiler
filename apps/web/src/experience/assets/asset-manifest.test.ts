import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  APPROVED_PROVIDERS,
  auditAssets,
  renderLicenseLedger,
  validateEntry,
  type AssetManifest,
  type ThirdPartyAsset,
} from "./asset-manifest";

/**
 * This test *is* the §31 release gate.
 *
 * The brief writes the gate as a build step, but CI here already runs the unit
 * suite on every push, and a gate that lives where the tests live is a gate
 * that cannot be skipped by running a different build command. If the asset
 * root grows a file nobody declared, this goes red.
 */

const WEB_ROOT = path.resolve(__dirname, "../../..");
const MANIFEST_PATH = path.join(WEB_ROOT, "src/content/asset-manifest.json");
const LEDGER_PATH = path.join(WEB_ROOT, "src/content/license-ledger.md");

function loadManifest(): AssetManifest {
  return JSON.parse(readFileSync(MANIFEST_PATH, "utf8")) as AssetManifest;
}

/** Every file under the asset root, as root-relative forward-slash paths. */
function walkAssetRoot(root: string): string[] {
  const abs = path.join(WEB_ROOT, root);
  if (!existsSync(abs)) return [];
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) {
        walk(full);
        continue;
      }
      // .gitkeep and friends are structure, not assets.
      if (name.startsWith(".")) continue;
      out.push(path.relative(abs, full).split(path.sep).join("/"));
    }
  };
  walk(abs);
  return out;
}

describe("§31 asset manifest release gate", () => {
  const manifest = loadManifest();

  it("has a manifest at the path §31 names", () => {
    expect(existsSync(MANIFEST_PATH)).toBe(true);
    expect(manifest.version).toBe(1);
  });

  it("declares every file that ships under the asset root", () => {
    const files = walkAssetRoot(manifest.asset_root);
    const violations = auditAssets(manifest, files);
    if (violations.length > 0) {
      const report = violations
        .map((v) => `  [${v.kind}] ${v.subject}\n      ${v.detail}`)
        .join("\n");
      throw new Error(
        `${violations.length} asset gate violation(s):\n${report}\n\n` +
          `Fix the manifest at src/content/asset-manifest.json. §17.4: ` +
          `no manifest entry, no production use.`,
      );
    }
    expect(violations).toEqual([]);
  });

  it("keeps the generated ledger in step with the manifest", () => {
    // The ledger is generated, never hand-edited — the same rule the claims
    // pack follows. Drift means someone edited the readable copy and left the
    // machine-checked one behind.
    expect(existsSync(LEDGER_PATH)).toBe(true);
    expect(readFileSync(LEDGER_PATH, "utf8").trimEnd()).toBe(
      renderLicenseLedger(manifest).trimEnd(),
    );
  });
});

describe("§17 licence rules", () => {
  const base: ThirdPartyAsset = {
    asset_id: "reality_workspace_003",
    local_path: "reality/workspace/workspace_003.webm",
    origin: "third-party",
    source_provider: "Pexels",
    source_url: "https://www.pexels.com/video/123456/",
    author_or_contributor: "A. Contributor",
    license_name: "Pexels License",
    license_url: "https://www.pexels.com/license/",
    downloaded_at: "2026-08-21",
    commercial_use_checked: true,
    third_party_risk: "no visible logo, no identifiable face",
    page_usage: ["home"],
    transformations: ["crop", "grade"],
    approved_by: "founder",
  };

  it("accepts a complete §17.4 receipt", () => {
    expect(validateEntry(base)).toEqual([]);
  });

  it("rejects a receipt missing any required field", () => {
    const v = validateEntry({ ...base, license_url: "" });
    expect(v.map((x) => x.kind)).toContain("missing-field");
  });

  it("refuses an unchecked commercial-use flag", () => {
    // Mixkit ships Free and Restricted items side by side, so "we did not
    // check" and "it is fine" must not be the same state.
    const v = validateEntry({ ...base, commercial_use_checked: false });
    expect(v.map((x) => x.kind)).toContain("commercial-use-unchecked");
  });

  it("refuses a provider outside the §17.2 approved stack", () => {
    const v = validateEntry({
      ...base,
      source_provider: "Shutterstock" as never,
    });
    expect(v.map((x) => x.kind)).toContain("unapproved-provider");
  });

  it("refuses a §17.3 mood-reference source used as production", () => {
    const v = validateEntry({
      ...base,
      source_url: "https://www.pinterest.com/pin/123/",
    });
    expect(v.map((x) => x.kind)).toContain("rejected-provider");
  });

  it("refuses a synthetic fixture claiming to be real evidence", () => {
    const v = validateEntry({
      asset_id: "atlas_plan_r4",
      local_path: "documents/atlas/plan_r4.svg",
      origin: "synthetic-fixture",
      generated_by: "document-forge",
      page_usage: ["home", "evidence"],
      depicts_real_evidence: true,
    });
    expect(v.map((x) => x.kind)).toContain("fabricated-evidence");
  });

  it("catches an undeclared file on disk", () => {
    const v = auditAssets(
      { version: 1, asset_root: "public/assets/tavonel", assets: [] },
      ["reality/workspace/mystery.webm"],
    );
    expect(v.map((x) => x.kind)).toContain("undeclared-file");
  });

  it("catches a manifest entry with no file behind it", () => {
    const v = auditAssets(
      { version: 1, asset_root: "public/assets/tavonel", assets: [base] },
      [],
    );
    expect(v.map((x) => x.kind)).toContain("missing-file");
  });

  it("lists exactly the seven providers §17.2 approves", () => {
    expect([...APPROVED_PROVIDERS]).toEqual([
      "Pexels",
      "Unsplash",
      "Mixkit",
      "Poly Haven",
      "ambientCG",
      "Fontshare",
      "Lucide",
    ]);
  });
});
