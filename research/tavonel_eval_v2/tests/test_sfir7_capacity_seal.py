"""Controls for SFIR7's capacity seal.

The one that matters most is that the sealer can return either answer. A sealer
that can only report a shortfall distinguishes nothing, exactly like a guard that
can never go red -- and it would be the more dangerous of the two here, because
SFIR7's entire question is whether an externally chosen frame produces a
different capacity. So both verdicts are driven, from synthetic censuses built
around the threshold.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import seal_sfir7_capacity_outcome as sealer  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402

CAP = sources.SOURCE_POOLS["git_docs"]["max_candidates_per_repository"]


def _census(tmp_path: Path, *, candidates: int, roots: int = 50, bound_excluded: int = 0,
            per_root: dict | None = None, attested: int = 50) -> Path:
    """A census with a chosen number of candidates spread over roots."""
    rows = []
    if per_root:
        for root_id, many in per_root.items():
            rows.extend(
                {"lineage_id": f"git:{root_id}:doc{i}.md", "discovery_root_id": root_id}
                for i in range(many)
            )
    else:
        for i in range(candidates):
            root_id = f"git:owner{i % max(roots, 1)}/repo{i % max(roots, 1)}"
            rows.append({"lineage_id": f"git:doc{i}.md", "discovery_root_id": root_id})

    dispositions = [
        {"discovery_root_id": f"git:owner{i}/repo{i}", "state": "COMPLETE"}
        for i in range(roots - bound_excluded)
    ]
    dispositions += [
        {
            "discovery_root_id": f"git:owner{roots - 1 - i}/repo{roots - 1 - i}",
            "state": "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
            "reason": "GLOBAL_GIT_REQUEST_BOUND",
        }
        for i in range(bound_excluded)
    ]
    body = {
        "families": {"git_docs": {"candidates": rows, "root_dispositions": dispositions}},
        "identity_attestation": {"roots_attested": attested, "rename_count": 0},
    }
    path = tmp_path / "census.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


# --- the seal can return either answer ---------------------------------------


def test_a_census_that_clears_the_threshold_is_sealed_as_met(tmp_path: Path):
    """The control that keeps this sealer from being decorative.

    SFIR7 exists to find out whether an externally chosen frame reaches a
    capacity TAVONEL's own roots did not. A sealer incapable of saying so would
    answer that question the same way regardless of the data.
    """
    body = sealer.build(_census(tmp_path, candidates=800))
    assert body["state"] == "CAPACITY_CRITERION_APPLIED_AND_MET"
    assert body["family"]["C"] == 800
    assert body["family"]["Q"] == 640
    assert body["family"]["meets_criterion"] is True


def test_a_census_below_the_threshold_is_sealed_as_failed(tmp_path: Path):
    body = sealer.build(_census(tmp_path, candidates=700))
    assert body["state"] == "CAPACITY_CRITERION_APPLIED_AND_FAILED"
    assert body["family"]["meets_C"] is False


def test_the_threshold_bites_exactly_where_the_criterion_says(tmp_path: Path):
    """750 passes C; 749 does not. Q trails at 0.8, so C is the binding half."""
    assert sealer.build(_census(tmp_path, candidates=750))["family"]["meets_criterion"] is True
    assert sealer.build(_census(tmp_path, candidates=749))["family"]["meets_criterion"] is False


def test_the_quota_is_the_inherited_formula_and_is_capped_at_a_thousand(tmp_path: Path):
    assert sealer.build(_census(tmp_path, candidates=1000))["family"]["Q"] == 800
    assert sealer.build(_census(tmp_path, candidates=5000))["family"]["Q"] == 1000


# --- the three kinds of shortfall are kept apart -----------------------------


def test_a_bound_exclusion_is_reported_as_its_own_kind(tmp_path: Path):
    """A budget exhausted is not a statement about how much documentation exists."""
    body = sealer.build(_census(tmp_path, candidates=400, bound_excluded=12))
    cut = body["why_a_shortfall_would_be_which_kind"]["frame_cut_by_an_inherited_bound"]
    assert cut["roots_excluded"] == 12
    assert cut["bound"] == sources.MAX_GIT_API_REQUESTS_GLOBAL
    assert cut["registered_in_advance_as"] == "INC-V2-115"
    assert body["family"]["roots_complete"] == 38


def test_a_root_at_the_per_root_cap_makes_the_count_a_floor(tmp_path: Path):
    """SFIR6's highest root was 73 against a cap of 80, which is why that
    shortfall was not a cap artifact. If SFIR7's roots hit 80, C understates.
    """
    body = sealer.build(
        _census(tmp_path, candidates=0, per_root={"git:a/b": CAP, "git:c/d": 5})
    )
    capped = body["why_a_shortfall_would_be_which_kind"]["roots_that_hit_the_per_root_cap"]
    assert capped["roots_at_the_cap"] == ["git:a/b"]
    assert capped["cap"] == CAP


def test_a_capped_census_is_not_sealable(tmp_path: Path):
    """A count that is a floor cannot be certified as a measurement."""
    body = sealer.build(
        _census(tmp_path, candidates=0, per_root={"git:a/b": CAP, "git:c/d": 900})
    )
    assert body["family"]["is_sealable"] is False


def test_an_uncapped_census_is_sealable(tmp_path: Path):
    """So the refusal above is not the only answer this can give."""
    body = sealer.build(_census(tmp_path, candidates=0, per_root={"git:a/b": CAP - 1}))
    assert body["family"]["is_sealable"] is True


def test_a_census_with_no_identity_attestation_is_not_sealable(tmp_path: Path):
    """Unattested roots may not be the roots that were selected."""
    body = sealer.build(_census(tmp_path, candidates=800, attested=0))
    assert body["family"]["is_sealable"] is False


# --- integrity ---------------------------------------------------------------


def test_duplicate_lineages_refuse_the_seal(tmp_path: Path):
    """C is a count of distinct documents or it is not a capacity."""
    body = {
        "families": {
            "git_docs": {
                "candidates": [
                    {"lineage_id": "git:a/b:x.md", "discovery_root_id": "git:a/b"},
                    {"lineage_id": "git:a/b:x.md", "discovery_root_id": "git:a/b"},
                ],
                "root_dispositions": [],
            }
        },
        "identity_attestation": {"roots_attested": 1},
    }
    path = tmp_path / "census.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(sealer.SealRefused, match="duplicate lineage"):
        sealer.build(path)


def test_the_predecessor_count_is_compared_and_never_substituted(tmp_path: Path):
    """SFIR6's 293 must not leak into SFIR7's figures."""
    body = sealer.build(_census(tmp_path, candidates=412))
    assert body["family"]["C"] == 412
    assert body["frame_change_versus_predecessor"]["predecessor_C"] == 293
    assert body["frame_change_versus_predecessor"]["delta_C"] == 412 - 293


def test_the_seal_records_that_nothing_was_adjusted_to_suit_the_result(tmp_path: Path):
    body = sealer.build(_census(tmp_path, candidates=100))
    unchanged = body["what_was_not_done_about_the_result"]
    assert unchanged["roots_added"] == 0
    assert unchanged["threshold_lowered"] is False
    assert unchanged["n_changed"] is False
    assert unchanged["roster_edited"] is False


def test_the_seal_opens_no_payload_and_spends_no_corpus(tmp_path: Path):
    body = sealer.build(_census(tmp_path, candidates=100))
    assert body["payload_opened"] is False
    assert body["corpus_spent"] is False


def test_a_host_rate_limit_exclusion_is_its_own_kind(tmp_path: Path):
    """Our cap firing and GitHub's firing are different findings. The first is a
    budget we chose; the second is one imposed on us, and SFIR7 measured that
    the host counts requests our counter does not (INC-V2-119).
    """
    body = json.loads(_census(tmp_path, candidates=200).read_text(encoding="utf-8"))
    body["families"]["git_docs"]["root_dispositions"][:5] = [
        {
            "discovery_root_id": f"git:o{i}/n{i}",
            "state": "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
            "reason": "EXTERNAL_RATE_LIMIT_EXHAUSTED",
        }
        for i in range(5)
    ]
    path = tmp_path / "host.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    kinds = sealer.build(path)["why_a_shortfall_would_be_which_kind"]
    assert kinds["frame_cut_by_the_hosts_rate_limit"]["roots_excluded"] == 5
    assert kinds["frame_cut_by_an_inherited_bound"]["roots_excluded"] == 0
    assert kinds["frame_cut_by_the_hosts_rate_limit"]["the_fail_safe_was_not_widened"] is True


def test_the_two_exclusion_kinds_are_counted_separately(tmp_path: Path):
    body = json.loads(_census(tmp_path, candidates=200, bound_excluded=4).read_text("utf-8"))
    body["families"]["git_docs"]["root_dispositions"].append(
        {
            "discovery_root_id": "git:x/y",
            "state": "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
            "reason": "EXTERNAL_RATE_LIMIT_EXHAUSTED",
        }
    )
    path = tmp_path / "both.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    kinds = sealer.build(path)["why_a_shortfall_would_be_which_kind"]
    assert kinds["frame_cut_by_an_inherited_bound"]["roots_excluded"] == 4
    assert kinds["frame_cut_by_the_hosts_rate_limit"]["roots_excluded"] == 1
