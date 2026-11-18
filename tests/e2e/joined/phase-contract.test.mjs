/**
 * phase-contract.mjs: the phase interface refuses anything but declared enums and bounded counts, the summary accepts only
 * phases that went through runPhase, and the real workflow file and harness are checked through the same functions the
 * harness calls.
 */
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import {
  COUNT, FLAG_NAMES, MAX_COUNT, PHASE_NAMES, SUMMARY_KEYS, SUMMARY_SCHEMA, PhaseContractError, booleanFlagState, buildJoinedSummary,
  codeFlagState, definePhase, deployCapabilities, runPhase, validatePhaseSummary, writeJoinedSummary,
} from "./phase-contract.mjs";

const here = import.meta.dirname;
const workflowText = readFileSync(path.resolve(here, "../../../.github/workflows/joined-e2e.yml"), "utf8");
const harnessText = readFileSync(path.join(here, "joined-e2e.mjs"), "utf8");

const noop = () => {};
const input = (overrides = {}) => ({ app: noop, sql: noop, check: noop, hop: noop, step: noop, state: {}, deadline: Date.now() + 60_000, ...overrides });
const modify = result => definePhase({ name: "modify", fields: { pointer_advanced: ["yes", "no"], refused_promotes: COUNT }, run: async () => result });
const refusedWith = code => error => error instanceof PhaseContractError && error.code === code;
const SHA = "a".repeat(40), SHA2 = "b".repeat(40);
const baseSummary = (overrides = {}) => ({
  trigger: "workflow_dispatch", coreSha: SHA, foundationSha: SHA2,
  flags: { intake_triage_rollout: "off", core_customer_data: "on" },
  fresh: { value: true, proof: "auth_users_empty_before_fixtures" }, deployActions: 0, phases: {}, ...overrides,
});

test("a phase returning only declared enums and counts passes, in declaration order", async () => {
  const out = await runPhase(modify({ refused_promotes: 1, outcome: "met", pointer_advanced: "no" }), input());
  assert.deepEqual(Object.entries(out), [["outcome", "met"], ["pointer_advanced", "no"], ["refused_promotes", 1]]);
  assert.ok(Object.isFrozen(out));
});

test("an undeclared field is not filled in", async () => {
  assert.deepEqual(await runPhase(modify({ outcome: "not_run" }), input()), { outcome: "not_run" });
});

test("a string field, an unknown enum or a field outside the allowlist is refused", async () => {
  await assert.rejects(runPhase(modify({ outcome: "met", note: "free text" }), input()), refusedWith("PHASE_FIELD_NOT_ALLOWED"));
  await assert.rejects(runPhase(modify({ outcome: "met", document_id: "doc-1" }), input()), refusedWith("PHASE_FIELD_NOT_ALLOWED"));
  await assert.rejects(runPhase(modify({ outcome: "met", pointer_advanced: "maybe" }), input()), refusedWith("PHASE_ENUM_INVALID"));
  await assert.rejects(runPhase(modify({ outcome: "met", refused_promotes: "1" }), input()), refusedWith("PHASE_COUNT_INVALID"));
  await assert.rejects(runPhase(modify({ outcome: "passed" }), input()), refusedWith("PHASE_OUTCOME_INVALID"));
  await assert.rejects(runPhase(modify({ pointer_advanced: "no" }), input()), refusedWith("PHASE_OUTCOME_INVALID"));
});

test("the class: every count or enum value that is not a declared token or a bounded non-negative integer is refused", async () => {
  for (const bad of [Number.NaN, Infinity, -Infinity, -1, 1.5, MAX_COUNT + 1, null, undefined, true, "3", [], {}, 2n]) {
    await assert.rejects(runPhase(modify({ outcome: "met", refused_promotes: bad }), input()), refusedWith("PHASE_COUNT_INVALID"), String(bad));
  }
  for (const bad of [null, undefined, 0, true, "YES", "yes ", ["yes"], { yes: 1 }]) {
    await assert.rejects(runPhase(modify({ outcome: "met", pointer_advanced: bad }), input()), refusedWith("PHASE_ENUM_INVALID"), String(bad));
  }
  for (const bad of [null, "met", [], new Map(), Object.create({ outcome: "met" })]) {
    await assert.rejects(runPhase(modify(bad), input()), PhaseContractError);
  }
});

test("an error names a token key, never a value or a free-text key", async () => {
  const error = await runPhase(modify({ outcome: "met", "Archive retention is 73 days": 1 }), input()).catch(e => e);
  assert.equal(error.code, "PHASE_FIELD_NOT_ALLOWED");
  assert.doesNotMatch(error.message, /73 days/);
  const valueError = await runPhase(modify({ outcome: "met", pointer_advanced: "Archive retention is 73 days" }), input()).catch(e => e);
  assert.doesNotMatch(valueError.message, /73 days/);
});

test("the phase input is exactly {app, sql, check, hop, step, state, deadline}", async () => {
  const phase = modify({ outcome: "met" });
  await assert.rejects(runPhase(phase, { ...input(), extra: 1 }), refusedWith("PHASE_INPUT_KEYS"));
  const { state: _state, ...missing } = input();
  await assert.rejects(runPhase(phase, missing), refusedWith("PHASE_INPUT_KEYS"));
  await assert.rejects(runPhase(phase, input({ sql: "select 1" })), refusedWith("PHASE_INPUT_NOT_A_FUNCTION"));
  await assert.rejects(runPhase(phase, input({ state: null })), refusedWith("PHASE_STATE_NOT_AN_OBJECT"));
  for (const deadline of [Number.NaN, Infinity, 0, -1, "60"]) {
    await assert.rejects(runPhase(phase, input({ deadline })), refusedWith("PHASE_DEADLINE_INVALID"));
  }
  let seen;
  await runPhase(definePhase({ name: "export", fields: {}, run: async received => { seen = Object.keys(received).sort(); return { outcome: "met" }; } }), input());
  assert.deepEqual(seen, ["app", "check", "deadline", "hop", "sql", "state", "step"]);
});

test("definePhase refuses an unknown name, a bad field declaration and a phase not made by it", async () => {
  assert.throws(() => definePhase({ name: "deploy", fields: {}, run: noop }), refusedWith("PHASE_NAME_UNKNOWN"));
  assert.throws(() => definePhase({ name: "modify", fields: { outcome: COUNT }, run: noop }), refusedWith("PHASE_FIELD_NAME_INVALID"));
  assert.throws(() => definePhase({ name: "modify", fields: { "Bad Name": COUNT }, run: noop }), refusedWith("PHASE_FIELD_NAME_INVALID"));
  assert.throws(() => definePhase({ name: "modify", fields: { kind: ["a", "a"] }, run: noop }), refusedWith("PHASE_FIELD_SPEC_INVALID"));
  assert.throws(() => definePhase({ name: "modify", fields: { kind: ["Free text value"] }, run: noop }), refusedWith("PHASE_FIELD_SPEC_INVALID"));
  assert.throws(() => definePhase({ name: "modify", fields: { kind: "text" }, run: noop }), refusedWith("PHASE_FIELD_SPEC_INVALID"));
  assert.throws(() => definePhase({ name: "modify", fields: {}, run: noop, schema: {} }), refusedWith("PHASE_DEFINITION_UNKNOWN_KEY"));
  const forged = { name: "modify", fields: { note: ["x"] }, run: async () => ({ outcome: "met" }) };
  await assert.rejects(runPhase(forged, input()), refusedWith("PHASE_NOT_DEFINED"));
  assert.throws(() => validatePhaseSummary(forged, { outcome: "met" }), refusedWith("PHASE_NOT_DEFINED"));
  assert.deepEqual(PHASE_NAMES, ["partial", "modify", "revoke", "export", "rebuild"]);
});

test("the summary is written with fixed keys and accepts only phases that went through runPhase, under their own name", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "phase-contract-"));
  try {
    const file = path.join(dir, "joined-summary.json");
    const modified = await runPhase(modify({ outcome: "not_met", refused_promotes: 2 }), input());
    writeJoinedSummary(file, baseSummary({ phases: { modify: modified } }));
    const written = JSON.parse(readFileSync(file, "utf8"));
    assert.deepEqual(Object.keys(written), [...SUMMARY_KEYS]);
    assert.equal(written.schema, SUMMARY_SCHEMA);
    assert.deepEqual(written.phases, { modify: { outcome: "not_met", refused_promotes: 2 } });
    assert.deepEqual(Object.keys(written.flags), [...FLAG_NAMES]);

    assert.throws(() => buildJoinedSummary(baseSummary({ phases: { modify: { outcome: "met" } } })), refusedWith("SUMMARY_PHASE_NOT_VALIDATED"));
    assert.throws(() => buildJoinedSummary(baseSummary({ phases: { revoke: modified } })), refusedWith("SUMMARY_PHASE_NOT_VALIDATED"));
    assert.throws(() => buildJoinedSummary(baseSummary({ phases: { deploy: modified } })), refusedWith("SUMMARY_PHASE_UNKNOWN"));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("the summary refuses a non-40-hex SHA, an unknown trigger, flag or state, an inconsistent fresh and a bad count", () => {
  const cases = [
    [{ coreSha: SHA.slice(1) }, "SUMMARY_SHA_INVALID"], [{ foundationSha: SHA.toUpperCase() }, "SUMMARY_SHA_INVALID"],
    [{ coreSha: undefined }, "SUMMARY_SHA_INVALID"], [{ trigger: "push" }, "SUMMARY_TRIGGER_INVALID"],
    [{ trigger: undefined }, "SUMMARY_TRIGGER_INVALID"],
    [{ flags: { intake_triage_rollout: "off" } }, "SUMMARY_FLAGS_KEYS"],
    [{ flags: { intake_triage_rollout: "off", core_customer_data: "on", revision_compile: "on" } }, "SUMMARY_FLAGS_KEYS"],
    [{ flags: { intake_triage_rollout: "unknown", core_customer_data: "on" } }, "SUMMARY_FLAG_STATE_INVALID"],
    [{ fresh: { value: true, proof: "not_reached" } }, "SUMMARY_FRESH_INVALID"],
    [{ fresh: { value: false, proof: "auth_users_empty_before_fixtures" } }, "SUMMARY_FRESH_INVALID"],
    [{ fresh: { value: "true", proof: "auth_users_empty_before_fixtures" } }, "SUMMARY_FRESH_INVALID"],
    [{ deployActions: null }, "SUMMARY_DEPLOY_ACTIONS_INVALID"], [{ deployActions: Number.NaN }, "SUMMARY_DEPLOY_ACTIONS_INVALID"],
    [{ deployActions: -1 }, "SUMMARY_DEPLOY_ACTIONS_INVALID"], [{ phases: [] }, "SUMMARY_PHASES_NOT_AN_OBJECT"],
    [{ extra: 1 }, "SUMMARY_KEY_NOT_ALLOWED"],
  ];
  for (const [overrides, code] of cases) assert.throws(() => buildJoinedSummary(baseSummary(overrides)), refusedWith(code), JSON.stringify(overrides));
  assert.deepEqual(buildJoinedSummary(baseSummary({ fresh: { value: false, proof: "not_reached" }, deployActions: 2,
    flags: { intake_triage_rollout: "not_read", core_customer_data: "not_read" } })).fresh, { value: false, proof: "not_reached" });
});

test("code flag: exactly one `export const NAME = true|false;` declaration, anything else refused", () => {
  const name = "INTAKE_TRIAGE_ROLLOUT_ENABLED";
  assert.equal(codeFlagState(`// switch\nexport const ${name} = false;\n`, name), "off");
  assert.equal(codeFlagState(`export const ${name} = true;\r\n`, name), "on");
  for (const text of ["", `export let ${name} = false;`, `export const ${name} = process.env.X === "1";`,
    `export const ${name} = false;\nexport const ${name} = false;`, `export const ${name} = false;\nconst ${name} = true;`, `export const ${name}  = false;`]) {
    assert.throws(() => codeFlagState(text, name), refusedWith("CODE_FLAG_NOT_EXACTLY_ONE_DECLARATION"), text);
  }
  assert.throws(() => codeFlagState(null, name), refusedWith("CODE_FLAG_INPUT"));
  assert.equal(booleanFlagState(true, "core_customer_data"), "on");
  for (const bad of [undefined, null, "true", 1]) assert.throws(() => booleanFlagState(bad, "core_customer_data"), refusedWith("FLAG_NOT_BOOLEAN"));
});

test("the real joined workflow: no secrets reference, top-level contents: read only, no write permission, no cache", () => {
  assert.equal(deployCapabilities(workflowText), 0);
  assert.doesNotMatch(workflowText, /\bsecrets\b/);
  assert.doesNotMatch(workflowText, /:\s*write\b|write-all/);
  assert.match(workflowText, /^permissions:\n {2}contents: read\n(?! )/m);
  assert.doesNotMatch(workflowText, /actions\/cache|^\s*cache:/m, "nothing is restored into the stack from a cache");
  assert.doesNotMatch(workflowText, /classify_pr91_affected_scope/, "the absent classifier is not called");
});

test("deployCapabilities counts each way a workflow could deploy or write", () => {
  const add = (text, line) => text.replace("\njobs:\n", `\njobs:\n${line}\n`);
  assert.equal(deployCapabilities(add(workflowText, "  # ${{ secrets.VERCEL_TOKEN }}")), 1);
  assert.equal(deployCapabilities(workflowText.replace("contents: read", "contents: write")), 2);
  assert.equal(deployCapabilities(workflowText.replace("permissions:\n  contents: read\n", "")), 1);
  assert.equal(deployCapabilities(workflowText.replace("permissions:\n  contents: read\n", "permissions:\n  contents: read\n  id-token: write\n")), 2);
  assert.equal(deployCapabilities(workflowText.replace("permissions:\n  contents: read\n", "permissions: write-all\n")), 2);
  assert.equal(deployCapabilities(add(workflowText, "    permissions: { deployments: write }")), 1);
  assert.equal(deployCapabilities(add(workflowText, "    secrets: inherit")), 1);
  assert.equal(deployCapabilities(workflowText.replace(/\n/g, "\r\n")), 0);
});

test("the harness wires the summary: reads the flags, proves freshness, writes the summary before the verdict, no Core journal", () => {
  for (const needle of ["writeJoinedSummary(summaryFile", "deployCapabilities(readFileSync(path.join(CORE, \".github/workflows/joined-e2e.yml\")",
    "codeFlagState(readFileSync(path.join(FOUNDATION, \"nextjs/lib/intake-triage-rollout.ts\")", "booleanFlagState(coreHealth.customerDataEnabled",
    "sql(\"select count(*) from auth.users\")"]) {
    assert.ok(harnessText.includes(needle), needle);
  }
  assert.ok(harnessText.indexOf("writeJoinedSummary(summaryFile") < harnessText.indexOf("const finalWritten = concludeRun(ledger, checkpoint);"));
  assert.ok(harnessText.indexOf("sql(\"select count(*) from auth.users\")") < harnessText.indexOf("await api(\"/auth/v1/admin/users\""));
  assert.doesNotMatch(harnessText, /TAVONEL_JOINED_CORE_JOURNAL|core-journal/);
});
