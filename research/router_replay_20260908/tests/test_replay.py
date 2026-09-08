"""WP-R10 replay invariants, on synthetic data where possible.

The one that matters most is structural: the runtime-visible half must be
UNABLE to open hidden evaluation truth. Everything else is arithmetic that has
to hold whatever the arena says.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

LANE = Path(__file__).resolve().parents[1]
for _path in (LANE, LANE.parent / "router_oracle_20260908"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import features as F  # noqa: E402
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
