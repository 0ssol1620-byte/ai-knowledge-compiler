"""Controls for the Historical-Dependency Isolation Gate.

The founder ruling preserves fifty-nine drifted frozen attestations as evidence
of a reproducibility chain that failed, and requires SFIR9 to be a new chain
that does not stand on them. "Does not stand on them" is a promise until
something checks it, so these controls check the checker.

Two failure directions matter equally and are both tested. The gate must refuse
a declaration that leans on the failed chain -- a drifted receipt as a
prerequisite, a historical expected digest certifying current source, a `latest`
lookup choosing an authority. And it must *not* refuse merely because a file
appears in the drift list: current bytes may be newly frozen for SFIR9, and a
gate that forbade that would make the failed chain permanently contagious.

The drift receipt itself is read here and never written. A control that repaired
it to make a test pass would destroy the record the ruling exists to preserve.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_isolation_gate as gate  # noqa: E402

DRIFTED_PATH = "research/tavonel_eval_v2/tools/root_identity.py"
DRIFTED_EXPECTED = "sha256:650766c4b6267b89ba8b730fbae90c134bc5240c458a19362b63d0747c61ab9d"
DRIFTED_RECEIPT = "sfi3-suite-evidence--20260826T111605Z-4f1a1e6ee0d9.json"


@pytest.fixture
def drift_receipt(tmp_path):
    body = {
        "frozen_drift": [
            {
                "class": "FROZEN",
                "path": DRIFTED_PATH,
                "expected": DRIFTED_EXPECTED,
                "worktree": "sha256:0d172324371fe5be38ba7c9e2617597f3fa9df938f01122799"
                "cd1ab2eeb8fa9c",
                "receipt": DRIFTED_RECEIPT,
            }
        ]
        * 59,
        "advisory_drift": [
            {
                "class": "ADVISORY",
                "path": "research/tavonel_eval_v2/tools/other.py",
                "expected": "sha256:" + "a" * 64,
                "worktree": "sha256:" + "b" * 64,
                "receipt": "some-advisory-receipt.json",
            }
        ]
        * 126,
        "does_not_repin": "reported, not repaired",
    }
    path = tmp_path / "frozen-instrument-integrity.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


@pytest.fixture
def components(tmp_path):
    """Eight clean SFIR9 components on disk."""
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    paths = {}
    for name in gate.REQUIRED_COMPONENTS:
        relative = f"tools/sfir9_{name}.py"
        (root / relative).write_text(
            f'"""SFIR9 {name}."""\nVALUE = "{name}"\n', encoding="utf-8"
        )
        paths[name] = relative
    return root, paths


def declaration(paths, **overrides):
    body = dict(
        components=dict(paths),
        historical_inputs=[],
        scientific_prerequisites=[],
        source_digests={},
        claims_continuity_with_historical_pin=False,
    )
    body.update(overrides)
    return gate.Sfir9Declaration(**body)


# ------------------------------------------------------------ it reads, never writes


def test_the_drift_receipt_is_read_and_its_digest_recorded(drift_receipt):
    before = drift_receipt.read_bytes()
    record = gate.read_drift(drift_receipt)

    assert record.frozen_drift_count == 59
    assert record.advisory_drift_count == 126
    assert record.receipt_sha256 == "sha256:" + hashlib.sha256(before).hexdigest()
    assert drift_receipt.read_bytes() == before, "the gate modified the drift receipt"


def test_the_gate_never_writes_to_the_drift_receipt(drift_receipt, components):
    root, paths = components
    before = drift_receipt.read_bytes()
    gate.evaluate(declaration(paths), gate.read_drift(drift_receipt), root=root)
    assert drift_receipt.read_bytes() == before


# ---------------------------------------------------- the two states stay separate


def test_both_integrity_states_are_reported_side_by_side(drift_receipt, components):
    root, paths = components
    proof = gate.evaluate(declaration(paths), gate.read_drift(drift_receipt), root=root)

    historical = proof["HISTORICAL_INSTRUMENT_INTEGRITY"]
    assert historical["state"] == "FAIL"
    assert historical["historical_frozen_drift_count"] == 59
    assert historical["historical_status"] == "PRESERVED_FAIL"
    assert historical["preserved"] is True

    prospective = proof["SFIR9_PROSPECTIVE_INTEGRITY"]
    assert prospective["state"] == "INDEPENDENTLY_EVALUATED"
    assert prospective["sfir9_historical_authority_dependencies"] == []


def test_a_historical_fail_does_not_block_a_clean_declaration(drift_receipt, components):
    """The ruling's first requirement: historical FAIL is not an SFIR9 blocker."""
    root, paths = components
    proof = gate.evaluate(declaration(paths), gate.read_drift(drift_receipt), root=root)
    assert proof["SFIR9_PROSPECTIVE_INTEGRITY"]["state"] == "INDEPENDENTLY_EVALUATED"


def test_the_proof_says_the_two_states_are_not_merged(drift_receipt, components):
    root, paths = components
    proof = gate.evaluate(declaration(paths), gate.read_drift(drift_receipt), root=root)
    text = proof["the_two_states_are_not_merged"].casefold()
    assert "does not block" in text
    assert "does not repair" in text


def test_the_proof_states_what_the_static_scan_cannot_establish(
    drift_receipt, components
):
    """A control that overstates itself is worse than none."""
    root, paths = components
    proof = gate.evaluate(declaration(paths), gate.read_drift(drift_receipt), root=root)
    limitation = proof["what_this_gate_does_not_establish"].casefold()
    assert "static" in limitation
    assert "cannot prove" in limitation


# ------------------------------------------------------------------ the refusals


def test_a_drifted_receipt_as_a_scientific_prerequisite_is_refused(
    drift_receipt, components
):
    root, paths = components
    with pytest.raises(gate.IsolationRefused, match=gate.REFUSAL):
        gate.evaluate(
            declaration(paths, scientific_prerequisites=[DRIFTED_RECEIPT]),
            gate.read_drift(drift_receipt),
            root=root,
        )


def test_a_drifted_path_as_a_scientific_prerequisite_is_refused(
    drift_receipt, components
):
    root, paths = components
    with pytest.raises(gate.IsolationRefused, match="proven freshly"):
        gate.evaluate(
            declaration(paths, scientific_prerequisites=[DRIFTED_PATH]),
            gate.read_drift(drift_receipt),
            root=root,
        )


def test_an_undrifted_receipt_as_a_prerequisite_is_allowed(drift_receipt, components):
    """The refusal must be about drift, not about being historical-shaped."""
    root, paths = components
    proof = gate.evaluate(
        declaration(paths, scientific_prerequisites=["sfir9-own-freeze.json"]),
        gate.read_drift(drift_receipt),
        root=root,
    )
    assert proof["SFIR9_PROSPECTIVE_INTEGRITY"]["state"] == "INDEPENDENTLY_EVALUATED"


def test_certifying_current_source_with_a_historical_expected_digest_is_refused(
    drift_receipt, components
):
    """How a chain claims a continuity it does not have."""
    root, paths = components
    with pytest.raises(gate.IsolationRefused, match="historical pin"):
        gate.evaluate(
            declaration(paths, source_digests={"tools/x.py": DRIFTED_EXPECTED}),
            gate.read_drift(drift_receipt),
            root=root,
        )


def test_the_historical_digest_is_recognised_without_its_prefix(
    drift_receipt, components
):
    """A bare hex digest is the same claim wearing fewer characters."""
    root, paths = components
    bare = DRIFTED_EXPECTED.removeprefix("sha256:")
    with pytest.raises(gate.IsolationRefused, match="historical pin"):
        gate.evaluate(
            declaration(paths, source_digests={"tools/x.py": bare}),
            gate.read_drift(drift_receipt),
            root=root,
        )


def test_a_freshly_computed_digest_for_the_same_path_is_allowed(
    drift_receipt, components
):
    """Ruling section 3: current bytes may be newly frozen for SFIR9.

    A gate that refused this would make the failed chain permanently contagious
    -- every file it ever touched unusable forever, however sound its current
    implementation.
    """
    root, paths = components
    proof = gate.evaluate(
        declaration(paths, source_digests={DRIFTED_PATH: "sha256:" + "0d17" * 16}),
        gate.read_drift(drift_receipt),
        root=root,
    )
    assert proof["SFIR9_PROSPECTIVE_INTEGRITY"]["sfir9_source_hashes"][DRIFTED_PATH]


def test_claiming_continuity_with_a_historical_pin_is_refused(
    drift_receipt, components
):
    """"The current implementation newly frozen for SFIR9", never "restored"."""
    root, paths = components
    with pytest.raises(gate.IsolationRefused, match="newly frozen"):
        gate.evaluate(
            declaration(paths, claims_continuity_with_historical_pin=True),
            gate.read_drift(drift_receipt),
            root=root,
        )


# ------------------------------------------------- non-deterministic authority


@pytest.mark.parametrize(
    "snippet,description",
    [
        ("for p in root.glob('*.json'): pass", "glob"),
        ("for p in root.rglob('*.json'): pass", "recursive glob"),
        ("newest = max(paths, key=lambda p: p.stat().st_mtime)", "mtime"),
        ("path = receipts / 'latest'", "latest pointer"),
    ],
)
def test_selecting_an_authority_by_recency_or_shape_is_refused(
    drift_receipt, components, snippet, description
):
    root, paths = components
    (root / paths["scorer"]).write_text(f"X = 1\n{snippet}\n", encoding="utf-8")
    with pytest.raises(gate.IsolationRefused, match="recency or shape"):
        gate.evaluate(declaration(paths), gate.read_drift(drift_receipt), root=root)


def test_the_refusal_names_the_component_and_the_lookup(drift_receipt, components):
    root, paths = components
    (root / paths["cohort_roster"]).write_text(
        "for p in root.rglob('*.json'): pass\n", encoding="utf-8"
    )
    with pytest.raises(gate.IsolationRefused) as caught:
        gate.evaluate(declaration(paths), gate.read_drift(drift_receipt), root=root)
    assert "cohort_roster" in str(caught.value)
    assert "recursive glob" in str(caught.value)


# ------------------------------------------------------ historical inputs, declared


def allowed_input(**overrides):
    body = dict(
        path=DRIFTED_PATH,
        sha256="sha256:" + "0" * 64,
        purpose="spent_identity_exclusion",
        why_not_scientific_authority=(
            "read only to exclude SFIR7's fifty spent development roots from the "
            "fresh holdout. It removes candidates from consideration and cannot add "
            "or certify one."
        ),
        value_bearing=False,
    )
    body.update(overrides)
    return gate.HistoricalInput(**body)


def test_a_properly_declared_historical_input_is_allowed(drift_receipt, components):
    root, paths = components
    proof = gate.evaluate(
        declaration(paths, historical_inputs=[allowed_input()]),
        gate.read_drift(drift_receipt),
        root=root,
    )
    recorded = proof["SFIR9_PROSPECTIVE_INTEGRITY"]["historical_inputs"][0]
    assert recorded["value_bearing"] is False
    assert recorded["purpose"] == "spent_identity_exclusion"
    assert recorded["why_not_scientific_authority"]


def test_a_value_bearing_historical_input_is_refused(drift_receipt, components):
    root, paths = components
    with pytest.raises(gate.IsolationRefused, match="may not bear value"):
        gate.evaluate(
            declaration(paths, historical_inputs=[allowed_input(value_bearing=True)]),
            gate.read_drift(drift_receipt),
            root=root,
        )


def test_a_historical_input_with_an_undeclared_purpose_is_refused(
    drift_receipt, components
):
    root, paths = components
    with pytest.raises(gate.IsolationRefused, match="not one of"):
        gate.evaluate(
            declaration(
                paths, historical_inputs=[allowed_input(purpose="cohort_authority")]
            ),
            gate.read_drift(drift_receipt),
            root=root,
        )


@pytest.mark.parametrize("purpose", sorted(gate.ALLOWED_HISTORICAL_PURPOSES))
def test_each_allowed_purpose_is_accepted(drift_receipt, components, purpose):
    root, paths = components
    gate.evaluate(
        declaration(paths, historical_inputs=[allowed_input(purpose=purpose)]),
        gate.read_drift(drift_receipt),
        root=root,
    )


def test_a_historical_input_without_a_reason_is_refused(drift_receipt, components):
    """An unexplained exemption is the shape every later exemption copies."""
    root, paths = components
    with pytest.raises(gate.IsolationRefused, match="why it is not"):
        gate.evaluate(
            declaration(
                paths, historical_inputs=[allowed_input(why_not_scientific_authority="  ")]
            ),
            gate.read_drift(drift_receipt),
            root=root,
        )


def test_a_historical_input_without_a_digest_is_refused(drift_receipt, components):
    root, paths = components
    with pytest.raises(gate.IsolationRefused, match="not recoverable"):
        gate.evaluate(
            declaration(paths, historical_inputs=[allowed_input(sha256="unknown")]),
            gate.read_drift(drift_receipt),
            root=root,
        )


# ------------------------------------------------------------ every component seen


@pytest.mark.parametrize("missing", gate.REQUIRED_COMPONENTS)
def test_an_undeclared_component_is_refused(drift_receipt, components, missing):
    """A component the gate never sees is one whose dependencies were never checked."""
    root, paths = components
    incomplete = {k: v for k, v in paths.items() if k != missing}
    with pytest.raises(gate.IsolationRefused, match=missing):
        gate.evaluate(
            declaration(paths, components=incomplete),
            gate.read_drift(drift_receipt),
            root=root,
        )


def test_a_component_that_is_not_a_file_is_refused(drift_receipt, components):
    root, paths = components
    with pytest.raises(gate.IsolationRefused, match="not a file"):
        gate.evaluate(
            declaration(paths, components={**paths, "scorer": "tools/absent.py"}),
            gate.read_drift(drift_receipt),
            root=root,
        )


def test_the_required_components_are_the_eight_the_ruling_names():
    assert set(gate.REQUIRED_COMPONENTS) == {
        "protocol",
        "execution_closure",
        "scorer",
        "acceptance",
        "cohort_roster",
        "transport",
        "identity_logic",
        "checkpoint_chain",
    }


def test_every_refusal_carries_the_declared_refusal_code(drift_receipt, components):
    root, paths = components
    with pytest.raises(gate.IsolationRefused) as caught:
        gate.evaluate(
            declaration(paths, claims_continuity_with_historical_pin=True),
            gate.read_drift(drift_receipt),
            root=root,
        )
    assert str(caught.value).startswith(gate.REFUSAL)


# ------------------------------------------------- against the receipt on disk


def test_the_real_receipt_reports_the_drift_the_ruling_names():
    """Bound to the actual preserved evidence, not only to a fixture.

    If the real receipt ever stops reporting 59 frozen drifts, either it was
    repaired -- which the ruling forbids -- or the gate is reading the wrong
    file. Either way this must fail rather than quietly pass.
    """
    receipt = NS / "receipts/frozen-instrument-integrity.json"
    record = gate.read_drift(receipt)
    assert record.frozen_drift_count == 59
    assert record.advisory_drift_count == 126
    assert DRIFTED_PATH in record.affected_paths
    assert DRIFTED_EXPECTED in record.expected_digests
    assert record.as_dict()["historical_status"] == "PRESERVED_FAIL"


def test_an_advisory_drifted_receipt_is_also_refused_as_authority(
    drift_receipt, components
):
    """Advisory drift is still drift.

    Mutation G24 stopped counting advisory entries as affected and survived,
    because every other control reached for a FROZEN one. The distinction
    between the two classes is about how the historical chain classified the
    breakage, not about whether the bytes moved -- and an attestation whose
    bytes moved cannot certify anything for SFIR9 whichever list it sits in.
    """
    root, paths = components
    with pytest.raises(gate.IsolationRefused, match="proven freshly"):
        gate.evaluate(
            declaration(
                paths,
                scientific_prerequisites=["research/tavonel_eval_v2/tools/other.py"],
            ),
            gate.read_drift(drift_receipt),
            root=root,
        )


def test_an_advisory_expected_digest_may_not_certify_current_source(
    drift_receipt, components
):
    root, paths = components
    with pytest.raises(gate.IsolationRefused, match="historical pin"):
        gate.evaluate(
            declaration(paths, source_digests={"tools/x.py": "sha256:" + "a" * 64}),
            gate.read_drift(drift_receipt),
            root=root,
        )


def test_the_advisory_count_is_reported_separately_from_the_frozen_count(
    drift_receipt, components
):
    """Counted together for authority, reported apart so neither hides the other."""
    root, paths = components
    proof = gate.evaluate(declaration(paths), gate.read_drift(drift_receipt), root=root)
    historical = proof["HISTORICAL_INSTRUMENT_INTEGRITY"]
    assert historical["historical_frozen_drift_count"] == 59
    assert historical["historical_advisory_drift_count"] == 126
