/**
 * The one interface every later joined phase implements (D20: partial, modify, revoke, export, rebuild), and the bounded
 * joined-summary.json the harness writes beside its ledger.
 *
 * A phase is `definePhase({ name, fields, run })`. `run` receives exactly { app, sql, check, hop, step, state, deadline }
 * and returns `{ outcome, ...fields }`. Every value is the outcome enum, a member of an enum the phase declared, or a
 * non-negative safe integer it declared as a count: no free text, no ids, no document text. Anything else is refused with
 * PhaseContractError, and a refused summary never reaches joined-summary.json: the summary only accepts phase results
 * that came out of `runPhase`.
 *
 * Errors name keys only when the key is a plain token; values are never echoed.
 */
import { renameSync, writeFileSync } from "node:fs";

export const PHASE_NAMES = Object.freeze(["partial", "modify", "revoke", "export", "rebuild"]);
export const PHASE_OUTCOMES = Object.freeze(["met", "not_met", "failed", "not_run", "off_not_exercised"]);
export const PHASE_INPUT_KEYS = Object.freeze(["app", "sql", "check", "hop", "step", "state", "deadline"]);
/** A declared field is either "count" or an array of enum tokens. */
export const COUNT = "count";
export const MAX_COUNT = 1_000_000_000;
const MAX_FIELDS = 24;
const MAX_ENUM_VALUES = 16;
const TOKEN = /^[a-z][a-z0-9_]{0,47}$/;

export const SUMMARY_SCHEMA = "tavonel.joined_summary.v1";
export const SUMMARY_KEYS = Object.freeze(["schema", "trigger", "core_sha", "foundation_sha", "flags", "fresh", "deploy_actions", "phases"]);
export const SUMMARY_TRIGGERS = Object.freeze(["workflow_dispatch", "pull_request"]);
/** Every flag the harness reads. `not_read` = the run ended before the harness read it. */
export const FLAG_NAMES = Object.freeze(["intake_triage_rollout", "core_customer_data"]);
export const FLAG_STATES = Object.freeze(["on", "off", "not_read"]);
/** The step that proves (or disproves) a fresh stack; `not_reached` = the run ended before that step. */
export const FRESH_PROOFS = Object.freeze(["auth_users_empty_before_fixtures", "auth_users_present_before_fixtures", "not_reached"]);

export class PhaseContractError extends Error {
  constructor(code, where) {
    super(`${code}: ${where}`);
    this.name = "PhaseContractError";
    this.code = code;
  }
}

const refuse = (code, where) => { throw new PhaseContractError(code, where); };
const named = key => (typeof key === "string" && TOKEN.test(key) ? key : "<non-token key>");
const isPlainObject = value => value !== null && typeof value === "object" && !Array.isArray(value)
  && [Object.prototype, null].includes(Object.getPrototypeOf(value));
const isCount = value => Number.isSafeInteger(value) && value >= 0 && value <= MAX_COUNT;

/** Phases made by definePhase, and phase results (-> their phase name) that went through validatePhaseSummary: the only
 * values runPhase and buildJoinedSummary accept. */
const defined = new WeakSet();
const validated = new WeakMap();

export function definePhase({ name, fields, run, ...rest }) {
  if (Object.keys(rest).length) refuse("PHASE_DEFINITION_UNKNOWN_KEY", named(Object.keys(rest)[0]));
  if (!PHASE_NAMES.includes(name)) refuse("PHASE_NAME_UNKNOWN", named(name));
  if (typeof run !== "function") refuse("PHASE_RUN_NOT_A_FUNCTION", name);
  if (!isPlainObject(fields)) refuse("PHASE_FIELDS_NOT_AN_OBJECT", name);
  const entries = Object.entries(fields);
  if (entries.length > MAX_FIELDS) refuse("PHASE_TOO_MANY_FIELDS", name);
  const declared = {};
  for (const [field, spec] of entries) {
    if (!TOKEN.test(field) || field === "outcome") refuse("PHASE_FIELD_NAME_INVALID", `${name}.${named(field)}`);
    if (spec === COUNT) { declared[field] = COUNT; continue; }
    if (!Array.isArray(spec) || spec.length === 0 || spec.length > MAX_ENUM_VALUES
      || !spec.every(value => typeof value === "string" && TOKEN.test(value)) || new Set(spec).size !== spec.length) {
      refuse("PHASE_FIELD_SPEC_INVALID", `${name}.${field}`);
    }
    declared[field] = Object.freeze([...spec]);
  }
  const phase = Object.freeze({ name, fields: Object.freeze(declared), run });
  defined.add(phase);
  return phase;
}

/** The phase's result, checked against its declaration; returns a frozen copy in declaration order. */
export function validatePhaseSummary(phase, result) {
  if (!defined.has(phase)) refuse("PHASE_NOT_DEFINED", "validatePhaseSummary");
  if (!isPlainObject(result)) refuse("PHASE_RESULT_NOT_AN_OBJECT", phase.name);
  for (const key of Object.keys(result)) {
    if (key !== "outcome" && !Object.hasOwn(phase.fields, key)) refuse("PHASE_FIELD_NOT_ALLOWED", `${phase.name}.${named(key)}`);
  }
  const outcome = result.outcome;
  if (!PHASE_OUTCOMES.includes(outcome)) refuse("PHASE_OUTCOME_INVALID", phase.name);
  const summary = { outcome };
  for (const [field, spec] of Object.entries(phase.fields)) {
    if (!Object.hasOwn(result, field)) continue;  // not reported; never filled in
    const value = result[field];
    const ok = spec === COUNT ? isCount(value) : spec.includes(value);
    if (!ok) refuse(spec === COUNT ? "PHASE_COUNT_INVALID" : "PHASE_ENUM_INVALID", `${phase.name}.${field}`);
    summary[field] = value;
  }
  const frozen = Object.freeze(summary);
  validated.set(frozen, phase.name);
  return frozen;
}

/** Runs one phase with exactly the contract's input and returns its validated, bounded summary. */
export async function runPhase(phase, input) {
  if (!defined.has(phase)) refuse("PHASE_NOT_DEFINED", "runPhase");
  if (!isPlainObject(input)) refuse("PHASE_INPUT_NOT_AN_OBJECT", phase.name);
  const keys = Object.keys(input).sort();
  if (keys.join(",") !== [...PHASE_INPUT_KEYS].sort().join(",")) refuse("PHASE_INPUT_KEYS", phase.name);
  if (!isPlainObject(input.state)) refuse("PHASE_STATE_NOT_AN_OBJECT", phase.name);
  for (const key of ["app", "sql", "check", "hop", "step"]) if (typeof input[key] !== "function") refuse("PHASE_INPUT_NOT_A_FUNCTION", `${phase.name}.${key}`);
  if (!(Number.isFinite(input.deadline) && input.deadline > 0)) refuse("PHASE_DEADLINE_INVALID", phase.name);
  return validatePhaseSummary(phase, await phase.run(input));
}

/**
 * "on"/"off" of a code-owned boolean switch: exactly one `export const NAME = true|false;` line and no other declaration
 * of NAME. Anything else is refused, never read as a default.
 */
export function codeFlagState(sourceText, name) {
  if (typeof sourceText !== "string" || !/^[A-Z][A-Z0-9_]*$/.test(name)) refuse("CODE_FLAG_INPUT", "codeFlagState");
  const lines = sourceText.split(/\r?\n/);
  const values = lines.map(line => line.match(new RegExp(`^export const ${name} = (true|false);$`))?.[1]).filter(Boolean);
  const declarations = lines.filter(line => new RegExp(`(^|[^A-Za-z0-9_$])(const|let|var)\\s+${name}([^A-Za-z0-9_$]|$)`).test(line));
  if (values.length !== 1 || declarations.length !== 1) refuse("CODE_FLAG_NOT_EXACTLY_ONE_DECLARATION", name);
  return values[0] === "true" ? "on" : "off";
}

/** "on"/"off" of a boolean the harness read from a service; a non-boolean is refused. */
export function booleanFlagState(value, name) {
  if (typeof value !== "boolean") refuse("FLAG_NOT_BOOLEAN", named(name));
  return value ? "on" : "off";
}

/**
 * How many ways the workflow file could let a run deploy or write: each `secrets.`/`secrets[`/`secrets:` reference, each
 * permission set to `write` or `write-all`, and a missing top-level `permissions:` block that is exactly `contents: read`
 * (the default token may then write). D20 requires 0.
 */
export function deployCapabilities(workflowText) {
  if (typeof workflowText !== "string") refuse("WORKFLOW_TEXT_INVALID", "deployCapabilities");
  const text = workflowText.replace(/\r\n/g, "\n");
  const secrets = text.match(/\bsecrets\s*[.[:]/g)?.length ?? 0;
  const writes = (text.match(/^\s*[A-Za-z-]+\s*:\s*write\s*(#.*)?$/gm)?.length ?? 0)
    + (text.match(/[{,]\s*[A-Za-z-]+\s*:\s*write\b/g)?.length ?? 0);
  const writeAll = text.match(/\bwrite-all\b/g)?.length ?? 0;
  const readOnlyTop = /^permissions:[ \t]*\n[ \t]+contents:[ \t]*read[ \t]*\n(?![ \t])/m.test(text) ? 0 : 1;
  return secrets + writes + writeAll + readOnlyTop;
}

/** The bounded summary: fixed keys, fixed enums, 40-hex SHAs, integers; phases only from runPhase. */
export function buildJoinedSummary({ trigger, coreSha, foundationSha, flags, fresh, deployActions, phases, ...rest }) {
  if (Object.keys(rest).length) refuse("SUMMARY_KEY_NOT_ALLOWED", named(Object.keys(rest)[0]));
  if (!SUMMARY_TRIGGERS.includes(trigger)) refuse("SUMMARY_TRIGGER_INVALID", "trigger");
  for (const [key, sha] of [["core_sha", coreSha], ["foundation_sha", foundationSha]]) {
    if (typeof sha !== "string" || !/^[0-9a-f]{40}$/.test(sha)) refuse("SUMMARY_SHA_INVALID", key);
  }
  if (!isPlainObject(flags) || Object.keys(flags).sort().join(",") !== [...FLAG_NAMES].sort().join(",")) refuse("SUMMARY_FLAGS_KEYS", "flags");
  for (const name of FLAG_NAMES) if (!FLAG_STATES.includes(flags[name])) refuse("SUMMARY_FLAG_STATE_INVALID", name);
  if (!isPlainObject(fresh) || Object.keys(fresh).sort().join(",") !== "proof,value" || typeof fresh.value !== "boolean"
    || !FRESH_PROOFS.includes(fresh.proof) || fresh.value !== (fresh.proof === "auth_users_empty_before_fixtures")) {
    refuse("SUMMARY_FRESH_INVALID", "fresh");
  }
  if (!isCount(deployActions)) refuse("SUMMARY_DEPLOY_ACTIONS_INVALID", "deploy_actions");
  if (!isPlainObject(phases)) refuse("SUMMARY_PHASES_NOT_AN_OBJECT", "phases");
  for (const [name, summary] of Object.entries(phases)) {
    if (!PHASE_NAMES.includes(name)) refuse("SUMMARY_PHASE_UNKNOWN", named(name));
    if (validated.get(summary) !== name) refuse("SUMMARY_PHASE_NOT_VALIDATED", name);
  }
  const summary = {
    schema: SUMMARY_SCHEMA, trigger, core_sha: coreSha, foundation_sha: foundationSha,
    flags: Object.fromEntries(FLAG_NAMES.map(name => [name, flags[name]])), fresh: { value: fresh.value, proof: fresh.proof },
    deploy_actions: deployActions, phases: Object.fromEntries(PHASE_NAMES.filter(name => Object.hasOwn(phases, name)).map(name => [name, phases[name]])),
  };
  if (Object.keys(summary).join(",") !== SUMMARY_KEYS.join(",")) refuse("SUMMARY_SHAPE", "buildJoinedSummary");
  return summary;
}

/** Builds the summary from `input` (refusing as buildJoinedSummary does) and writes it with one rename, so a reader never
 * sees half of it. Returns what was written. */
export function writeJoinedSummary(file, input) {
  const summary = buildJoinedSummary(input);
  const temporary = `${file}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(summary, null, 2)}\n`);
  renameSync(temporary, file);
  return summary;
}
