/**
 * The joined review step's evidence choice. Review never picks evidence for the reviewer, so the harness names the one
 * record it means from the World read model the review page itself fetched, and refuses anything but exactly one.
 * Dependency-free apart from node:assert, so joined-review-selection.test.mjs drives every refusal without a browser.
 */
import assert from "node:assert/strict";

const sameBox = (a, b) => Array.isArray(a) && Array.isArray(b) && a.length === 4 && b.length === 4 && a.every((value, index) => value === b[index]);

/** The single OCR region whose text carries `phrase`. None, or more than one, is not a region the review can name. */
export function uniquePhraseRegion(regions, phrase) {
  const matches = (Array.isArray(regions) ? regions : []).filter(region => phrase.test(String(region?.text ?? "")));
  assert.equal(matches.length, 1, `exactly one OCR region reads ${phrase}`);
  return matches[0];
}

/**
 * The one evidence record of exactly this World revision that cites `documentId` at `versionKey`, reads `phrase`, and
 * sits on `page` at exactly `bbox`. Its id is returned verbatim and must be the read model's `evidenceId:chunkId`.
 */
export function resolveReviewEvidence(model, { collectionId, manifestDigest, documentId, versionKey, phrase, page, bbox }) {
  assert.deepEqual([model?.world?.id, model?.world?.manifestDigest], [collectionId, manifestDigest], "the World read model is this exact candidate revision");
  const evidence = Array.isArray(model.evidence) ? model.evidence : [];
  const matches = evidence.filter(item => item?.sourceId === documentId && item.sourceVersionId === versionKey
    && phrase.test(String(item.excerpt ?? "")) && item.page === page && sameBox(item.bbox, bbox));
  if (matches.length !== 1) {
    // Identities only, never excerpts: enough to say which binding was wrong.
    const reading = evidence.filter(item => phrase.test(String(item?.excerpt ?? "")))
      .map(({ id, sourceId, sourceVersionId, page: itemPage, bbox: itemBox }) => ({ id, sourceId, sourceVersionId, page: itemPage, bbox: itemBox }));
    assert.fail(`expected exactly one evidence record for ${documentId}@${versionKey} page ${page} region [${bbox}], found ${matches.length}; records reading the phrase: ${JSON.stringify(reading)}`);
  }
  const [match] = matches;
  assert.ok(typeof match.id === "string" && typeof match.blockId === "string" && match.blockId.length > 0
    && match.id.length > match.blockId.length + 1 && match.id.endsWith(`:${match.blockId}`), `evidence ${JSON.stringify(match.id)} is evidenceId:chunkId`);
  return match;
}

/** Exactly one review POST, naming exactly this evidence record of this revision as an acceptance. */
export function assertAcceptPostBindsEvidence(bodies, { collectionId, manifestDigest, evidenceId }) {
  assert.equal(bodies.length, 1, "exactly one review POST was sent");
  const [body] = bodies;
  const bound = { collectionId: body?.collectionId, manifestDigest: body?.manifestDigest, evidenceId: body?.evidenceId, action: body?.action };
  assert.deepEqual(bound, { collectionId, manifestDigest, evidenceId, action: "accept" }, "the review POST binds the selected evidence");
  return bound;
}
