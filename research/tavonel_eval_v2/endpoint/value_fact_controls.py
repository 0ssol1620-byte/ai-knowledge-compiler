"""Frozen fixtures for the ValueFact extractor: positive, negative, adversarial.

The extractor decides what may be asked, so a defect here does not show up as a
wrong answer — it shows up as a cohort that looks fine and measures something
else. These fixtures are frozen with the extractor and run before acquisition.

The adversarial cases are the ones that matter. Each is a candidate that *would*
pass a naive reading and must not: a renamed key, a value that only looks
changed, a label carrying its own answer, a row that appears twice, an atom with
a second changed number beside the one being asked about.
"""

from __future__ import annotations

from typing import Any

from value_fact import (
    AMBIGUOUS_VALUE_FACT,
    PROPERTY_NOT_STABLE,
    VALUE_KIND_MISMATCH,
    VALUE_UNCHANGED,
    atom_contrast_is_single,
    question_is_blind_to_the_value,
    question_query,
    value_facts,
)

_MD_BEFORE = """# Flags

| Flag | Description | Default |
| --- | --- | --- |
| --query.lookback-delta | Maximum query lookback duration. | 5 |
| --storage.retention | How long to retain samples. | 15 |
"""

_MD_AFTER = """# Flags

| Flag | Description | Default |
| --- | --- | --- |
| --query.lookback-delta | Maximum query lookback duration. | 9 |
| --storage.retention | How long to retain samples. | 15 |
"""

_HTML_BEFORE = """<h2>Overview</h2><table>
<tr><th>Founded</th><td>1998-09-04</td></tr>
<tr><th>Employees</th><td>1,200</td></tr>
</table>"""

_HTML_AFTER = """<h2>Overview</h2><table>
<tr><th>Founded</th><td>1998-09-04</td></tr>
<tr><th>Employees</th><td>1,450</td></tr>
</table>"""

#: A renamed key. The value changed, but nothing stable binds the two.
_RENAMED_BEFORE = """| Option | Default |
| --- | --- |
| --timeout-seconds | 30 |
"""
_RENAMED_AFTER = """| Option | Default |
| --- | --- |
| --request-timeout-seconds | 60 |
"""

#: Typography only. 1,200 and 1200 are one value written twice.
_TYPOGRAPHY_BEFORE = """| Key | Value |
| --- | --- |
| Employees | 1,200 |
"""
_TYPOGRAPHY_AFTER = """| Key | Value |
| --- | --- |
| Employees | 1200 |
"""

#: A kind change. A version becoming a date is not a value contrast of one kind.
_KIND_BEFORE = """| Key | Value |
| --- | --- |
| Release | 2.14.1 |
"""
_KIND_AFTER = """| Key | Value |
| --- | --- |
| Release | 2026-04-01 |
"""

#: The label carries a number, so the question would state part of the answer.
_LABEL_BEFORE = """| Key | Value |
| --- | --- |
| Limit for tier 2 | 30 |
"""
_LABEL_AFTER = """| Key | Value |
| --- | --- |
| Limit for tier 2 | 60 |
"""

#: The same key twice under one heading. Choosing by ordinal would hide it.
_DUPLICATE_BEFORE = """| Key | Value |
| --- | --- |
| Threshold | 10 |
| Threshold | 20 |
"""
_DUPLICATE_AFTER = """| Key | Value |
| --- | --- |
| Threshold | 30 |
| Threshold | 40 |
"""

#: A version chain. Under the scorer's overlapping patterns this cell looks like
#: two values ("2.14.1" and "2.14" inside it); dominance is what makes it one.
_VERSION_BEFORE = """| Key | Value |
| --- | --- |
| Release | 2.14.1 |
"""
_VERSION_AFTER = """| Key | Value |
| --- | --- |
| Release | 2.15.0 |
"""

#: Two values at their own positions. "5" is a substring of "15" and must not be
#: swallowed by it — string containment would admit this cell as holding one.
_TWO_POSITIONS_BEFORE = """| Key | Value |
| --- | --- |
| Window | 5 to 15 |
"""
_TWO_POSITIONS_AFTER = """| Key | Value |
| --- | --- |
| Window | 7 to 17 |
"""

#: A range, not a value.
_RANGE_BEFORE = """| Key | Value |
| --- | --- |
| Window | between 5 and 10 |
"""
_RANGE_AFTER = """| Key | Value |
| --- | --- |
| Window | between 7 and 12 |
"""


def _facts(before: str, after: str, suffix: str = ".md") -> dict[str, Any]:
    return value_facts("doc:control", before, after, suffix)


CONTROLS: tuple[dict[str, Any], ...] = (
    {
        "name": "positive_markdown_table_default",
        "kind": "positive",
        "guards": "the ordinary case: one row label, one column, one changed value",
    },
    {
        "name": "positive_html_infobox_row",
        "kind": "positive",
        "guards": "a th/td row is a source-native key/value and must be read as one",
    },
    {
        "name": "negative_unchanged_row_is_not_a_fact",
        "kind": "negative",
        "guards": "a row that did not change is not a currency question",
    },
    {
        "name": "adversarial_renamed_key",
        "kind": "adversarial",
        "guards": "a renamed option is a different property, not a changed value",
    },
    {
        "name": "adversarial_typography_only",
        "kind": "adversarial",
        "guards": "1,200 and 1200 are the same value; the scorer says so and so must this",
    },
    {
        "name": "adversarial_value_kind_change",
        "kind": "adversarial",
        "guards": "a version becoming a date is not a single-kind contrast",
    },
    {
        "name": "adversarial_label_contains_a_number",
        "kind": "adversarial",
        "guards": "a label carrying a value would put part of the answer in the question",
    },
    {
        "name": "adversarial_duplicate_row_label",
        "kind": "adversarial",
        "guards": "two rows claiming one key is ambiguity, not a choice of ordinal",
    },
    {
        "name": "positive_version_chain_is_one_value",
        "kind": "positive",
        "guards": "nested pattern matches must not make a version look like two values",
    },
    {
        "name": "adversarial_two_values_at_their_own_positions",
        "kind": "adversarial",
        "guards": "dominance is span containment, not string containment",
    },
    {
        "name": "adversarial_range_is_not_a_value",
        "kind": "adversarial",
        "guards": "a cell holding two tokens binds no single value",
    },
    {
        "name": "adversarial_atom_carries_a_second_changed_number",
        "kind": "adversarial",
        "guards": "answering from a neighbouring change is not currency selection",
    },
    {
        "name": "adversarial_question_never_states_a_value",
        "kind": "adversarial",
        "guards": "the generated question must be blind to both values",
    },
)


def run_controls() -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    def record(name: str, ok: bool, observed: str) -> None:
        control = next(c for c in CONTROLS if c["name"] == name)
        results.append(
            {
                "name": name,
                "kind": control["kind"],
                "guards": control["guards"],
                "agrees": bool(ok),
                "observed": observed,
            }
        )

    got = _facts(_MD_BEFORE, _MD_AFTER)
    one = len(got["facts"]) == 1 and got["facts"][0]["property_label"] == "--query.lookback-delta"
    changed = one and (got["facts"][0]["current_value"], got["facts"][0]["superseded_value"]) == (
        "9",
        "5",
    )
    record("positive_markdown_table_default", one and changed, str(len(got["facts"])) + " fact(s)")
    record(
        "negative_unchanged_row_is_not_a_fact",
        any(r["code"] == VALUE_UNCHANGED for r in got["rejected"]),
        ",".join(sorted({r["code"] for r in got["rejected"]})),
    )

    html = value_facts("doc:control", _HTML_BEFORE, _HTML_AFTER, ".html")
    ok = len(html["facts"]) == 1 and html["facts"][0]["property_label"] == "Employees"
    ok = ok and html["facts"][0]["current_value"] == "1450"
    record("positive_html_infobox_row", ok, str(len(html["facts"])) + " fact(s)")

    renamed = _facts(_RENAMED_BEFORE, _RENAMED_AFTER)
    record(
        "adversarial_renamed_key",
        not renamed["facts"]
        and any(r["code"] == PROPERTY_NOT_STABLE for r in renamed["rejected"]),
        ",".join(sorted({r["code"] for r in renamed["rejected"]})),
    )

    typography = _facts(_TYPOGRAPHY_BEFORE, _TYPOGRAPHY_AFTER)
    record(
        "adversarial_typography_only",
        not typography["facts"]
        and any(r["code"] == VALUE_UNCHANGED for r in typography["rejected"]),
        ",".join(sorted({r["code"] for r in typography["rejected"]})),
    )

    kind = _facts(_KIND_BEFORE, _KIND_AFTER)
    record(
        "adversarial_value_kind_change",
        not kind["facts"] and any(r["code"] == VALUE_KIND_MISMATCH for r in kind["rejected"]),
        ",".join(sorted({r["code"] for r in kind["rejected"]})),
    )

    label = _facts(_LABEL_BEFORE, _LABEL_AFTER)
    record("adversarial_label_contains_a_number", not label["facts"], str(len(label["facts"])))

    duplicate = _facts(_DUPLICATE_BEFORE, _DUPLICATE_AFTER)
    record("adversarial_duplicate_row_label", not duplicate["facts"], str(len(duplicate["facts"])))

    version = _facts(_VERSION_BEFORE, _VERSION_AFTER)
    ok = len(version["facts"]) == 1 and version["facts"][0]["value_kind"] == "version_chain"
    ok = ok and version["facts"][0]["current_value"] == "2.15.0"
    record("positive_version_chain_is_one_value", ok, str(len(version["facts"])) + " fact(s)")

    positions = _facts(_TWO_POSITIONS_BEFORE, _TWO_POSITIONS_AFTER)
    record(
        "adversarial_two_values_at_their_own_positions",
        not positions["facts"],
        str(len(positions["facts"])),
    )

    span = _facts(_RANGE_BEFORE, _RANGE_AFTER)
    record("adversarial_range_is_not_a_value", not span["facts"], str(len(span["facts"])))

    fact = got["facts"][0] if got["facts"] else None
    if fact is not None:
        noisy = atom_contrast_is_single(
            fact,
            "lookback 9 and retention 30",
            "lookback 5 and retention 15",
        )
        clean = atom_contrast_is_single(
            fact,
            "the lookback default is 9",
            "the lookback default is 5",
        )
        record(
            "adversarial_atom_carries_a_second_changed_number",
            noisy["single_contrast"] is False
            and noisy["code"] == AMBIGUOUS_VALUE_FACT
            and clean["single_contrast"] is True,
            "noisy=" + str(noisy["single_contrast"]) + " clean=" + str(clean["single_contrast"]),
        )
        blind = question_is_blind_to_the_value(question_query(fact), fact)
        record(
            "adversarial_question_never_states_a_value",
            blind["blind"] is True,
            question_query(fact),
        )
    else:  # pragma: no cover - the positive control failing already fails the run
        record("adversarial_atom_carries_a_second_changed_number", False, "no fact")
        record("adversarial_question_never_states_a_value", False, "no fact")

    by_kind = {
        name: all(r["agrees"] for r in results if r["kind"] == name)
        for name in ("positive", "negative", "adversarial")
    }
    return {
        "results": results,
        "all_agree": all(r["agrees"] for r in results),
        "by_kind": by_kind,
        "three_directions_passed": all(by_kind.values()),
    }
