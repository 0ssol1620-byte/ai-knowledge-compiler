/**
 * Joined phase `modify` (D20 WO-D20-2): a new source revision arrives after revision 1 is the active World.
 *
 *  1. until revision 2's candidate is promoted, ask answers from revision 1's manifest;
 *  2. a candidate compiled from revision 1 after revision 2 arrived is refused at promote (a catalogued 409) and the
 *     active pointer does not move;
 *  3. revision 2's candidate promotes; the changed value is answered from revision 2 with evidence bound to revision 2,
 *     the unchanged region's evidence keeps its page and box, and revision 1's World stays in the version history;
 *  4. the revision-compile flag state and the path that compiled revision 2 are recorded.
 *
 * What the harness puts in `state` (this phase never reaches into the harness otherwise; a missing or mistyped entry is
 * a thrown TypeError, never a default): token, workspaceKey, collectionId, activeManifestDigest, activeRevision (positive
 * integer), revisionCompileEnabled (boolean read from the stack), rev1VersionKey, changedQuestion, rev1Value and rev2Value
 * (RegExp), unchangedQuestion, unchangedPattern (RegExp), unchangedRegion {pageNumber1, bbox1000}, and two async
 * functions: uploadRevision2() -> {versionKey} and compileCandidate({revision: 1|2}) -> {manifestDigest, path} with
 * path "revision_compile" | "full_compile". A semantic miss is outcome `not_met` with the stage it failed at; an
 * operational error (a rejected request, a timeout) is rethrown, never turned into a verdict.
 */
import { AssertionError } from "node:assert";
import { randomUUID } from "node:crypto";
import { COUNT, booleanFlagState, definePhase } from "./phase-contract.mjs";

/** The 409 codes a stale candidate may be refused with: the catalogue's source, receipt-subject, scope and revision-binding codes. */
export const STALE_PROMOTE_CODES = Object.freeze({
  SOURCE_VERSION_CHANGED: "source_version_changed",
  COMPILE_RECEIPT_SUBJECT_MISMATCH: "compile_receipt_subject_mismatch",
  WORLD_CANDIDATE_SCOPE_CHANGED: "world_candidate_scope_changed",
  WORLD_VERSION_BINDING_CONFLICT: "world_version_binding_conflict",
});
const STAGES = ["none", "rev1_served_before_promote", "stale_promote_refused", "stale_pointer_unchanged", "rev2_promoted",
  "rev2_value_answered", "rev2_evidence_bound", "unchanged_region_bound", "history_kept"];
const COMPILE_PATHS = ["revision_compile", "full_compile"];
const KEY = /^[A-Za-z0-9_-]{1,128}$/;
const DIGEST = /^sha256:[0-9a-f]{64}$/;
const STEP_MS = 180_000;

const need = (state, key, ok) => { if (!ok(state[key])) throw new TypeError(`phase modify: state.${key} missing or mistyped`); return state[key]; };
const candidate = (value, which) => {
  if (!(typeof value?.manifestDigest === "string" && DIGEST.test(value.manifestDigest) && COMPILE_PATHS.includes(value.path))) {
    throw new TypeError(`phase modify: compileCandidate(${which}) returned no digest or path`);
  }
  return value;
};

export const phaseModify = definePhase({
  name: "modify",
  fields: {
    failed_at: STAGES, revision_compile_flag: ["on", "off"], rev2_compile_path: COMPILE_PATHS,
    stale_refusal_code: Object.values(STALE_PROMOTE_CODES), active_revision_after: COUNT, history_versions: COUNT,
  },
  async run({ app, sql, check, hop, step, state }) {
    const token = need(state, "token", v => typeof v === "string" && v.length > 0);
    const workspace = need(state, "workspaceKey", v => typeof v === "string" && KEY.test(v));
    const collectionId = need(state, "collectionId", v => typeof v === "string" && KEY.test(v));
    const active = need(state, "activeManifestDigest", v => typeof v === "string" && DIGEST.test(v));
    const revision = need(state, "activeRevision", v => Number.isSafeInteger(v) && v > 0);
    const rev1VersionKey = need(state, "rev1VersionKey", v => typeof v === "string" && v.length > 0);
    const [changedQuestion, unchangedQuestion] = ["changedQuestion", "unchangedQuestion"].map(key => need(state, key, v => typeof v === "string" && v.length > 0));
    const [rev1Value, rev2Value, unchangedPattern] = ["rev1Value", "rev2Value", "unchangedPattern"].map(key => need(state, key, v => v instanceof RegExp));
    const region = need(state, "unchangedRegion", v => v && Number.isSafeInteger(v.pageNumber1) && Array.isArray(v.bbox1000) && v.bbox1000.length === 4);
    const upload = need(state, "uploadRevision2", v => typeof v === "function");
    const compile = need(state, "compileCandidate", v => typeof v === "function");
    const flag = booleanFlagState(need(state, "revisionCompileEnabled", v => typeof v === "boolean"), "revision_compile");
    const result = { revision_compile_flag: flag };

    const pointer = () => sql(`select manifest_digest||'@'||revision from public.foundation_active_worlds where workspace_key='${workspace}' and collection_id='${collectionId}'`);
    const ask = async question => (await app(`/api/v1/collections/${collectionId}/ask`, token, { question })).body;
    const says = (body, pattern) => typeof body?.answer === "string" && pattern.test(body.answer);
    const promote = manifestDigest => app(`/api/collections/${collectionId}/promote`, token, {
      operationId: randomUUID(), manifestDigest, expectedCurrentManifest: active, expectedCurrentRevision: revision,
      reason: "Joined E2E modify phase: promote a reviewed revision.",
    });
    const bound = (c, versionKey) => [c?.sourceId, c?.sourceVersionId].some(v => String(v).includes(versionKey));
    let stage = "none";
    const verdict = (name, actual, expected) => { stage = name; check(`modify/${name}`, actual, expected); };
    try {
      hop("modify");
      const rev2 = await step("upload-rev2", STEP_MS, upload);
      if (!(typeof rev2?.versionKey === "string" && rev2.versionKey.length > 0)) throw new TypeError("phase modify: uploadRevision2 returned no versionKey");

      const before = await ask(changedQuestion);
      verdict("rev1_served_before_promote", [before?.code, before?.activeWorld?.manifestDigest, says(before, rev2Value), pointer()],
        ["GROUNDED_ANSWER", active, false, `${active}@${revision}`]);

      const stale = candidate(await step("compile-stale", STEP_MS, () => compile({ revision: 1 })), 1);
      const refused = await promote(stale.manifestDigest);
      verdict("stale_promote_refused", [refused.status, Object.hasOwn(STALE_PROMOTE_CODES, refused.body?.code)], [409, true]);
      result.stale_refusal_code = STALE_PROMOTE_CODES[refused.body.code];
      verdict("stale_pointer_unchanged", pointer(), `${active}@${revision}`);

      const fresh = candidate(await step("compile-rev2", STEP_MS, () => compile({ revision: 2 })), 2);
      result.rev2_compile_path = fresh.path;
      const promoted = await promote(fresh.manifestDigest);
      verdict("rev2_promoted", [promoted.status, promoted.body?.code, pointer()], [200, "WORLD_ACTIVE", `${fresh.manifestDigest}@${revision + 1}`]);
      result.active_revision_after = revision + 1;

      const after = await ask(changedQuestion);
      verdict("rev2_value_answered", [after?.code, after?.activeWorld?.manifestDigest, says(after, rev2Value), says(after, rev1Value)],
        ["GROUNDED_ANSWER", fresh.manifestDigest, true, false]);
      const cited = (after.citations ?? []).filter(c => rev2Value.test(c?.excerpt ?? ""));
      verdict("rev2_evidence_bound", [cited.length > 0, cited.every(c => bound(c, rev2.versionKey)), cited.some(c => bound(c, rev1VersionKey))], [true, true, false]);

      const unchanged = await ask(unchangedQuestion);
      const kept = (unchanged?.citations ?? []).filter(c => unchangedPattern.test(c?.excerpt ?? ""));
      verdict("unchanged_region_bound", [unchanged?.activeWorld?.manifestDigest, kept.length > 0,
        kept.every(c => c.pageNumber1 === region.pageNumber1 && JSON.stringify(c.bbox1000) === JSON.stringify(region.bbox1000))],
        [fresh.manifestDigest, true, true]);

      const world = await app(`/api/collections/${collectionId}/world`, token);
      const versions = Array.isArray(world.body?.versions) ? world.body.versions : [];
      const lifecycle = digest => versions.find(v => v?.manifest_digest === digest)?.lifecycle_status;
      verdict("history_kept", [world.status, lifecycle(active), lifecycle(fresh.manifestDigest)], [200, "superseded", "active"]);
      result.history_versions = versions.length;
      stage = "none";
    } catch (error) {
      if (!(error instanceof AssertionError)) throw error;
    }
    return { ...result, failed_at: stage, outcome: stage === "none" ? "met" : "not_met" };
  },
});
