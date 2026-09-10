"""WP-R10 replay invariants, on synthetic data where possible.

The one that matters most is structural: the runtime-visible half must be
UNABLE to open hidden evaluation truth. Everything else is arithmetic that has
to hold whatever the arena says.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

LANE = Path(__file__).resolve().parents[1]
for _path in (LANE, LANE.parent / "router_oracle_20260908"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import features as F  # noqa: E402
import layout_visible as L  # noqa: E402
import native_visible as N  # noqa: E402
import replay as R  # noqa: E402
import scorer as S  # noqa: E402

# ---------------------------------------------------------------------------
# leakage: structural, not by convention
# ---------------------------------------------------------------------------

HIDDEN_PATHS = [
    F.DEFAULT_ARENA_ROOT / "reports" / "full_compare_20260905" / "omnidoc_raw" / "x.json",
    F.DEFAULT_ARENA_ROOT / "reports" / "full_compare_20260905" / "olmocr_raw" / "x.json",
    F.DEFAULT_ARENA_ROOT / "scores" / "ovisocr2" / "omnidoc" / "x.json",
    F.DEFAULT_ARENA_ROOT / "evidence" / "x.json",
    F.DEFAULT_ARENA_ROOT / "receipts" / "x.json",
    F.DEFAULT_SOURCE_ROOT / "omnidocbench" / "OmniDocBench.json",
    F.DEFAULT_SOURCE_ROOT / "parsebench" / "table.jsonl",
    F.DEFAULT_SOURCE_ROOT / "olmocr-bench" / "bench_data" / "old_scans.jsonl",
]


@pytest.mark.parametrize("path", HIDDEN_PATHS, ids=lambda p: p.name)
def test_runtime_half_cannot_open_a_hidden_path(path: Path) -> None:
    with pytest.raises(F.LeakageRefusal):
        F.assert_visible(path)


@pytest.mark.parametrize(
    "path",
    [
        F.DEFAULT_ARENA_ROOT / "source_manifest.jsonl",
        F.DEFAULT_ARENA_ROOT / "frozen_outputs" / "ovisocr2" / "manifest.jsonl",
        F.DEFAULT_ARENA_ROOT / "runs" / "ovisocr2" / "canonical" / "x.md",
        F.DEFAULT_ARENA_ROOT / "runs" / "ovisocr2" / "receipts" / "x.json",
        F.DEFAULT_ARENA_ROOT / "cost" / "campaign-cost.json",
        F.DEFAULT_SOURCE_ROOT / "omnidocbench" / "images" / "x.png",
        F.DEFAULT_SOURCE_ROOT / "parsebench" / "docs" / "table" / "x.pdf",
    ],
    ids=lambda p: p.name,
)
def test_runtime_half_can_open_the_allow_listed_paths(path: Path) -> None:
    assert F.assert_visible(path) == path.resolve()


def test_a_parent_directory_traversal_is_refused() -> None:
    escape = F.DEFAULT_ARENA_ROOT / "runs" / ".." / "scores" / "leak.json"
    with pytest.raises(F.LeakageRefusal):
        F.assert_visible(escape)


def test_features_module_never_imports_the_scorer() -> None:
    """The split is enforced on the import graph, not by a comment."""
    tree = ast.parse((LANE / "features.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "scorer" not in imported
    assert "oracle" not in imported  # oracle.py opens the score files


def test_no_hidden_path_constant_appears_in_the_runtime_half() -> None:
    """No hidden path may be spelled anywhere in the code (docstrings aside)."""
    tree = ast.parse((LANE / "features.py").read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        for forbidden in ("full_compare", "OmniDocBench", "_raw", "scores"):
            assert forbidden not in node.value, (forbidden, node.value[:80])


def test_every_replay_record_declares_hidden_truth_invisible() -> None:
    from akc_router.execution_plan import RouterReplayRecord

    unit = make_unit(texts={F.PRIMARY_MODEL: "x", F.PEER_MODEL: "y", "s": "z"})
    for arm in (
        F.FixedModel(model=F.PRIMARY_MODEL),
        F.Escalating(trigger="disagreement", strong="s"),
        F.CoreRouter(),
        F.AlwaysAllReconciled(models=(F.PRIMARY_MODEL, F.PEER_MODEL)),
        F.ReplayComposite(strong="s"),
    ):
        record = R.to_replay_record(arm.name, unit, arm.plan(unit))
        assert isinstance(record, RouterReplayRecord)
        assert record.hidden_evaluation_visible_to_runtime is False
        assert record.final_disposition in {"accepted", "unresolved"}


def test_a_replay_record_refuses_to_say_the_runtime_saw_hidden_truth() -> None:
    from akc_router.execution_plan import RouterReplayRecord, VerificationPolicy

    with pytest.raises(ValueError, match="hidden_evaluation_visible_to_runtime"):
        RouterReplayRecord(
            unit_id="u1",
            features_revision="f",
            router_revision="r",
            allowed_routes=(),
            selected_plan="p",
            verification=VerificationPolicy.NONE,
            final_disposition="accepted",
            hidden_evaluation_visible_to_runtime=True,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# arms
# ---------------------------------------------------------------------------


def make_unit(
    unit: str = "u1",
    *,
    texts: dict[str, str] | None = None,
    blind: dict[str, float] | None = None,
    critical: float = 0.0,
    native_chars: int = 0,
    media_type: str = "image",
) -> F.UnitFeatures:
    texts = texts or {}
    outputs = {
        model: F.OutputFeatures(
            model=model,
            status="SUCCESS",
            present=True,
            chars=len(body),
            words=len(body.split()),
            lines=1,
            table_rows=0,
            replacement_ratio=0.0,
            control_ratio=0.0,
            inference_ms=1000.0,
            queue_ms=0.0,
            load_ms=None,
            peak_vram_mb=None,
        )
        for model, body in texts.items()
    }
    from reconciler import normalize, select, similarity

    sets = {model: normalize(body) for model, body in texts.items()}
    keys = sorted(sets)
    sims = {
        f"{a}|{b}": similarity(sets[a], sets[b])
        for i, a in enumerate(keys)
        for b in keys[i + 1 :]
    }
    return F.UnitFeatures(
        case_key=unit,
        benchmark="omnidoc",
        unit_key=unit,
        media_type=media_type,
        input_bytes=1,
        width=100,
        height=100,
        page_index=0,
        render_edge_density=0.1,
        render_mean_intensity=200.0,
        render_near_white_ratio=0.5,
        render_entropy=2.0,
        render_probably_blank=False,
        native_text_chars=native_chars,
        native_word_count=native_chars // 5,
        native_invalid_unicode_ratio=0.0,
        native_replacement_ratio=0.0,
        native_text_available=native_chars > 0,
        outputs=outputs,
        similarity=sims,
        reconciler_choice=select(sets) if sets else "__UNRESOLVED__",
        critical_token_risk=critical,
        critical_token_kinds=(),
        blind_risk=blind or {},
        unknown_fields=F.UNKNOWN_PAGE_METRIC_FIELDS,
    )


def test_a_missing_output_is_unresolved_never_a_substitute() -> None:
    unit = make_unit(texts={"other": "hello world"})
    plan = F.FixedModel(model=F.PRIMARY_MODEL).plan(unit)
    assert plan.accepted is None
    assert plan.unresolved_reason


def test_disagreement_arm_escalates_only_below_the_frozen_tau() -> None:
    same = make_unit(texts={F.PRIMARY_MODEL: "a b c d", F.PEER_MODEL: "a b c d", "s": "z"})
    different = make_unit(texts={F.PRIMARY_MODEL: "a b c d", F.PEER_MODEL: "q r s t", "s": "z"})
    arm = F.Escalating(trigger="disagreement", strong="s")
    assert arm.plan(same).escalate is False
    assert arm.plan(different).escalate is True
    assert arm.plan(different).accepted == "s"


def test_prediction_arm_uses_the_frozen_threshold_only() -> None:
    low = make_unit(texts={F.PRIMARY_MODEL: "x", "s": "y"}, blind={F.PRIMARY_MODEL: 0.1})
    high = make_unit(texts={F.PRIMARY_MODEL: "x", "s": "y"}, blind={F.PRIMARY_MODEL: 0.9})
    arm = F.Escalating(trigger="prediction", strong="s")
    assert arm.plan(low).escalate is False
    assert arm.plan(high).escalate is True


def test_peer_agreement_verifier_accepts_a_corroborated_output() -> None:
    unit = make_unit(
        texts={
            "native": "alpha beta gamma delta",
            F.PRIMARY_MODEL: "alpha beta gamma delta",
            F.PEER_MODEL: "unrelated visual output",
        }
    )
    plan = F.PeerAgreementVerified(
        models=("native", F.PRIMARY_MODEL, F.PEER_MODEL)
    ).plan(unit)
    assert plan.accepted in {"native", F.PRIMARY_MODEL}
    assert plan.unresolved_reason is None
    assert plan.reason_codes == ("PEER_AGREEMENT_ESTABLISHED",)


def test_peer_agreement_verifier_can_use_two_surviving_routes() -> None:
    unit = make_unit(
        texts={
            F.PRIMARY_MODEL: "alpha beta gamma delta",
            F.PEER_MODEL: "alpha beta gamma delta",
        }
    )
    plan = F.PeerAgreementVerified(
        models=("native", F.PRIMARY_MODEL, F.PEER_MODEL)
    ).plan(unit)
    assert plan.accepted in {F.PRIMARY_MODEL, F.PEER_MODEL}
    assert plan.routes == ("native", F.PRIMARY_MODEL, F.PEER_MODEL)


def test_peer_agreement_verifier_refuses_uncorroborated_outputs() -> None:
    unit = make_unit(
        texts={
            "native": "alpha beta gamma",
            F.PRIMARY_MODEL: "one two three",
            F.PEER_MODEL: "red green blue",
        }
    )
    plan = F.PeerAgreementVerified(
        models=("native", F.PRIMARY_MODEL, F.PEER_MODEL)
    ).plan(unit)
    assert plan.accepted is None
    assert plan.escalate is True
    assert plan.reason_codes == ("PEER_AGREEMENT_NOT_ESTABLISHED",)


def test_peer_agreement_verifier_is_fully_declared_in_the_policy_freeze() -> None:
    freeze = F.frozen_policy_parameters()
    verifier = freeze["peer_agreement_verifier_v2"]
    assert verifier["models"] == ["native", F.PRIMARY_MODEL, F.PEER_MODEL]
    assert "UNRESOLVED" in verifier["acceptance_rule"]


def test_source_layout_authority_policy_refuses_unscored_authority() -> None:
    unit = replace(
        make_unit(texts={"mineru_vlm": "x", "olmocr2": "x"}),
        authority_domain="sec",
        authority_available=True,
    )
    plan = F.SourceLayoutAuthorityVerified().plan(unit)
    assert plan.accepted is None
    assert plan.routes == ()
    assert plan.reason_codes == ("AUTHORITY_ARM_UNMEASURED",)


def test_source_layout_authority_policy_treats_unknown_layout_as_high_risk() -> None:
    unit = make_unit(
        texts={"mineru_vlm": "alpha beta gamma", "olmocr2": "alpha beta gamma"}
    )
    plan = F.SourceLayoutAuthorityVerified().plan(unit)
    assert plan.accepted == "mineru_vlm"
    assert plan.routes == ("mineru_vlm", "olmocr2")
    assert "layout:unknown_conservative" in plan.reason_codes


def test_source_layout_authority_policy_uses_independent_verifier_to_overturn() -> None:
    unit = make_unit(
        texts={
            "mineru_vlm": "layout candidate unrelated",
            "olmocr2": "alpha beta gamma delta",
            F.PRIMARY_MODEL: "alpha beta gamma delta",
        }
    )
    plan = F.SourceLayoutAuthorityVerified().plan(unit)
    assert plan.accepted == "olmocr2"
    assert plan.routes == ("mineru_vlm", "olmocr2", F.PRIMARY_MODEL)
    assert "INDEPENDENT_VERIFICATION_ESTABLISHED" in plan.reason_codes


def test_source_layout_authority_policy_refuses_three_way_disagreement() -> None:
    unit = make_unit(
        texts={
            "mineru_vlm": "layout candidate",
            "olmocr2": "text candidate",
            F.PRIMARY_MODEL: "third opinion",
        }
    )
    plan = F.SourceLayoutAuthorityVerified().plan(unit)
    assert plan.accepted is None
    assert plan.unresolved_reason == "independent verifier corroborated no candidate"


def test_source_layout_authority_policy_and_builder_are_frozen() -> None:
    freeze = F.frozen_policy_parameters()
    policy = freeze["source_layout_authority_verifier_v1"]
    assert policy["authority_rule"].startswith("UNRESOLVED")
    assert policy["agreement_tau"] == F.AGREEMENT_TAU
    measured = freeze["source_layout_authority_verifier_v2"]
    assert measured["native_limits"]["minimum_locator_coverage"] == 0.99
    assert measured["layout_probe"]["table_line_density_tau"] == 0.02
    override = freeze["selective_peer_override_verifier_v1"]
    assert override["primary_model"] == "mineru_vlm"
    assert override["agreement_tau"] == F.AGREEMENT_TAU
    token_guard = freeze["native_critical_token_guard_v1"]
    assert token_guard["native_limits"]["minimum_locator_coverage"] == 0.99
    assert token_guard["primary_model"] == "mineru_vlm"
    assert F.FEATURE_BUILDER_ID.endswith("V3")
    assert "native_reading_order_score" in F.UNKNOWN_PAGE_METRIC_FIELDS


def test_measured_layout_policy_routes_observed_low_layout_to_text() -> None:
    unit = replace(
        make_unit(
            texts={"mineru_vlm": "alpha beta", "olmocr2": "alpha beta"},
            media_type="pdf",
        ),
        layout_feature_status="measured",
        layout_column_count=1,
        layout_table_line_density=0.0,
        layout_ink_coverage=0.2,
    )
    plan = F.SourceLayoutAuthorityMeasured().plan(unit)
    assert plan.accepted == "olmocr2"
    assert plan.routes == ("olmocr2", "mineru_vlm")
    assert "authority:unmeasured" in plan.reason_codes
    assert "layout:observed_low" in plan.reason_codes


def test_measured_layout_policy_routes_observed_structure_to_layout() -> None:
    unit = replace(
        make_unit(
            texts={"mineru_vlm": "alpha beta", "olmocr2": "alpha beta"},
            media_type="pdf",
        ),
        layout_feature_status="measured",
        layout_column_count=2,
        layout_table_line_density=0.0,
        layout_ink_coverage=0.2,
    )
    plan = F.SourceLayoutAuthorityMeasured().plan(unit)
    assert plan.accepted == "mineru_vlm"
    assert plan.routes == ("mineru_vlm", "olmocr2")
    assert "layout:observed" in plan.reason_codes


def test_measured_layout_policy_uses_locator_coverage_for_native() -> None:
    unit = replace(
        make_unit(
            texts={
                "native": "alpha beta gamma",
                "mineru_vlm": "alpha beta gamma",
            },
            native_chars=500,
            media_type="pdf",
        ),
        native_locator_coverage=1.0,
        layout_feature_status="measured",
        layout_column_count=1,
        layout_table_line_density=0.0,
    )
    plan = F.SourceLayoutAuthorityMeasured().plan(unit)
    assert plan.accepted == "native"
    assert plan.routes == ("native", "mineru_vlm")
    assert "source:native_qualified" in plan.reason_codes


def test_selective_override_keeps_primary_on_direct_agreement() -> None:
    unit = make_unit(
        texts={"mineru_vlm": "alpha beta", "olmocr2": "alpha beta"}
    )
    plan = F.SelectivePeerOverrideVerified().plan(unit)
    assert plan.accepted == "mineru_vlm"
    assert plan.routes == ("mineru_vlm", "olmocr2")
    assert plan.reason_codes == ("PRIMARY_CHALLENGER_AGREEMENT",)


def test_selective_override_requires_exclusive_peer_corroboration() -> None:
    unit = make_unit(
        texts={
            "mineru_vlm": "layout candidate unrelated",
            "olmocr2": "alpha beta gamma delta",
            F.PRIMARY_MODEL: "alpha beta gamma delta",
        }
    )
    plan = F.SelectivePeerOverrideVerified().plan(unit)
    assert plan.accepted == "olmocr2"
    assert plan.routes == ("mineru_vlm", "olmocr2", F.PRIMARY_MODEL)
    assert plan.reason_codes == ("PEER_ONLY_CORROBORATED_OVERRIDE",)


def test_selective_override_retains_primary_without_false_verification() -> None:
    unit = make_unit(
        texts={
            "mineru_vlm": "layout candidate",
            "olmocr2": "text candidate",
            F.PRIMARY_MODEL: "third opinion",
        }
    )
    plan = F.SelectivePeerOverrideVerified().plan(unit)
    assert plan.accepted == "mineru_vlm"
    assert plan.reason_codes == ("PRIMARY_RETAINED_WITHOUT_CORROBORATION",)


def test_selective_override_does_not_substitute_uncorroborated_missing_primary() -> None:
    unit = make_unit(
        texts={"olmocr2": "text candidate", F.PRIMARY_MODEL: "third opinion"}
    )
    plan = F.SelectivePeerOverrideVerified().plan(unit)
    assert plan.accepted is None
    assert plan.reason_codes == ("MISSING_PRIMARY_NOT_SUBSTITUTED",)


def _token_guard_unit(primary: int, challenger: int) -> F.UnitFeatures:
    return replace(
        make_unit(
            texts={
                "native": "Revenue was USD 1,250 on 2026-09-10.",
                "mineru_vlm": "primary",
                "olmocr2": "challenger",
            },
            native_chars=500,
            media_type="pdf",
        ),
        native_locator_coverage=1.0,
        native_critical_mismatch_count={
            "mineru_vlm": primary,
            "olmocr2": challenger,
        },
        native_critical_max_risk={"mineru_vlm": 0.92, "olmocr2": 0.0},
    )


def test_native_token_guard_skips_challenger_when_primary_preserves_tokens() -> None:
    plan = F.NativeCriticalTokenGuard().plan(_token_guard_unit(0, 0))
    assert plan.accepted == "mineru_vlm"
    assert plan.routes == ("native", "mineru_vlm")
    assert not plan.escalate


def test_native_token_guard_overrides_only_for_zero_mismatch_challenger() -> None:
    plan = F.NativeCriticalTokenGuard().plan(_token_guard_unit(2, 0))
    assert plan.accepted == "olmocr2"
    assert plan.routes == ("native", "mineru_vlm", "olmocr2")
    assert plan.reason_codes == ("CHALLENGER_SOURCE_TOKENS_PRESERVED",)


def test_native_token_guard_strict_refuses_when_neither_candidate_passes() -> None:
    plan = F.NativeCriticalTokenGuard(strict=True).plan(_token_guard_unit(2, 1))
    assert plan.accepted is None
    assert plan.reason_codes == ("SOURCE_CRITICAL_TOKEN_VERIFICATION_FAILED",)


def test_native_token_guard_retains_baseline_with_review_reason() -> None:
    plan = F.NativeCriticalTokenGuard(strict=False).plan(_token_guard_unit(2, 1))
    assert plan.accepted == "mineru_vlm"
    assert plan.reason_codes == ("PRIMARY_RETAINED_TOKEN_REVIEW_REQUIRED",)


def test_native_token_guard_requires_locator_coverage() -> None:
    unit = replace(_token_guard_unit(2, 0), native_locator_coverage=0.98)
    plan = F.NativeCriticalTokenGuard().plan(unit)
    assert plan.accepted == "mineru_vlm"
    assert plan.routes == ("native", "mineru_vlm")
    assert plan.reason_codes == ("NATIVE_CRITICAL_REFERENCE_UNAVAILABLE",)


def test_layout_probe_measures_two_separated_columns(tmp_path: Path) -> None:
    image = Image.new("L", (400, 500), 255)
    pixels = image.load()
    assert pixels is not None
    for y in range(50, 450):
        for x in (*range(30, 160), *range(240, 370)):
            pixels[x, y] = 0
    path = tmp_path / "two-columns.png"
    image.save(path)
    measured = L.measure_image(path)
    assert measured["column_count"] >= 2
    assert 0 < measured["ink_coverage"] < 1


def test_layout_capture_binds_every_page_and_preserves_timing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(L, "EXPECTED_UNITS", 2)
    input_root = tmp_path / "inputs"
    staged = input_root / "olmocr-bench" / "inputs"
    staged.mkdir(parents=True)
    rows = []
    units = []
    for index in (1, 2):
        path = staged / f"case-{index}.png"
        Image.new("L", (200, 300), 255 - index).save(path)
        image_sha = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        source_sha = "sha256:" + str(index) * 64
        rows.append(
            {
                "benchmark": "olmocr",
                "case_key": f"case-{index}",
                "input_relative_path": f"olmocr-bench/inputs/case-{index}.png",
                "input_png_sha256": image_sha,
                "original_source_sha256": source_sha,
            }
        )
        units.append(
            replace(
                make_unit(unit=f"unit-{index}"),
                case_key=f"case-{index}",
                input_png_sha256=image_sha,
                original_source_sha256=source_sha,
            )
        )
    manifest = tmp_path / "source_manifest.jsonl"
    manifest.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    captured = L.capture(manifest, input_root, tmp_path / "capture")
    assert captured.coverage == {
        "layout_measured": 2,
        "layout_failed": 0,
        "authority_measured": 0,
    }
    assert captured.wall_ms["p95"] is not None
    augmented = L.augment_units(units, captured)
    assert all(unit.layout_feature_status == "measured" for unit in augmented)
    assert all(not unit.authority_checked for unit in augmented)
    assert all(unit.layout_feature_wall_ms is not None for unit in augmented)


def test_core_router_native_units_are_unresolved_not_substituted() -> None:
    """Route.NATIVE has no Arena arm. The absence is reported, never filled."""
    unit = make_unit(
        texts={F.PRIMARY_MODEL: "x"}, native_chars=5000, media_type="pdf"
    )
    plan = F.CoreRouter(reading_order_assumption=1.0).plan(unit)
    assert plan.accepted is None
    assert "native" in (plan.unresolved_reason or "")
    # the pessimistic end of the reading-order sweep routes visually instead
    visual = F.CoreRouter(reading_order_assumption=0.0).plan(unit)
    assert visual.accepted == F.PRIMARY_MODEL


def test_worker_sentinels_reproduce_the_c09_handwriting_defect() -> None:
    from akc_router.preflight import PageTechnicalClass, classify_page

    unit = make_unit(texts={F.PRIMARY_MODEL: "x"}, native_chars=3000, media_type="pdf")
    honest = F.page_metrics(unit, reading_order_assumption=1.0, worker_sentinels=False)
    sentinel = F.page_metrics(unit, reading_order_assumption=1.0, worker_sentinels=True)
    assert classify_page(sentinel) is PageTechnicalClass.HANDWRITTEN
    assert classify_page(honest) is not PageTechnicalClass.HANDWRITTEN


def test_reconciler_medoid_matches_the_frozen_rule_on_the_escalated_set() -> None:
    unit = make_unit(
        texts={
            F.PRIMARY_MODEL: "alpha beta gamma",
            F.PEER_MODEL: "alpha beta gamma delta",
            "s": "totally different words here",
        }
    )
    assert F._medoid_of(unit, (F.PRIMARY_MODEL, F.PEER_MODEL, "s")) in {
        F.PRIMARY_MODEL,
        F.PEER_MODEL,
    }


def test_ablation_flags_actually_change_the_decision() -> None:
    disagreeing = make_unit(
        texts={F.PRIMARY_MODEL: "a b c", F.PEER_MODEL: "q r s", "s": "z"},
        blind={F.PRIMARY_MODEL: 0.0},
    )
    assert F.ReplayComposite(strong="s").plan(disagreeing).escalate is True
    assert (
        F.ReplayComposite(strong="s", use_disagreement=False).plan(disagreeing).escalate
        is False
    )

    # prediction alone, with the peer corroborating: the cost objective is the
    # only thing standing between this unit and a paid strong call.
    corroborated = make_unit(
        texts={F.PRIMARY_MODEL: "a b c", F.PEER_MODEL: "a b c", "s": "z"},
        blind={F.PRIMARY_MODEL: 0.9},
    )
    assert F.ReplayComposite(strong="s").plan(corroborated).escalate is False
    assert (
        F.ReplayComposite(strong="s", use_cost_objective=False)
        .plan(corroborated)
        .escalate
        is True
    )
    assert (
        F.ReplayComposite(strong="s", use_prediction=False).plan(corroborated).escalate
        is False
    )


# ---------------------------------------------------------------------------
# scoring arithmetic
# ---------------------------------------------------------------------------


class _FakeSurface:
    def __init__(self, loss: dict[str, dict[str, float]]) -> None:
        self.loss = loss
        self.models = sorted(loss)
        self.cluster: dict[str, str] = {}
        self.page_class: dict[str, str] = {}

    def all_units(self) -> list[str]:
        units: set[str] = set()
        for per_unit in self.loss.values():
            units |= per_unit.keys()
        return sorted(units)


def test_a_missing_unit_scores_a_full_loss_and_is_never_dropped() -> None:
    surface = _FakeSurface({"a": {"u1": 0.1}, "b": {}})
    assert S.unit_loss(surface, "b", "u1") == 1.0


def test_the_oracle_is_never_worse_than_any_permitted_plan() -> None:
    surface = _FakeSurface({"a": {"u1": 0.4}, "b": {"u1": 0.2}})
    oracle = S.oracle_unit_loss(surface, "u1", ["a", "b"], "b")
    assert oracle <= min(0.4, 0.2)


def test_an_unresolved_reconciler_choice_is_a_full_loss_not_a_fallback() -> None:
    surface = _FakeSurface({"a": {"u1": 0.4}})
    assert S.oracle_unit_loss(surface, "u1", [], "__UNRESOLVED__") == 1.0


def test_hidden_critical_loss_counts_deletions_only() -> None:
    gt = "Revenue was 1,234.5 and -7 on 2024-01-02"
    complete = "Revenue was 1,234.5 and -7 on 2024-01-02"
    dropped = "Revenue was and -7 on 2024-01-02"
    inserted = complete + " plus an invented 999"
    assert S.hidden_critical_loss(gt, complete)[0] == 0
    assert S.hidden_critical_loss(gt, dropped)[0] >= 1
    assert S.hidden_critical_loss(gt, inserted)[0] == 0


def test_opportunity_counter_is_the_production_detector_s_own_counters() -> None:
    counts = S.count_opportunities("total 12 items, $3.00, on 2024-01-02, 5 kg")
    assert counts["number"] >= 3
    assert counts["currency"] >= 1
    assert counts["date"] == 1
    assert counts["unit"] >= 1
    assert counts["identifier"] == 0  # NOT_MEASURABLE, declared


def test_capture_bootstrap_reports_no_capture_when_there_is_no_headroom() -> None:
    surface = _FakeSurface({"a": {"u1": 0.2, "u2": 0.2}})
    surface.cluster = {"u1": "d1", "u2": "d2"}
    arms = {
        "SINGLE:a": {"u1": 0.2, "u2": 0.2},
        "ORACLE_DIAGNOSTIC": {"u1": 0.2, "u2": 0.2},
    }
    boot = R.capture_bootstrap(
        surface, arms, ["SINGLE:a"], "ORACLE_DIAGNOSTIC", ["u1", "u2"], replicates=50
    )
    assert boot["replicates_with_zero_headroom"] == 50
    assert boot["capture_ratio_point"]["SINGLE:a"] is None


def test_percentiles_say_unknown_rather_than_invent_a_latency() -> None:
    assert R._percentiles([], 10, 10)["basis"] == "UNKNOWN"
    assert R._percentiles([], 10, 10)["p95"] is None


def test_frozen_parameters_are_recorded_for_the_receipt() -> None:
    frozen = F.frozen_policy_parameters()
    assert frozen["agreement_tau"] == F.AGREEMENT_TAU
    assert frozen["route_to_arena_model"]["native"] is None
    assert set(frozen["strong_models"]) == set(F.STRONG_MODELS)


def test_native_visible_capture_is_hash_bound_and_augments_every_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(N, "EXPECTED_UNITS", 2)
    source_rows = [
        {
            "case_key": f"case-{index}",
            "sample_id": f"sample-{index}",
            "original_source_sha256": "sha256:" + str(index) * 64,
        }
        for index in (1, 2)
    ]
    freeze = {
        "confirmatory_eligible": False,
        "quality_verified": False,
        "hidden_evaluation_visible_to_runtime": False,
        "eligible_units": 2,
        "selected_units": 2,
        "source_manifest_sha256": "sha256:" + "a" * 64,
        "selected_source_rows": source_rows,
    }
    (tmp_path / "FREEZE.json").write_text(json.dumps(freeze), encoding="utf-8")
    observations = []
    for index, source in zip((1, 2), source_rows, strict=True):
        text = f"native text USD {index * 10}"
        observations.append(
            {
                "case_key": source["case_key"],
                "sample_id": source["sample_id"],
                "source_sha256": source["original_source_sha256"],
                "route": "native",
                "confirmatory_eligible": False,
                "quality_verified": False,
                "status": "native_text_observed",
                "text": text,
                "output_sha256": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                "local_wall_seconds": 0.01 * index,
            }
        )
    raw = "".join(json.dumps(row) + "\n" for row in observations).encode()
    (tmp_path / "observations.jsonl").write_bytes(raw)
    (tmp_path / "RESULT.json").write_text(
        json.dumps(
            {
                "selected": 2,
                "output_rows": 2,
                "observations_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    capture = N.load_capture(tmp_path)
    model_texts = {
        ("mineru_vlm", "unit-1"): "native text USD 10",
        ("mineru_vlm", "unit-2"): "native text USD 99",
    }
    units = [
        replace(
            make_unit(
                unit=f"unit-{index}",
                texts={"mineru_vlm": model_texts[("mineru_vlm", f"unit-{index}")]},
            ),
            case_key=f"case-{index}",
        )
        for index in (1, 2)
    ]
    augmented, texts = N.augment_units(units, model_texts, capture)
    assert [unit.outputs["native"].present for unit in augmented] == [True, True]
    assert texts[("native", "unit-1")] == "native text USD 10"
    assert augmented[0].native_critical_mismatch_count == {"mineru_vlm": 0}
    assert augmented[1].native_critical_mismatch_count == {"mineru_vlm": 2}
    assert capture.binding["units"] == 2


def test_native_hidden_scores_extend_only_the_exact_page_denominator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(S, "NATIVE_EXPECTED_UNITS", 2)
    monkeypatch.setattr(S, "NATIVE_EXPECTED_RULES", 3)
    rows = [
        {
            "test_id": "r1",
            "pdf": "u1",
            "type": "text",
            "passed": True,
            "evaluator_error": None,
        },
        {
            "test_id": "r2",
            "pdf": "u1",
            "type": "text",
            "passed": False,
            "evaluator_error": None,
        },
        {
            "test_id": "r3",
            "pdf": "u2",
            "type": "table",
            "passed": False,
            "evaluator_error": None,
        },
    ]
    raw = "".join(json.dumps(row) + "\n" for row in rows).encode()
    (tmp_path / "rule-results.jsonl").write_bytes(raw)
    (tmp_path / "FREEZE.json").write_text(
        json.dumps({"confirmatory_eligible": False, "capture_sha256": "sha256:fixture"}),
        encoding="utf-8",
    )
    (tmp_path / "RESULT.json").write_text(
        json.dumps(
            {
                "status": "DEVELOPMENT_SCORED",
                "confirmatory_eligible": False,
                "production_qualified": False,
                "units": 2,
                "tests": 3,
                "evaluator_errors": 0,
                "rule_results_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    surface = _FakeSurface({"model": {"u1": 0.0, "u2": 0.0}})
    surface.models = ["model"]
    surface.elements = {}
    surface.notes = []
    binding = S.add_native_olmocr_surface(surface, tmp_path)
    assert surface.loss["native"] == {"u1": 0.5, "u2": 1.0}
    assert surface.models == ["model", "native"]
    assert binding["capture_freeze_sha256"] == "sha256:fixture"


def test_router_v2_replay_policies_have_distinct_bound_names() -> None:
    visual = F.planner_adapter(primary=F.PRIMARY_MODEL, strong=F.PEER_MODEL)
    native = F.planner_adapter(primary="native", strong=F.PRIMARY_MODEL)
    assert visual is not None and native is not None
    assert visual.name != native.name
