// @vitest-environment node
import { spawnSync } from "node:child_process";
import {
  copyFileSync,
  cpSync,
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
 * writes, beside a copy of docs/evidence/artifacts for the declarations to be
 * checked against.
 *
 * Review of #119, non-blocking 1, 2 and 4: a withheld number typed with a digit
 * group separator other than a comma ("5 116", "5.116", fullwidth digits)
 * passed; a declaration whose numerator was edited together with the must_say
 * passed; and a string inside a published claim's numbers was never compared.
 *
 * Review of #120, residuals 1-3: a declaration that read both counts from one
 * field ("5,116/5,116 (100.0%)") passed; an Arabic thousands separator, a
 * middle dot and a tab were not separators; and a date or a version string
 * such as 2015.11.6 or v5.1.16 folded to 5116 and failed the build.
 */

type Claim = Record<string, unknown> & { id: string };
type Pack = { claims: Claim[] };
type Declared = {
  numerator: number;
  numerator_field?: string;
  denominator: number;
  denominator_field?: string;
  evidence: string;
  evidence_sha256: string;
};

const WEB = fileURLToPath(new URL("../..", import.meta.url));
const ARTIFACTS = path.resolve(WEB, "..", "..", "docs", "evidence", "artifacts");
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

function verify(pack: Pack, sources: Record<string, string> = {}, artifacts = true) {
  const root = mkdtempSync(path.join(tmpdir(), "verify-claims-"));
  roots.push(root);
  if (artifacts) {
    cpSync(ARTIFACTS, path.join(root, "docs", "evidence", "artifacts"), { recursive: true });
  }
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

/** Every way 5,116 can be typed and still read as 5,116. */
const SEPARATED = [
  ["an ASCII space", "5 116"],
  ["a no-break space", "5 116"],
  ["a narrow no-break space", "5 116"],
  ["a thin space", "5 116"],
  ["a period", "5.116"],
  ["an apostrophe", "5'116"],
  ["a right single quotation mark", "5’116"],
  ["an underscore", "5_116"],
  ["an Arabic thousands separator", "5٬116"],
  ["a middle dot", "5·116"],
  ["a tab", "5\t116"],
  ["fullwidth digits", "５１１６"],
  ["fullwidth digits and a fullwidth comma", "５，１１６"],
] as const;

describe("verify-claims: a withheld number in any digit-group form", () => {
  it.each(SEPARATED)("fails it in a must_say when written with %s", (_, written) => {
    const pack = shippedPack();
    const accuracy = claim(pack, "benchmark-accuracy");
    accuracy.must_say = `${accuracy.must_say as string} ${written}건.`;

    const result = verify(pack);

    expect(result.status).toBe(1);
    expect(result.output).toMatch(/benchmark-accuracy\.must_say .*blind-quality-detection/);
  });

  it.each(SEPARATED)("fails it in a source comment when written with %s", (_, written) => {
    const result = verify(shippedPack(), {
      "src/lib/note.ts": `// the failure study scored ${written} documents\n`,
    });

    expect(result.status).toBe(1);
    expect(result.output).toContain("src/lib/note.ts:1");
  });

  it("still over-matches: 5116 inside 15116 fails closed", () => {
    const result = verify(shippedPack(), { "src/lib/note.ts": "// 15116\n" });

    expect(result.status).toBe(1);
    expect(result.output).toContain("src/lib/note.ts:1");
  });

  it.each(["5,116.0", "5.116,0", "3.698 5.116", "1 005 116"])(
    "still finds it inside a decimal, a longer numeral or beside another: %s",
    (written) => {
      const result = verify(shippedPack(), { "src/lib/note.ts": `// ${written}\n` });

      expect(result.status).toBe(1);
      expect(result.output).toContain("src/lib/note.ts:1");
    },
  );

  // Only a thousands-grouped numeral folds: one to three digits, then groups of
  // exactly three joined by one separator, not inside a longer chain of it.
  it.each([
    ["a Korean-style date", "2015.11.6"],
    ["a version string", "v5.1.16"],
    ["the tail of a longer dotted chain", "1.5.116"],
    ["the head of a longer dotted chain", "5.116.2"],
  ])("does not read %s as the number: %s", (_, written) => {
    const result = verify(shippedPack(), { "src/lib/note.ts": `// released ${written}\n` });

    expect(result.output).toContain("verify-claims: passed");
    expect(result.status).toBe(0);
  });

  it.each(["3,698/5,116", "5 116 cases"])(
    "fails it in a string inside a published claim's numbers: %s",
    (written) => {
      const pack = shippedPack();
      const numbers = claim(pack, "benchmark-accuracy").numbers as Record<string, unknown>;
      numbers.failure_study = written;

      const result = verify(pack);

      expect(result.status).toBe(1);
      expect(result.output).toContain("benchmark-accuracy.numbers");
    },
  );
});

describe("verify-claims: a declaration is its artifact's own count", () => {
  function declared(pack: Pack): Declared {
    const [first] = declarations(pack);
    if (!first) throw new Error("the shipped pack declares no denominator");
    return first;
  }

  it("fails a numerator edited together with the must_say that writes it", () => {
    const pack = shippedPack();
    const accuracy = claim(pack, "benchmark-accuracy");
    const declaration = declared(pack);
    const before = `${declaration.numerator.toLocaleString("en-US")}/`;
    declaration.numerator = 1;
    for (const field of ["must_say", "must_say_en"]) {
      accuracy[field] = (accuracy[field] as string).replace(before, "1/");
    }

    const result = verify(pack);

    expect(result.status).toBe(1);
    expect(result.output).toMatch(/benchmark-accuracy\.declared_denominators .*numerator 1 /);
  });

  /** Rewrite the counted rate both must_say fields write for the declaration. */
  function rewriteRate(pack: Pack, rate: string) {
    const accuracy = claim(pack, "benchmark-accuracy");
    const { numerator, denominator } = declared(pack);
    const written = `${numerator.toLocaleString("en-US")}/${denominator.toLocaleString("en-US")} (`;
    for (const field of ["must_say", "must_say_en"]) {
      const text = accuracy[field] as string;
      const at = text.indexOf(written);
      if (at === -1) throw new Error(`${field} does not write ${written}`);
      accuracy[field] = text.slice(0, at) + rate + text.slice(text.indexOf(")", at) + 1);
    }
  }

  it("fails a declaration that reads its numerator and denominator from one field", () => {
    // Review of #120 R18: both counts read back correctly from corpus_cases.
    const pack = shippedPack();
    const declaration = declared(pack);
    rewriteRate(pack, "5,116/5,116 (100.0%)");
    declaration.numerator_field = declaration.denominator_field as string;
    declaration.numerator = declaration.denominator;

    const result = verify(pack);

    expect(result.status).toBe(1);
    expect(result.output).toMatch(/benchmark-accuracy\.declared_denominators .*both read from/);
  });

  it("fails a declaration whose numerator exceeds its denominator", () => {
    // Review of #120 R17: a real field of the artifact, read back correctly.
    const pack = shippedPack();
    const declaration = declared(pack);
    rewriteRate(pack, "42,506/5,116 (830.8%)");
    declaration.numerator_field = "total_official_failure_records";
    declaration.numerator = 42506;

    const result = verify(pack);

    expect(result.status).toBe(1);
    expect(result.output).toMatch(/benchmark-accuracy\.declared_denominators .*is not a rate/);
  });

  it("fails a declaration whose denominator is not the field the withheld claim withholds", () => {
    // The withheld claim names the field it withholds, from the artifact both
    // cite. A declaration lets that number through only when it reads its
    // denominator from that same field.
    const pack = shippedPack();
    const numbers = claim(pack, "blind-quality-detection").numbers as Record<string, unknown>;
    numbers.documents_scored = numbers.corpus_cases;
    delete numbers.corpus_cases;

    const result = verify(pack);

    expect(result.status).toBe(1);
    expect(result.output).toMatch(/benchmark-accuracy\.must_say_en .*documents_scored/);
  });

  it("fails a declaration that names no field to read its count from", () => {
    const pack = shippedPack();
    delete declared(pack).numerator_field;

    const result = verify(pack);

    expect(result.status).toBe(1);
    expect(result.output).toMatch(/benchmark-accuracy\.declared_denominators .*numerator/);
  });

  it("fails a declaration whose file does not hash to its digest", () => {
    const pack = shippedPack();
    // Another file the claim cites, under the digest of the one it should be.
    declared(pack).evidence = (claim(pack, "benchmark-accuracy").evidence as string[])[0] as string;

    const result = verify(pack);

    expect(result.status).toBe(1);
    expect(result.output).toMatch(/benchmark-accuracy\.declared_denominators .*hashes to/);
  });

  it("fails a declaration whose artifact is not in the checkout", () => {
    const result = verify(shippedPack(), {}, false);

    expect(result.status).toBe(1);
    expect(result.output).toMatch(/benchmark-accuracy\.declared_denominators .*does not exist/);
  });
});
