// @vitest-environment node
import { spawnSync } from "node:child_process";
import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

/**
 * `scripts/verify-claims.mjs`, run against the shipped pack with one change.
 *
 * Review PR-111 N-a: the withheld-figures rule failed a source comment that
 * wrote the failure study's corpus size, while the same number rendered on the
 * home page through benchmark-accuracy's must_say, because the scan skipped
 * src/data/claims/. The number has to be there — every rate carries its
 * denominator — so the pack now declares it, and the script allows it only as
 * that declaration and nowhere else.
 *
 * The script resolves everything from its own location, so each case copies it
 * into a throwaway apps/web whose src/ holds the pack and whatever the case
 * writes.
 */

type Claim = Record<string, unknown> & { id: string };
type Pack = { claims: Claim[] };
type Declared = { denominator: number; evidence_sha256: string };

const WEB = fileURLToPath(new URL("../..", import.meta.url));
const SCRIPT = path.join(WEB, "scripts", "verify-claims.mjs");
const PACK = path.join(WEB, "src", "data", "claims", "public-claims-pack.json");

function shippedPack(): Pack {
  return JSON.parse(readFileSync(PACK, "utf8")) as Pack;
}

function claim(pack: Pack, id: string): Claim {
  const found = pack.claims.find((candidate) => candidate.id === id);
  if (!found) throw new Error(`no claim ${id}`);
  return found;
}

function declarations(pack: Pack): Declared[] {
  return (claim(pack, "benchmark-accuracy").declared_denominators ?? []) as Declared[];
}

/** The withheld number the home page legitimately renders. */
function corpusCases(pack: Pack): number {
  const numbers = claim(pack, "blind-quality-detection").numbers as Record<string, number>;
  return numbers.corpus_cases as number;
}

const roots: string[] = [];
afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function verify(pack: Pack, sources: Record<string, string> = {}) {
  const root = mkdtempSync(path.join(tmpdir(), "verify-claims-"));
  roots.push(root);
  const web = path.join(root, "apps", "web");
  const files: Record<string, string> = {
    "src/data/claims/public-claims-pack.json": JSON.stringify(pack),
    ...sources,
  };
  for (const [relative, text] of Object.entries(files)) {
    mkdirSync(path.dirname(path.join(web, relative)), { recursive: true });
    writeFileSync(path.join(web, relative), text);
  }
  mkdirSync(path.join(web, "scripts"));
  copyFileSync(SCRIPT, path.join(web, "scripts", "verify-claims.mjs"));
  const run = spawnSync(process.execPath, [path.join(web, "scripts", "verify-claims.mjs")], {
    encoding: "utf8",
  });
  return { status: run.status, output: `${run.stdout}${run.stderr}` };
}

describe("verify-claims: withheld figures", () => {
  it("passes the shipped pack, whose must_say writes the withheld number as a declared denominator", () => {
    const pack = shippedPack();
    const written = corpusCases(pack).toLocaleString("en-US");
    expect(claim(pack, "benchmark-accuracy").must_say_en).toContain(`/${written} (`);
    expect(declarations(pack).map((declared) => declared.denominator)).toEqual([
      corpusCases(pack),
    ]);

    const result = verify(pack);

    expect(result.output).toContain("verify-claims: passed");
    expect(result.status).toBe(0);
  });

  it("fails a withheld number inside an approved must_say that declares no denominator", () => {
    const pack = shippedPack();
    delete claim(pack, "benchmark-accuracy").declared_denominators;

    const result = verify(pack);

    expect(result.status).toBe(1);
    expect(result.output).toMatch(/benchmark-accuracy\.must_say_en .*blind-quality-detection/);
    expect(result.output).toMatch(/benchmark-accuracy\.must_say .*blind-quality-detection/);
  });

  it("fails a declaration that is not bound to the withheld claim's artifact hash", () => {
    const pack = shippedPack();
    const [declared] = declarations(pack);
    if (!declared) throw new Error("the shipped pack declares no denominator");
    declared.evidence_sha256 = `sha256:${"0".repeat(64)}`;

    const result = verify(pack);

    expect(result.status).toBe(1);
    expect(result.output).toContain("blind-quality-detection exposes corpus_cases");
  });

  it("fails a declaration that no must_say uses any more", () => {
    const pack = shippedPack();
    const accuracy = claim(pack, "benchmark-accuracy");
    const written = corpusCases(pack).toLocaleString("en-US");
    for (const field of ["must_say", "must_say_en"]) {
      const text = accuracy[field] as string;
      accuracy[field] = text.slice(0, text.indexOf(`/${written} (`)).trimEnd();
    }

    const result = verify(pack);

    expect(result.status).toBe(1);
    expect(result.output).toContain("is declared but not written");
  });

  it("still fails the same number in a source comment under src/", () => {
    const pack = shippedPack();
    const written = corpusCases(pack).toLocaleString("en-US");

    const result = verify(pack, {
      "src/lib/note.ts": `// 72.3% of the ${written} documents in the failure study\n`,
    });

    expect(result.status).toBe(1);
    expect(result.output).toContain("src/lib/note.ts:1");
  });

  it("fails a withheld number carried in a published claim's numbers", () => {
    const pack = shippedPack();
    const numbers = claim(pack, "benchmark-accuracy").numbers as Record<string, unknown>;
    numbers.documents_scored = corpusCases(pack);

    const result = verify(pack);

    expect(result.status).toBe(1);
    expect(result.output).toContain("benchmark-accuracy.numbers");
  });
});
