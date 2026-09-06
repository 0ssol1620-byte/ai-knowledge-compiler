"""Unit-level counterparts to the R1, P0d and P4c gates.

Each gate below is measured over a corpus or a fixture and can pass for the
wrong reason. These pin the behaviours the gates exist to protect:

* the span partition is total and non-overlapping, and the filler does **not**
  get to call its own gaps MODELED;
* an ignored construct and an unmodeled one are different classifications, and
  a reference-bearing construct is a fact rather than prose;
* immutable receipts refuse to be overwritten and the pointer carries no
  evidence;
* P4c question construction never emits a forbidden intent source.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]

sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(NS / "canonicalization"))
sys.path.insert(0, str(NS / "tools"))
sys.path.insert(0, str(NS / "acquisition"))

import source_spans as spans_mod  # noqa: E402
from source_spans import (  # noqa: E402
    IGNORED,
    MODELED,
    REFERENCE_KINDS,
    UNMODELED,
    attribute_to_canonical,
    coverage,
    html_spans,
    markdown_spans,
    partition_holds,
    reference_facts,
)


# --- P0d: the partition ------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "# Title\n\nSome prose here.\n",
        "<!-- editor note -->\n# Title\n\nSee [the guide](https://example.invalid/g).\n",
        "---\nweight: 3\n---\n\n{{< api-reference page=\"apps/deployment-v1\" >}}\n",
        "",
        "```\ncode block\n```\n",
    ],
)
def test_markdown_spans_partition_the_whole_source(text: str) -> None:
    spans = markdown_spans(text)
    result = partition_holds(spans, len(text))
    assert result["holds"], result
    assert result["gap_count"] == 0
    assert result["overlap_count"] == 0
    assert result["covered_to"] == len(text)


def test_the_filler_does_not_declare_its_own_gaps_modeled() -> None:
    """The failure mode the whole protocol is about.

    A filler that marked unclassified source MODELED would report total
    coverage by construction. Attribution is a separate, evidenced step.
    """
    spans = markdown_spans("A sentence the grammar has no rule for.\n")
    prose = [s for s in spans if s.kind == "prose"]
    assert prose, "expected the filler to produce a prose span"
    assert all(s.classification == UNMODELED for s in prose)


def test_prose_becomes_modeled_only_when_it_reached_a_canonical_unit() -> None:
    text = "The quota resets at midnight.\n"
    spans = markdown_spans(text)
    attribute_to_canonical(spans, ["The quota resets at midnight."], [])
    assert all(s.classification != UNMODELED for s in spans), [s.as_dict() for s in spans]

    spans = markdown_spans(text)
    attribute_to_canonical(spans, ["something else entirely"], [])
    assert any(s.classification == UNMODELED for s in spans)


# --- P0d: ignored is not unmodeled -------------------------------------------


def test_an_html_comment_is_ignored_by_declared_policy_not_unmodeled() -> None:
    spans = markdown_spans("<!-- reviewers: do not ship -->\n")
    comment = [s for s in spans if s.kind == "html_comment"]
    assert comment and comment[0].classification == IGNORED


def test_an_unrecognised_html_attribute_is_unmodeled_not_ignored() -> None:
    """An attribute in neither declared list is surfaced, never folded away."""
    spans = html_spans('<policyref binding="true" targetref="reg/2026/117"></policyref>')
    kinds = {s.classification for s in spans}
    assert UNMODELED in kinds, [s.as_dict() for s in spans]


def test_ignored_and_unmodeled_are_distinct_constants() -> None:
    assert IGNORED != UNMODELED != MODELED


# --- P0d: reference edges are facts, not prose -------------------------------


@pytest.mark.parametrize(
    "text,kind,target",
    [
        ("See [the guide](https://example.invalid/g).\n", "hyperlink", "https://example.invalid/g"),
        ("![alt](/img/a.png)\n", "image", "/img/a.png"),
        ("[ref]: https://example.invalid/r\n", "link_definition", "https://example.invalid/r"),
    ],
)
def test_reference_targets_are_captured_as_typed_facts(
    text: str, kind: str, target: str
) -> None:
    facts = reference_facts(markdown_spans(text))
    assert facts, text
    assert facts[0]["reference_kind"] == kind
    assert facts[0]["reference_kind"] in REFERENCE_KINDS
    assert facts[0]["target"] == target


def test_a_directive_argument_is_a_fact_which_is_what_inc_v2_006_missed() -> None:
    before = reference_facts(markdown_spans('{{< api-reference page="apps/deployment-v1" >}}\n'))
    after = reference_facts(
        markdown_spans('{{< api-reference page="workload-resources/deployment-v1" >}}\n')
    )
    assert before and after
    assert before[0]["reference_kind"] == "directive"
    assert before != after, "the moved directive argument must be visible as a fact change"


def test_an_include_directive_is_typed_as_include_not_directive() -> None:
    facts = reference_facts(markdown_spans('{{< include "shared/notice.md" >}}\n'))
    assert facts and facts[0]["reference_kind"] == "include"


# --- P0d: coverage arithmetic ------------------------------------------------


def test_coverage_shares_sum_to_one_and_exclude_unmodeled_from_source_coverage() -> None:
    text = "<!-- note -->\nPresent prose.\nAbsent prose.\n"
    spans = markdown_spans(text)
    attribute_to_canonical(spans, ["Present prose."], [])
    result = coverage(spans)
    assert result["total"] == len(text)
    total_share = result["modeled_share"] + result["ignored_share"] + result["unmodeled_share"]
    assert total_share == pytest.approx(1.0)
    assert result["source_coverage"] == pytest.approx(
        result["modeled_share"] + result["ignored_share"]
    )
    assert result["unmodeled_share"] > 0.0


def test_the_containment_probe_is_loose_in_one_direction_only() -> None:
    """Coverage is an upper bound, and the module says so where it is computed.

    A future edit that made the probe stricter would lower coverage; one that
    made it looser would raise it silently. Pinning the documented direction is
    the cheapest guard against the second.
    """
    doc = spans_mod._fold.__doc__ or ""
    assert "over-reporting coverage" in doc
    assert "larger, never smaller" in doc


# --- R1: the immutable receipt contract --------------------------------------


def test_write_immutable_refuses_to_reuse_a_run_specific_path() -> None:
    """Run out-of-process, because the oracle isolation probe another test
    module installs on ``sys.meta_path`` is global to the interpreter. The real
    contract is exercised in a subprocess for the same reason."""
    tools = str(NS / "tools")
    probe = f'''
import json, sys
sys.path.insert(0, {tools!r})
from evidence import ReceiptExists, write_immutable
from pathlib import Path

stem = "unit-test-immutability"
run_id = "20260822T000000Z-000000000000"
kw = dict(tool=Path({str(NS / "tools" / "reproducibility_fixture.py")!r}),
          protocol=Path({str(NS / "protocols" / "R1_receipt_reproducibility.yaml")!r}),
          run_id=run_id, pointer=False)

first = write_immutable(stem, {{"value": 1}}, **kw)
path = Path({str(ROOT)!r}) / first["receipt"]
before = path.read_bytes()
result = {{"refused": False, "unchanged": None, "receipt": first["receipt"]}}
try:
    write_immutable(stem, {{"value": 2}}, **kw)
except ReceiptExists as error:
    result["refused"] = True
    result["exception"] = type(error).__name__
result["unchanged"] = path.read_bytes() == before
path.unlink(missing_ok=True)
print(json.dumps(result))
'''
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, cwd=ROOT
    )
    result = json.loads(done.stdout)
    assert result["refused"], result
    assert result["exception"] == "ReceiptExists"
    assert result["unchanged"], "the standing receipt must survive a collision attempt"


def test_the_r1_receipt_records_all_seven_gates_passing() -> None:
    receipts = sorted((NS / "receipts").glob("r1-reproducibility-check--*.json"))
    assert receipts, "the owed reproducibility check has no receipt"
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    gates = body["gates"]
    assert len(gates) == 7, sorted(gates)
    assert all(g["passed"] for g in gates.values()), gates
    assert gates["G_R1_DISTINCT_PATHS"]["first_run_id"] != gates["G_R1_DISTINCT_PATHS"]["second_run_id"]
    assert gates["G_R1_OVERWRITE_REFUSED"]["exception"] == "ReceiptExists"
    assert gates["G_R1_POINTER_IS_NOT_EVIDENCE"]["declares_is_evidence_false"]
    assert gates["G_R1_POINTER_IS_NOT_EVIDENCE"]["payload_fields_found_in_pointer"] == []


def test_the_fixture_reads_no_clock_randomness_or_environment() -> None:
    """A fixture that read any of these could not prove reproducibility."""
    tree = ast.parse((NS / "tools" / "reproducibility_fixture.py").read_text(encoding="utf-8"))
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not imported & {"time", "datetime", "random", "os", "secrets", "uuid"}, imported


def test_two_subprocess_runs_agree_on_the_semantic_digest_but_not_the_path() -> None:
    """Two runs, same semantics, different paths.

    The fixture writes into the REAL receipts directory, because that is the
    contract under test -- a run id collision has to be a real collision. It
    therefore also moves the REAL `receipts/latest` pointer, since
    `write_immutable` updates one unless told not to.

    This test used to delete the two receipts and leave the pointer naming the
    second one. That is INC-V2-097: a pointer to a receipt that exists nowhere,
    on disk or in git. It was observed three times and its cause was recorded as
    not established; this is the cause. Restoring the pointer is not tidiness --
    a dangling pointer is an authority naming bytes nobody can produce, which is
    the exact shape INC-V2-089 is about.
    """
    fixture = NS / "tools" / "reproducibility_fixture.py"
    pointer = NS / "receipts" / "latest" / "r1-reproducibility-fixture.json"
    before = pointer.read_bytes() if pointer.is_file() else None
    runs = []
    try:
        runs = [
            json.loads(
                subprocess.run(
                    [sys.executable, str(fixture)],
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=ROOT,
                ).stdout
            )
            for _ in range(2)
        ]
        assert runs[0]["semantic_result_digest"] == runs[1]["semantic_result_digest"]
        assert runs[0]["receipt"] != runs[1]["receipt"]
        assert runs[0]["run_id"] != runs[1]["run_id"]
    finally:
        for run in runs:
            (ROOT / run["receipt"]).unlink(missing_ok=True)
        # in `finally`, and after the unlinks: a failed assertion must not be
        # able to leave the pointer dangling either, which is how this went
        # unnoticed for three occurrences
        if before is None:
            pointer.unlink(missing_ok=True)
        else:
            pointer.write_bytes(before)


def test_the_fixture_test_above_leaves_no_dangling_pointer() -> None:
    """The control for the repair, asserted against the real pointer.

    INC-V2-097's standing gate checks every pointer in the tree; this one checks
    the specific pointer the test above disturbs, so a regression is attributed
    here rather than surfacing later as an unexplained dangling reference.
    """
    pointer = NS / "receipts" / "latest" / "r1-reproducibility-fixture.json"
    if not pointer.is_file():
        pytest.skip("no r1 fixture pointer in this tree")
    target = ROOT / json.loads(pointer.read_text(encoding="utf-8"))["points_to"]
    assert target.is_file(), f"pointer names a receipt that is not on disk: {target}"


# --- P4c: question construction ----------------------------------------------


def test_no_machine_identifier_reaches_any_p4c_query() -> None:
    """The correction P4c exists to make.

    P4b put ticker and CIK in the query together, so its SEC routing was partly
    reading a ten-digit key nobody types. A CIK is ten consecutive digits; no
    scored query may contain one.
    """
    import re  # noqa: PLC0415

    receipts = sorted((NS / "receipts").glob("p4c-retrieval-validity--*.json"))
    assert receipts
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    cik = re.compile(r"\d{10}")
    for row in body["core_rows"] + body["global_rows"]:
        assert not cik.search(row["query"]), row["query"]


def test_no_p4c_query_carries_a_revision_or_currency_indicator() -> None:
    forbidden = ("superseded", "current revision", "before/after", "oldid=", "revision id")
    receipts = sorted((NS / "receipts").glob("p4c-retrieval-validity--*.json"))
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    for row in body["core_rows"] + body["global_rows"]:
        lowered = row["query"].lower()
        assert not any(token in lowered for token in forbidden), row["query"]


def test_the_p4c_selection_rule_is_frozen_and_mentions_no_score() -> None:
    from sources_p4c import SELECTION_RULE  # noqa: PLC0415

    assert SELECTION_RULE["one_pair_per_source_document"] is True
    assert SELECTION_RULE["frozen_before_any_retrieval_result"] is True
    text = json.dumps(SELECTION_RULE).lower()
    assert "score" not in text and "rank" not in text and "bm25" not in text


def test_p4c_reuses_the_p4b_ranking_rather_than_writing_it_a_third_time() -> None:
    """INC-V2-007 was caused by writing the unit-level ranking twice."""
    tree = ast.parse((NS / "tools" / "run_p4c.py").read_text(encoding="utf-8"))
    reused = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "run_p4b"
        for alias in node.names
    }
    assert {"rank", "FieldedBm25"} <= reused, reused


def test_the_two_p4c_endpoints_carry_separate_verdicts() -> None:
    receipts = sorted((NS / "receipts").glob("p4c-retrieval-validity--*.json"))
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    assert body["P4c_Core"]["verdict"] == "FAIL"
    assert body["P4c_Global"]["verdict"] == "PASS"
    assert "verdict" not in body, "a combined verdict would merge two endpoints into one number"


def test_no_p4c_run_spent_anything() -> None:
    receipts = sorted((NS / "receipts").glob("p4c-retrieval-validity--*.json"))
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    assert body["gpu_seconds"] == 0
    assert body["estimated_cost_usd"] == 0.0
