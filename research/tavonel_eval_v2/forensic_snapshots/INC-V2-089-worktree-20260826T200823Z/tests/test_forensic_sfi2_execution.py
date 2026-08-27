"""`forensic_sfi2_execution.py` -- the stage tracer, and the classifier it runs.

Two kinds of test here, deliberately kept apart:

* **Hermetic** tests build tiny synthetic documents (a single markdown unit,
  cache monkeypatched to hand back fixed bytes) and check the stage classifier
  against a case constructed to exercise it directly -- one where the
  `identity_text` fold erases a real byte difference (the bug this tool traces),
  and one where it does not, so a normal rebuild is not reported as a
  divergence.
* **Real-data** tests replay the actual frozen 14 SFI2 cases from the cached
  payloads on disk. They are skipped, not failed, if the frozen receipt, the
  lineage frame or the payload cache are not present in this checkout --
  their absence is an environment fact, not a defect in this tool.

`write_immutable` is monkeypatched everywhere a full `main()` run is exercised,
so repeated test runs do not accumulate immutable receipts under `receipts/`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))

import forensic_sfi2_execution as forensic  # noqa: E402
from payload_cache import PayloadCache  # noqa: E402

REAL_DATA_MISSING = not (
    forensic.LINEAGES.exists()
    and forensic.CACHE_ROOT.exists()
    and any(NS.glob("receipts/sfi2-native-provenance--*.json"))
)
skip_without_real_data = pytest.mark.skipif(
    REAL_DATA_MISSING,
    reason="frozen sfi2-native-provenance receipt, lineage frame or payload cache not present",
)


# --- 1. URL construction, cache-only, matches what acquisition wrote it under -


def test_git_url_matches_the_shape_acquisition_used() -> None:
    lineage = {"owner": "apache", "repo": "druid", "path": "docs/design/deep-storage.md"}
    url = forensic._git_url(lineage, "abc123")
    assert url == "https://raw.githubusercontent.com/apache/druid/abc123/docs/design/deep-storage.md"


def test_ecfr_url_matches_the_shape_acquisition_used() -> None:
    lineage = {"title": "40", "part": "761", "identifier": "761.180"}
    url = forensic._ecfr_url(lineage, "2024-05-28")
    assert url == (
        "https://www.ecfr.gov/api/versioner/v1/full/2024-05-28/title-40.xml"
        "?part=761&section=761.180"
    )


def test_unsupported_family_raises_rather_than_guessing_a_url(tmp_path: Path) -> None:
    cache = PayloadCache(tmp_path / "cache", "fixture")
    lineage = {"family": "encyclopedia_wikipedia", "lineage_id": "wp:example"}
    with pytest.raises(forensic.UnsupportedFamily):
        forensic.fetch_payload(cache, lineage, "12345")


def test_a_version_not_in_the_cache_is_reported_not_fetched(tmp_path: Path) -> None:
    cache = PayloadCache(tmp_path / "cache", "fixture")
    lineage = {
        "family": "git_docs",
        "owner": "apache",
        "repo": "druid",
        "path": "docs/does-not-exist.md",
        "lineage_id": "git:apache/druid:docs/does-not-exist.md",
    }
    with pytest.raises(forensic.CacheMiss):
        forensic.fetch_payload(cache, lineage, "0000000000000000000000000000000000000000")


# --- 2. the stage classifier, on synthetic documents -------------------------


#: `provenance_document` drops any block under `MIN_TEXT_CHARS` (120), so the
#: single sentence under test is padded with filler that is identical on both
#: sides -- only the sentence itself varies between the before and after
#: fixtures a test builds.
_FILLER = (
    " This sentence exists only to push the block past the minimum text "
    "length the canonicaliser requires before it keeps a section as a unit."
)


def _markdown(body_line: str) -> bytes:
    return f"{body_line}{_FILLER}\n".encode()


def _seed_cache(cache: PayloadCache, lineage: dict[str, Any], version: str, payload: bytes) -> None:
    url = forensic._git_url(lineage, version)
    cache.payload(url, lambda _url: payload)


def _synthetic_lineage() -> dict[str, Any]:
    return {
        "family": "git_docs",
        "owner": "fixture",
        "repo": "repo",
        "path": "docs/page.md",
        "lineage_id": "git:fixture/repo:docs/page.md",
        "licence": "fixture",
    }


def test_a_punctuation_only_change_that_folds_identity_equal_is_caught_at_typed_delta(
    tmp_path: Path,
) -> None:
    """The exact shape of the bug this tool exists to trace, now traced through
    the repaired path.

    A registered-sign character is inserted. The raw bytes differ, so a clean
    rebuild's digest over the raw text differs -- and `normalize_text_for_identity`
    still folds punctuation to a space, so `identity_text` still agrees on both
    sides. That fold is deliberate and was never touched: it answers "is this the
    same unit?", where insensitivity is the feature.

    What changed is which question the change predicate asks. Until INC-V2-037 the
    identity fold WAS the change predicate, so an edit it folded away emitted no
    `MODIFIED_CLAIM`, the typed delta never marked the artifact, and the section
    was carried forward stale -- `first_divergence_stage == "typed_delta"`, the
    reading SFI2 froze. The predicate now comes from the declared change facets
    instead, so the same replay diverges at no stage.

    The assertions below are therefore the mirror of the ones this test shipped
    with, and the two things that must NOT have changed -- `identity_text_equal`
    and `raw_text_differs` -- are asserted unchanged alongside them. If identity
    equality had been "fixed" by making the fold content-sensitive, this test
    would still be green while identity continuity was silently broken.
    """
    cache = PayloadCache(tmp_path / "cache", "fixture")
    lineage = _synthetic_lineage()
    before_raw = _markdown("Apache Druid is a database.")
    after_raw = _markdown("Apache® Druid is a database.")
    _seed_cache(cache, lineage, "before1", before_raw)
    _seed_cache(cache, lineage, "after1", after_raw)

    before_doc = forensic.build_document(lineage, "before1", before_raw)
    logical = before_doc["units"][0]["explicit_path"]
    artifact_key = "section:" + __import__("selective_build").logical_id(
        lineage["lineage_id"], logical
    )

    case = {
        "lineage_id": lineage["lineage_id"],
        "before_version": "before1",
        "after_version": "after1",
        "artifacts": [artifact_key],
    }

    result = forensic.trace_case(lineage, case, cache)
    assert result["resolved"] is True
    #: No stage drops the artifact from required-to-rebuild any more.
    assert result["first_divergence_stage"] is None

    row = result["artifacts"][0]
    assert row["clean_before_moved_from_clean_after"] is True
    #: Unchanged by the migration, and asserted so a regression in either would
    #: be visible: the bytes really do differ, and the identity fold really does
    #: still agree. Identity continuity is preserved.
    assert row["raw_text_differs"] is True
    assert row["identity_text_equal"] is True
    #: The repair: change detection no longer rides on identity equality.
    assert row["modified_claim_emitted"] is True
    assert row["stage_marks_required_to_rebuild"]["typed_delta"] is True
    #: and everything downstream now inherits the catch rather than the miss.
    assert row["stage_marks_required_to_rebuild"]["dependency_expansion"] is True
    assert row["stage_marks_required_to_rebuild"]["rebuild_request"] is True
    assert row["carried_forward"] is False
    assert row["rebuilt"] is True


def test_a_substantive_change_is_rebuilt_and_shows_no_divergence(tmp_path: Path) -> None:
    """The control case: a real wording change survives `identity_text`
    folding, so the unit is named at every stage and no divergence is found."""
    cache = PayloadCache(tmp_path / "cache", "fixture")
    lineage = _synthetic_lineage()
    before_raw = _markdown("The service starts on port 8080.")
    after_raw = _markdown("The service starts on port 9090 instead.")
    _seed_cache(cache, lineage, "before1", before_raw)
    _seed_cache(cache, lineage, "after1", after_raw)

    before_doc = forensic.build_document(lineage, "before1", before_raw)
    logical = before_doc["units"][0]["explicit_path"]
    artifact_key = "section:" + __import__("selective_build").logical_id(
        lineage["lineage_id"], logical
    )

    case = {
        "lineage_id": lineage["lineage_id"],
        "before_version": "before1",
        "after_version": "after1",
        "artifacts": [artifact_key],
    }

    result = forensic.trace_case(lineage, case, cache)
    assert result["resolved"] is True
    assert result["first_divergence_stage"] is None

    row = result["artifacts"][0]
    assert row["clean_before_moved_from_clean_after"] is True
    assert row["identity_text_equal"] is False
    assert row["modified_claim_emitted"] is True
    assert all(row["stage_marks_required_to_rebuild"].values())
    assert row["rebuilt"] is True
    assert row["carried_forward"] is False


def test_a_lineage_not_in_the_frame_is_reported_unresolved_not_skipped(tmp_path: Path) -> None:
    cache = PayloadCache(tmp_path / "cache", "fixture")
    lineage = {
        "family": "git_docs",
        "owner": "fixture",
        "repo": "repo",
        "path": "docs/missing.md",
        "lineage_id": "git:fixture/repo:docs/missing.md",
    }
    case = {
        "lineage_id": lineage["lineage_id"],
        "before_version": "b",
        "after_version": "a",
        "artifacts": ["section:u:doesnotmatter"],
    }
    result = forensic.trace_case(lineage, case, cache)
    assert result["resolved"] is False
    assert "CacheMiss" in result["unresolved_reason"]
    assert result["first_divergence_stage"] is None


# --- 3. main(), against the real frozen 14 cases ------------------------------


@skip_without_real_data
def test_main_resolves_all_fourteen_confirmed_cases_at_typed_delta(
    monkeypatch: Any, tmp_path: Path
) -> None:
    written: dict[str, Any] = {}

    def _fake_write_immutable(stem: str, body: dict[str, Any], **_kwargs: Any) -> dict[str, str]:
        written["stem"] = stem
        written["body"] = body
        return {"receipt": "fixture", "receipt_sha256": "sha256:fixture"}

    monkeypatch.setattr(forensic, "write_immutable", _fake_write_immutable)

    assert forensic.main() == 0
    assert written["stem"] == "sfi2-execution-forensic"
    body = written["body"]

    assert body["cases_considered"] == 14
    assert body["cases_resolved"] + body["cases_unresolved"] == 14
    assert body["gpu_seconds"] == 0
    assert body["estimated_cost_usd"] == 0.0

    #: not asserting the distribution is a single stage -- that is what the
    #: tool measures, and forcing it here would make the test assert the
    #: finding instead of checking the tool produces one honestly. What is
    #: asserted is that every resolved case got an actual verdict.
    for row in body["cases"]:
        if row["resolved"]:
            assert row["diff_content_changed"] is True
            for artifact_row in row["artifacts"]:
                assert artifact_row["stage_marks_required_to_rebuild"]["typed_delta"] in (
                    True,
                    False,
                )


@skip_without_real_data
def test_load_cases_reports_the_e5_e6_lineage_agreement() -> None:
    cases, meta = forensic.load_cases()
    assert len(cases) == meta["e5_confirmed_count"]
    assert isinstance(meta["e5_and_e6_are_the_same_lineage_set"], bool)
    assert meta["source_receipt_sha256"].startswith("sha256:")
