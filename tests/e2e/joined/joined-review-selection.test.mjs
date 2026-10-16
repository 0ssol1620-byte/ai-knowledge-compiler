import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { assertAcceptPostBindsEvidence, resolveReviewEvidence, uniquePhraseRegion } from "./review-evidence.mjs";

// Synthetic identities in the read model's shape (world-read-model.ts parseEvidence): id `${evidenceId}:${chunkId}`, blockId = chunkId.
const PHRASE = /73\s*days/i;
const collectionId = "collection-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const manifestDigest = `sha256:${"b".repeat(64)}`;
const documentId = "11111111-1111-4111-8111-111111111111";
const versionKey = "c".repeat(64);
const bbox = [72, 110, 640, 150];
const intended = { id: "ev_1:chunk_1", sourceId: documentId, sourceVersionId: versionKey, page: 1, bbox, blockId: "chunk_1",
  excerpt: "Archive retention is 73 days.", authority: "unclassified", digest: `sha256:${versionKey}` };
const neighbour = { ...intended, id: "ev_2:chunk_2", blockId: "chunk_2", bbox: [72, 160, 640, 200], excerpt: "Joined harness policy record." };
const model = (evidence, world = {}) => ({ world: { id: collectionId, manifestDigest, status: "candidate", revision: 1, ...world }, evidence });
const target = { collectionId, manifestDigest, documentId, versionKey, phrase: PHRASE, page: 1, bbox };

test("resolves the one intended record and returns its id verbatim", () => {
  const resolved = resolveReviewEvidence(model([neighbour, intended]), target);
  assert.equal(resolved, intended);
  assert.equal(resolved.id, "ev_1:chunk_1");
});

test("missing evidence fails closed", () => {
  assert.throws(() => resolveReviewEvidence(model([neighbour]), target), /found 0/);
  assert.throws(() => resolveReviewEvidence(model([]), target), /found 0/);
  assert.throws(() => resolveReviewEvidence({ world: model([]).world }, target), /found 0/);
});

test("ambiguous evidence fails closed instead of picking one", () => {
  assert.throws(() => resolveReviewEvidence(model([intended, { ...intended, id: "ev_3:chunk_3", blockId: "chunk_3" }]), target), /found 2/);
});

test("wrong source, version, page or region fails closed", () => {
  for (const wrong of [{ sourceId: "22222222-2222-4222-8222-222222222222" }, { sourceVersionId: "d".repeat(64) }, { page: 2 }, { bbox: [72, 110, 640, 151] }, { bbox: [72, 110, 640] }]) {
    assert.throws(() => resolveReviewEvidence(model([{ ...intended, ...wrong }]), target), /found 0/, JSON.stringify(wrong));
  }
});

test("a model for another manifest or collection fails closed", () => {
  assert.throws(() => resolveReviewEvidence(model([intended], { manifestDigest: `sha256:${"a".repeat(64)}` }), target), /exact candidate revision/);
  assert.throws(() => resolveReviewEvidence(model([intended], { id: "collection-other" }), target), /exact candidate revision/);
  assert.throws(() => resolveReviewEvidence(null, target), /exact candidate revision/);
});

test("an id that is not evidenceId:chunkId fails closed", () => {
  for (const id of ["chunk_1", ":chunk_1", "ev_1:chunk_9"]) {
    assert.throws(() => resolveReviewEvidence(model([{ ...intended, id }]), target), /evidenceId:chunkId/, id);
  }
});

test("the intended OCR region must be unique", () => {
  const region = { regionId: "r1", pageNumber1: 1, text: "Archive retention is 73 days.", bbox1000: bbox };
  assert.equal(uniquePhraseRegion([region, { ...region, regionId: "r2", text: "Joined harness policy record." }], PHRASE), region);
  assert.throws(() => uniquePhraseRegion([{ ...region, text: "nothing here" }], PHRASE), /exactly one OCR region/);
  assert.throws(() => uniquePhraseRegion([region, { ...region, regionId: "r2" }], PHRASE), /exactly one OCR region/);
  assert.throws(() => uniquePhraseRegion(undefined, PHRASE), /exactly one OCR region/);
});

test("the acceptance POST must name exactly the selected evidence, once", () => {
  const expected = { collectionId, manifestDigest, evidenceId: intended.id };
  const body = { ...expected, action: "accept", reason: "Accepted after reviewing the source." };
  assert.deepEqual(assertAcceptPostBindsEvidence([body], expected), { ...expected, action: "accept" });
  assert.throws(() => assertAcceptPostBindsEvidence([{ ...body, evidenceId: neighbour.id }], expected), /binds the selected evidence/);
  assert.throws(() => assertAcceptPostBindsEvidence([{ ...body, evidenceId: "ev_1" }], expected), /binds the selected evidence/);
  assert.throws(() => assertAcceptPostBindsEvidence([{ ...body, manifestDigest: `sha256:${"a".repeat(64)}` }], expected), /binds the selected evidence/);
  assert.throws(() => assertAcceptPostBindsEvidence([{ ...body, action: "reject" }], expected), /binds the selected evidence/);
  assert.throws(() => assertAcceptPostBindsEvidence([], expected), /exactly one review POST/);
  assert.throws(() => assertAcceptPostBindsEvidence([body, body], expected), /exactly one review POST/);
});

// The harness step itself, read as text the way joined-intake-approval.test.mjs reads it: it cannot run off the runner.
const harness = readFileSync(new URL("./joined-e2e.mjs", import.meta.url), "utf8");
const review = harness.slice(harness.indexOf('hop("review-activate")'), harness.indexOf('hop("consumers")'));
const at = text => { const index = review.indexOf(text); assert.ok(index >= 0, `review step contains ${text}`); return index; };

test("the review step observes the World read, selects the evidence, then accepts", () => {
  assert.ok(review.length > 0);
  const order = [
    "const worldReply = page.waitForResponse(",
    "await page.goto(`${origin}/workspace/review?collection=${compiled.collectionId}&manifest=${encodeURIComponent(compiled.manifestDigest)}`);",
    'check("the review page reads exactly the candidate World revision"',
    "resolveReviewEvidence((await worldResponse.json())?.model",
    "await expect(evidenceCard).toHaveCount(1);",
    'await expect(evidenceCard).toHaveAttribute("aria-pressed", "false");',
    "await expect(acceptButton).toBeDisabled();",
    'page.on("request", recordReviewPost);',
    "await evidenceCard.click();",
    'await expect(evidenceCard).toHaveAttribute("aria-pressed", "true");',
    'await expect(inspector.locator(":scope > strong")).toHaveText(reviewEvidence.sourceId);',
    'await expect(inspector.locator("dd")).toHaveText([reviewEvidence.sourceVersionId, String(reviewEvidence.page), `[${reviewEvidence.bbox.join(", ")}]`]);',
    "await expect(acceptButton).toBeEnabled();",
    "accepted = await acceptEvidenceThroughUi(page, compiled.collectionId, compiled.manifestDigest);",
    'check("UI records the evidence acceptance", accepted.status(), 201);',
    "assertAcceptPostBindsEvidence(reviewPosts, { collectionId: compiled.collectionId, manifestDigest: compiled.manifestDigest, evidenceId: reviewEvidence.id })",
    "expectedCurrentManifest: null, expectedCurrentRevision: 0 }",
    "`${compiled.manifestDigest}@1`);",
    "ledger.booleans.reviewActivateViaUi = true;",
  ];
  order.reduce((previous, text) => { const index = at(text); assert.ok(index > previous, `in order: ${text}`); return index; }, -1);
  assert.ok(review.includes(`page.locator('section[aria-labelledby="review-comparison-title"]')`), "the card is the production evidence card in the review comparison");
  assert.ok(review.includes("documentId: docA.documentId, versionKey: docA.versionKey, phrase: PHRASE"), "the evidence is named by the uploaded document version and phrase");
  assert.ok(review.includes("page: phraseRegion.pageNumber1, bbox: phraseRegion.bbox1000"), "the evidence is named by the OCR region that read the phrase");
});

test("the review step forces, scripts or substitutes nothing", () => {
  for (const banned of [".first()", ".nth(", "force: true", "waitForTimeout", "evaluate(", "removeAttribute", 'app("/api/v1/reviews"', "fetch(", "dispatchEvent"]) {
    assert.ok(!review.includes(banned), `review step does not use ${banned}`);
  }
  assert.equal(review.split("acceptEvidenceThroughUi(").length - 1, 1, "accepts once, through the shared helper");
});
