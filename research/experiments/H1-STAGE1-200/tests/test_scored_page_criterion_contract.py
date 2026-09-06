"""The confirmatory denominator is not selective, and stays that way.

51 of the frozen 800 pages carry no official text score and leave the primary
endpoint's denominator. The danger is not the count, it is the *reason*: an
exclusion correlated with output quality would strip out the worst pages and
bias the measured error rate downward invisibly.

These tests pin the finding that the exclusion is decided by ground truth alone
-- a page is scored exactly when its annotation carries body text -- and that
the rule was checked against the evaluator's real output rather than asserted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
RECEIPTS = ROOT / "research" / "experiments" / "H1-A9-01" / "receipts"
SCRIPTS = ROOT / "research" / "experiments" / "H1-A9-01" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from scored_page_criterion import BODY_TEXT_CATEGORIES, has_body_text  # noqa: E402

RECEIPT = RECEIPTS / "scored-page-criterion-2026-08-18.json"


def receipt() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_the_criterion_was_checked_against_every_holdout_page() -> None:
    data = receipt()
    assert data["pages_in_ground_truth"] == 800
    assert data["criterion_reproduces_the_evaluator_exactly"] is True
    assert data["disagreements_unscored_despite_body_text"] == []
    assert data["disagreements_scored_without_body_text"] == []


def test_the_exclusion_cannot_depend_on_the_prediction() -> None:
    """The whole argument. If this flips, the denominator is suspect."""
    assert receipt()["criterion_reads_predictions"] is False


def test_the_excluded_pages_are_a_real_and_stated_quantity() -> None:
    data = receipt()
    excluded = data["pages_in_ground_truth"] - data["pages_scored_by_the_evaluator"]
    assert excluded == 51
    assert data["pages_predicted_unscored"] == excluded


@pytest.mark.parametrize(
    "category",
    ["text_block", "title", "reference", "code_txt"],
)
def test_body_text_categories_qualify(category: str) -> None:
    page = {"layout_dets": [{"category_type": category}]}
    assert has_body_text(page) is True


@pytest.mark.parametrize(
    "category",
    # These are precisely the categories that misled the first attempt at this
    # rule: they belong to the evaluator's matched-element text group, so the
    # obvious 16-category predictor called 48 table-only pages scoreable. They
    # do not, on their own, earn a page a text score.
    ["table_caption", "table_footnote", "header", "footer", "page_number",
     "figure_caption", "figure_footnote", "page_footnote", "table", "figure"],
)
def test_peripheral_and_caption_categories_do_not_qualify(category: str) -> None:
    page = {"layout_dets": [{"category_type": category}]}
    assert has_body_text(page) is False


def test_the_criterion_is_discriminating_not_trivially_true() -> None:
    """A rule that accepted everything would also show zero disagreements."""
    assert has_body_text({"layout_dets": []}) is False
    assert (
        has_body_text(
            {"layout_dets": [{"category_type": "table"}, {"category_type": "header"}]}
        )
        is False
    )
    assert (
        has_body_text(
            {"layout_dets": [{"category_type": "table"}, {"category_type": "title"}]}
        )
        is True
    )


def test_the_category_set_is_the_minimal_one_that_was_measured() -> None:
    """Widening this set silently would re-admit the 48-page error."""
    assert set(BODY_TEXT_CATEGORIES) == {"text_block", "title", "reference", "code_txt"}
    assert set(receipt()["body_text_categories"]) == set(BODY_TEXT_CATEGORIES)


def test_result_artifact_hashes_in_the_protocol_still_match() -> None:
    """A silent receipt overwrite already happened once in this work.

    Two duplicate background jobs raced on the power-calculation receipt and the
    second replaced the first with third-decimal-different Monte-Carlo values.
    Nothing failed; the document and the receipt simply stopped agreeing, and it
    was noticed by chance. The protocol now pins each result artifact's sha256,
    and this checks the pin against the file on disk.

    A mismatch does not necessarily mean tampering -- regenerating a receipt is a
    normal thing to do. It means the protocol's recorded hash and the artifact
    have diverged, and one of the two needs updating deliberately rather than
    silently.
    """
    import hashlib
    import re

    protocol = (
        Path(__file__).resolve().parents[4]
        / "research" / "experiments" / "H1-A9-01"
        / "A9_CONFIRMATORY_PROTOCOL_2026-08-18.md"
    ).read_text(encoding="utf-8")

    pinned = dict(
        re.findall(r"^\| `([^`]+\.json)` \| `([0-9a-f]{64})` \|$", protocol, re.MULTILINE)
    )
    assert pinned, "the protocol no longer pins any result artifact hash"

    for name, expected in sorted(pinned.items()):
        path = RECEIPTS / name
        assert path.is_file(), f"pinned artifact is missing: {name}"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, (
            f"{name} no longer matches the hash recorded in the protocol.\n"
            f"  protocol: {expected}\n  on disk:  {actual}\n"
            "Regenerating a receipt is normal; doing so without updating the "
            "protocol is how a document and its evidence drift apart."
        )
