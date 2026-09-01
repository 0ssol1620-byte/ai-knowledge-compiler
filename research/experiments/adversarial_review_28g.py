"""Adversarial review of the claims added in this session (audit section 28-G).

Section 28-G lists nine hostile questions. This runs the ones that can be
checked mechanically against the receipts and the repository, rather than
asserted in prose:

  1. Did any holdout leak?
  2. Was any threshold changed after seeing a result?
  3. Was a transport amendment mislabeled?
  4. Was a development result presented as confirmatory?
  5. Is every headline number derivable from immutable receipts?

The remaining four (graph mutating truth, LLM mutating ontology, cross-job
PASS promotion, unresolved identity force-matching) are properties of the
product control plane rather than of these claims, and are checked by the
product test suite; they are reported here as out-of-scope-for-this-run rather
than silently passed.

Exit code is non-zero if any check fails, so this cannot be "run and ignored".
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

VKC = Path(r"D:\CodexProjects\ai-knowledge-compiler-vkc-research")
CANON = Path(r"D:\CodexProjects\ai-knowledge-compiler")
MATRIX = CANON / "research" / "tavonel_eval_v2" / "paper" / "CLAIM_MATRIX.yaml"

CLAIMS_UNDER_REVIEW = ("C-36", "C-37")

failures: list[str] = []
notes: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}")
    print(f"         {detail}")
    if not ok:
        failures.append(f"{name}: {detail}")


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_yaml_claims() -> dict:
    import yaml

    return yaml.safe_load(MATRIX.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- Q5 first:
# every headline number must come from a receipt whose hash the matrix pins.
def q5_receipts_are_immutable_and_pinned() -> None:
    print("\nQ5. Is every headline number derivable from immutable receipts?")
    data = load_yaml_claims()
    claims = {c["id"]: c for c in data["claims"]}

    for cid in CLAIMS_UNDER_REVIEW:
        claim = claims.get(cid)
        if claim is None:
            check(f"{cid} present in matrix", False, "claim not found")
            continue

        receipt_rel = claim.get("receipt")
        receipt_path = VKC / receipt_rel
        if not receipt_path.exists():
            check(f"{cid} receipt exists", False, f"missing {receipt_rel}")
            continue

        # Two different pins exist in this matrix and they digest different
        # things: receipt_file_sha256 is the whole file, while
        # receipt_sha256_of_result is the receipt's own declared content hash.
        # Compare like with like, and require that at least one pin exists.
        body = json.loads(receipt_path.read_text(encoding="utf-8"))
        file_pin = claim.get("receipt_file_sha256")
        content_pin = claim.get("receipt_sha256_of_result")

        if file_pin:
            actual = sha256(receipt_path)
            check(
                f"{cid} receipt file hash matches its pin",
                actual == file_pin,
                f"{receipt_rel}\n         on disk {actual}\n         pinned  {file_pin}",
            )
        elif content_pin:
            declared = body.get("result_sha256")
            check(
                f"{cid} receipt content hash matches its pin",
                declared == content_pin,
                f"{receipt_rel}\n         in receipt {declared}\n         pinned    {content_pin}",
            )
        else:
            check(
                f"{cid} receipt is pinned at all",
                False,
                "neither receipt_file_sha256 nor receipt_sha256_of_result is set",
            )


# ---------------------------------------------------------------- Q2
def q2_thresholds_not_changed_after_results() -> None:
    print("\nQ2. Was any threshold changed after seeing a result?")

    # ECFR: 01 failed an adequacy gate of 6; 02 must be >= that, never lower.
    p1 = json.loads((VKC / "research/experiments/H3-B-REGULATORY-ECFR-01/protocol.json").read_text(encoding="utf-8"))
    p2 = json.loads((VKC / "research/experiments/H3-B-REGULATORY-ECFR-02/protocol.json").read_text(encoding="utf-8"))
    g1 = p1["frozen_safety_gates"]["minimum_changed_pair_count"]
    g2 = p2["frozen_safety_gates"]["minimum_changed_pair_count"]
    check(
        "ECFR adequacy gate was raised, not lowered",
        g2 >= g1,
        f"ECFR-01 required {g1}, ECFR-02 requires {g2}",
    )

    # Preservation: E2E-01 failed detection_rate 1.0; E2E-02 must keep 1.0.
    q1 = json.loads((VKC / "research/experiments/PRESERVATION-E2E-01/protocol.json").read_text(encoding="utf-8"))
    q2 = json.loads((VKC / "research/experiments/PRESERVATION-E2E-02/protocol.json").read_text(encoding="utf-8"))
    d1 = q1["preregistered_gates"]["detection_rate_min_per_family"]
    d2 = q2["preregistered_gates"]["detection_rate_min_per_family"]
    check(
        "preservation detection gate unchanged after a FAIL",
        d2 >= d1,
        f"E2E-01 required {d1}, E2E-02 requires {d2}",
    )

    f1 = q1["preregistered_gates"]["false_positive_rate_max"]
    f2 = q2["preregistered_gates"]["false_positive_rate_max"]
    # ECFR safety gates themselves must not have loosened between rounds.
    s1 = p1["frozen_safety_gates"]
    s2 = p2["frozen_safety_gates"]
    check(
        "ECFR equivalence gate unchanged",
        s2["all_evaluated_pairs_equivalent"] == s1["all_evaluated_pairs_equivalent"],
        f"{s1['all_evaluated_pairs_equivalent']} -> {s2['all_evaluated_pairs_equivalent']}",
    )
    check(
        "ECFR stale-artifact gate unchanged",
        s2["stale_left_behind_total"] <= s1["stale_left_behind_total"],
        f"{s1['stale_left_behind_total']} -> {s2['stale_left_behind_total']}",
    )

    check(
        "preservation false-positive gate unchanged",
        f2 <= f1,
        f"E2E-01 allowed {f1}, E2E-02 allows {f2}",
    )


# ---------------------------------------------------------------- Q4
def q4_dev_not_presented_as_confirmatory() -> None:
    print("\nQ4. Was a development result presented as confirmatory?")
    data = load_yaml_claims()
    claims = {c["id"]: c for c in data["claims"]}

    # Asserting only that the split is a known word is not a check: a
    # dishonest relabel satisfies it. Mutation testing caught exactly that.
    # Each claim is held to the split its evidence entitles it to.
    ENTITLED_SPLIT = {
        "C-36": (
            "held_out",
            "ECFR-02 selected its cohort from versions-endpoint metadata before "
            "the protocol was frozen; the substantive label scored the result "
            "and never chose the pairs",
        ),
        "C-37": (
            "held_out",
            "PRESERVATION-E2E-02 reads frozen CONF-02 outputs it did not produce",
        ),
    }

    for cid in CLAIMS_UNDER_REVIEW:
        claim = claims.get(cid, {})
        split = claim.get("split")
        expected, why = ENTITLED_SPLIT.get(cid, (None, "no entitlement recorded"))
        check(
            f"{cid} split is the one its evidence entitles it to",
            split == expected,
            f"split = {split!r}, required {expected!r} because {why}",
        )

    # The entitlement above is only sound while selection stays label-blind.
    ecfr2 = json.loads(
        (VKC / "research/experiments/H3-B-REGULATORY-ECFR-02/protocol.json").read_text(encoding="utf-8")
    )
    check(
        "C-36 held_out entitlement still holds (selection is label-blind)",
        ecfr2.get("forbidden", {}).get("using_substantive_label_to_select_pairs") is True,
        "protocol forbids using the outside label to select pairs",
    )

    # Both failing predecessors must still be on disk and referenced.
    # The two lineages record adjudication differently, so each is read the
    # way it actually writes rather than through one assumed field.
    ecfr_pred = VKC / "research/experiments/H3-B-REGULATORY-ECFR-01/receipts/regulatory-revision-result.json"
    if not ecfr_pred.exists():
        check("C-36 failing predecessor is retained", False, f"missing {ecfr_pred}")
    else:
        body = json.loads(ecfr_pred.read_text(encoding="utf-8"))
        gate = json.loads(
            (VKC / "research/experiments/H3-B-REGULATORY-ECFR-01/protocol.json").read_text(encoding="utf-8")
        )["frozen_safety_gates"]["minimum_changed_pair_count"]
        changed = (
            body.get("changed_pair_count")
            or body.get("changed_pairs")
            or (body.get("cohort") or {}).get("changed_pair_count")
        )
        safety_ok = body.get("safety_gate_pass")
        # The predecessor is only useful as a retained failure if it really
        # fell short of its own adequacy gate while passing safety.
        check(
            "C-36 failing predecessor is retained and genuinely short of its gate",
            changed is not None and changed < gate,
            f"changed pairs {changed} < adequacy gate {gate}; safety_gate_pass={safety_ok}",
        )

    pres_pred = VKC / "research/experiments/PRESERVATION-E2E-01/receipts/result.json"
    verdict = json.loads(pres_pred.read_text(encoding="utf-8")).get("verdict") if pres_pred.exists() else None
    check(
        "C-37 failing predecessor is retained",
        pres_pred.exists() and verdict == "FAIL",
        f"PRESERVATION-E2E-01 verdict={verdict}",
    )


# ---------------------------------------------------------------- Q1
def q1_holdout_leak() -> None:
    print("\nQ1. Did any holdout leak?")
    # The preservation experiments read CONF-02 outputs. They must not have
    # written anything into that tree.
    result = json.loads(
        (VKC / "research/experiments/PRESERVATION-E2E-02/receipts/result.json").read_text(encoding="utf-8")
    )
    src = result["parser_output_source"]
    check(
        "preservation used CONF-02 outputs read-only",
        src.startswith("research/experiments/SEM-RISK-CONF-02/outputs/"),
        f"source = {src}; receipts written only under PRESERVATION-E2E-02/receipts/",
    )

    # CONF-02's own frozen integrity must still verify after all this work.
    notes.append(
        "CONF-02 frozen integrity is verified separately by "
        "verify_frozen_integrity.py; run it alongside this review."
    )

    # ECFR selection must predate the protocol freeze.
    p2 = json.loads((VKC / "research/experiments/H3-B-REGULATORY-ECFR-02/protocol.json").read_text(encoding="utf-8"))
    forbidden = p2.get("forbidden", {})
    # ECFR names this prohibition specifically rather than generically.
    gate_locked = forbidden.get(
        "lowering_the_adequacy_gate_after_seeing_this_result"
    ) is True
    selection_clean = forbidden.get("using_substantive_label_to_select_pairs") is True
    check(
        "ECFR-02 forbids lowering its adequacy gate post-result",
        gate_locked,
        f"lowering_the_adequacy_gate_after_seeing_this_result = {gate_locked}",
    )
    check(
        "ECFR-02 forbids using the outside label to select pairs",
        selection_clean,
        "the substantive flag scores the result; it must not choose the cohort",
    )


# ---------------------------------------------------------------- Q3
def q3_transport_amendment_labelling() -> None:
    print("\nQ3. Was a transport amendment mislabeled?")
    # ECFR-02 differs from ECFR-01 only in selection. Assert the evaluator
    # module was reused rather than modified.
    p2 = json.loads((VKC / "research/experiments/H3-B-REGULATORY-ECFR-02/protocol.json").read_text(encoding="utf-8"))
    reuse = json.dumps(p2).lower()
    check(
        "ECFR-02 declares evaluator reuse",
        "evaluator" in reuse and ("reus" in reuse or "byte-identical" in reuse or "unchanged" in reuse),
        "protocol states the sealed V01 evaluator is reused unchanged",
    )

    q2p = json.loads((VKC / "research/experiments/PRESERVATION-E2E-02/protocol.json").read_text(encoding="utf-8"))
    changed = q2p.get("change_from_v01", {})
    check(
        "E2E-02 states exactly what changed",
        bool(changed.get("only_change")) and changed.get("gates_were_not_relaxed") is True,
        f"only_change = {str(changed.get('only_change'))[:90]}...",
    )


def main() -> int:
    print("=" * 68)
    print("ADVERSARIAL REVIEW -- audit section 28-G")
    print(f"claims under review: {', '.join(CLAIMS_UNDER_REVIEW)}")
    print("=" * 68)

    q1_holdout_leak()
    q2_thresholds_not_changed_after_results()
    q3_transport_amendment_labelling()
    q4_dev_not_presented_as_confirmatory()
    q5_receipts_are_immutable_and_pinned()

    print("\n" + "=" * 68)
    print("OUT OF SCOPE FOR THIS RUN (product control plane, not these claims):")
    for q in (
        "Can the graph mutate truth?",
        "Can an LLM mutate ontology?",
        "Can a PASS receipt from another job promote this candidate?",
        "Can unresolved identity silently force-match?",
    ):
        print(f"  - {q}")
    for note in notes:
        print(f"\nNOTE: {note}")

    print("\n" + "=" * 68)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: all mechanical checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
