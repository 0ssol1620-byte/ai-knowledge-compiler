"""WP-R10 Phase B — the HIDDEN half of the offline router replay.

This module is the only place that opens evaluation truth:

  * ``reports/full_compare_20260905/{omnidoc,olmocr,parsebench}_raw/`` — the
    per-unit evaluator scores (loaded through the Phase A loaders so Phase A and
    Phase B are scored by the same code);
  * ``OmniDocBench.json`` and the benchmark ``*.jsonl`` rule files — the ground
    truth text the SCLR opportunity denominator is counted over.

``features.py`` never imports this module, and a test asserts it. Nothing here
is ever consulted by a policy.

Diagnostic research code. Not a public benchmark result.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_ORACLE = Path(__file__).resolve().parents[1] / "router_oracle_20260908"
if str(_ORACLE) not in sys.path:
    sys.path.insert(0, str(_ORACLE))

import oracle as _oracle  # type: ignore[import-not-found]  # noqa: E402
from bind import load_json  # type: ignore[import-not-found]  # noqa: E402
from reconciler import UNRESOLVED  # type: ignore[import-not-found]  # noqa: E402

HERE = Path(__file__).resolve().parent

DATASETS = Path(
    r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core"
)
OMNIDOC_GT = DATASETS / "omnidocbench" / "OmniDocBench.json"
OLMOCR_GT_DIR = DATASETS / "olmocr-bench" / "bench_data"
PARSEBENCH_GT_DIR = DATASETS / "parsebench"

# tau for "this unit is wrong", identical to Phase A so the two are comparable.
HARD_FAIL_TAU = _oracle.HARD_FAIL_TAU

OPPORTUNITY_FREEZE_ID = "TAVONEL-ROUTER-REPLAY-SCLR-OPPORTUNITY-2026-09-08-V1"
NATIVE_EXPECTED_UNITS = 1403
NATIVE_EXPECTED_RULES = 8413

# The critical-opportunity detector IS akc_cir's own counter set. Reusing the
# module's compiled patterns rather than restating them is deliberate: a second
# copy of these regexes would silently drift from the production detector, and
# then the denominator would stop describing what the detector can find.
from akc_cir import critical_tokens as _ct  # noqa: E402

OPPORTUNITY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("date", _ct._DATE),
    ("currency", _ct._CURRENCY),
    ("sign", _ct._SIGNED),
    ("unit", _ct._UNIT),
    ("number", _ct._NUMBER),
)
RISK = {kind.value: value for kind, value in _ct._RISK.items()}

_TABLE_CELL = re.compile(r"<t[dh][\s>]|^\s*\|", re.IGNORECASE | re.MULTILINE)


# ---------------------------------------------------------------------------
# loss surfaces (Phase A loaders, unchanged)
# ---------------------------------------------------------------------------


def load_surfaces(root: Path, bind: dict[str, Any]) -> dict[str, Any]:
    """Every scoreable surface, using the Phase A loaders verbatim."""
    surfaces = {
        "omnidoc": _oracle.load_omnidoc(root, bind),
        "olmocr": _oracle.load_olmocr(root, bind),
    }
    for facet in ("table", "chart", "text_content", "text_formatting"):
        surfaces[f"parsebench:{facet}"] = _oracle.load_parsebench(root, bind, facet)
    return surfaces


def add_native_olmocr_surface(surface: Any, score_root: Path) -> dict[str, Any]:
    """Bind the hidden Native rule outcome to the existing olmOCR surface.

    This function remains in the scorer half.  A runtime policy receives only
    the augmented visible observation produced by ``native_visible`` and can
    never access this directory or any rule result.
    """
    score_root = score_root.resolve(strict=True)
    if not score_root.is_dir():
        raise ValueError("NATIVE_SCORE_DIRECTORY_REQUIRED")
    result_path = (score_root / "RESULT.json").resolve(strict=True)
    freeze_path = (score_root / "FREEZE.json").resolve(strict=True)
    rules_path = (score_root / "rule-results.jsonl").resolve(strict=True)
    for path in (result_path, freeze_path, rules_path):
        if path.parent != score_root:
            raise ValueError("NATIVE_SCORE_PATH_ESCAPE")
    result = load_json(result_path)
    freeze = load_json(freeze_path)
    rules_sha256 = "sha256:" + hashlib.sha256(rules_path.read_bytes()).hexdigest()
    if (
        result.get("status") != "DEVELOPMENT_SCORED"
        or result.get("confirmatory_eligible") is not False
        or result.get("production_qualified") is not False
        or result.get("units") != NATIVE_EXPECTED_UNITS
        or result.get("tests") != NATIVE_EXPECTED_RULES
        or result.get("evaluator_errors") != 0
        or result.get("rule_results_sha256") != rules_sha256
    ):
        raise ValueError("NATIVE_SCORE_BINDING_INVALID")
    if freeze.get("confirmatory_eligible") is not False:
        raise ValueError("SPENT_NATIVE_SCORE_REQUIRED")

    totals: dict[str, list[int]] = {}
    by_type: dict[str, dict[str, list[int]]] = {}
    seen: set[str] = set()
    with rules_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            test_id = row.get("test_id")
            unit = row.get("pdf")
            test_type = row.get("type")
            passed = row.get("passed")
            if (
                not isinstance(test_id, str)
                or test_id in seen
                or not isinstance(unit, str)
                or not isinstance(test_type, str)
                or type(passed) is not bool
                or row.get("evaluator_error") is not None
            ):
                raise ValueError("NATIVE_SCORE_RULE_INVALID")
            seen.add(test_id)
            failed = 0 if passed else 1
            totals.setdefault(unit, [0, 0])
            totals[unit][0] += failed
            totals[unit][1] += 1
            by_type.setdefault(test_type, {}).setdefault(unit, [0, 0])
            by_type[test_type][unit][0] += failed
            by_type[test_type][unit][1] += 1
    if len(seen) != NATIVE_EXPECTED_RULES or len(totals) != NATIVE_EXPECTED_UNITS:
        raise ValueError("NATIVE_SCORE_DENOMINATOR_INCOMPLETE")
    if set(totals) != set(surface.all_units()):
        raise ValueError("NATIVE_SCORE_PAGE_SET_MISMATCH")

    surface.loss["native"] = {unit: failed / count for unit, (failed, count) in totals.items()}
    for test_type, rows in by_type.items():
        surface.elements.setdefault(f"type:{test_type}", {})["native"] = {
            unit: failed / count for unit, (failed, count) in rows.items()
        }
    surface.models = sorted(set(surface.models) | {"native"})
    surface.notes.append(
        "Native is the complete spent 1,403-page text-projection arm; empty, refused, "
        "unqualified and failed pages remain in the denominator."
    )
    return {
        "score_freeze_sha256": "sha256:" + hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
        "rule_results_sha256": rules_sha256,
        "capture_freeze_sha256": freeze.get("capture_sha256"),
        "rules": len(seen),
        "pages": len(totals),
        "confirmatory_eligible": False,
        "production_qualified": False,
    }


def unit_loss(surface: Any, model: str, unit: str) -> float:
    """Missing or failed is a full loss. Never dropped, never imputed."""
    value = surface.loss.get(model, {}).get(unit)
    return 1.0 if value is None else float(value)


def oracle_unit_loss(
    surface: Any, unit: str, models: Sequence[str], reconciler_choice: str
) -> float:
    """The permitted-plan Oracle's per-unit loss (Phase A section 35 rule).

    One plan for the whole unit: the best SINGLE model, or the frozen
    reconciler's pick. No cross-model splicing.
    """
    options = [unit_loss(surface, model, unit) for model in models]
    if reconciler_choice != UNRESOLVED and reconciler_choice in models:
        options.append(unit_loss(surface, reconciler_choice, unit))
    else:
        options.append(1.0)
    return min(options) if options else 1.0


# ---------------------------------------------------------------------------
# ground-truth text, per surface
# ---------------------------------------------------------------------------


def _omnidoc_gt() -> dict[str, str]:
    out: dict[str, str] = {}
    if not OMNIDOC_GT.is_file():
        return out
    for page in load_json(OMNIDOC_GT):
        info = page.get("page_info") or {}
        image = info.get("image_path")
        if not image:
            continue
        parts: list[str] = []
        for det in page.get("layout_dets") or []:
            for key in ("text", "latex", "html"):
                value = det.get(key)
                if isinstance(value, str) and value:
                    parts.append(value)
        out[str(image)] = "\n".join(parts)
    return out


def _olmocr_gt() -> dict[str, str]:
    """Assembled from the asserted spans of the bench rules.

    LIMITATION, and it travels with every olmOCR SCLR number: olmOCR-Bench does
    not publish a full page transcription. Its ground truth is a set of
    assertions, so this text is the union of what the bench asserts must be
    present -- a LOWER BOUND on the page's critical opportunities, never the
    page's full content. `absent` rules are excluded: they assert text that must
    NOT appear, which is not an opportunity to preserve.
    """
    out: dict[str, list[str]] = {}
    if not OLMOCR_GT_DIR.is_dir():
        return {}
    for path in sorted(OLMOCR_GT_DIR.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if str(row.get("type")) == "absent":
                    continue
                unit = str(row.get("pdf") or "")
                if not unit:
                    continue
                bucket = out.setdefault(unit, [])
                for key in (
                    "text",
                    "math",
                    "cell",
                    "up",
                    "down",
                    "left",
                    "right",
                    "top_heading",
                    "left_heading",
                ):
                    value = row.get(key)
                    if isinstance(value, str) and value:
                        bucket.append(value)
    return {unit: _join_unique(parts) for unit, parts in out.items()}


def _join_unique(parts: Sequence[str]) -> str:
    """Deduplicate before joining.

    A benchmark repeats the same assertion payload on several rules for the same
    page (ParseBench text_content carries the whole bag-of-sentence on both its
    `missing_` and `unexpected_` rules). Joining them verbatim would double every
    critical-token count -- inflating the SCLR denominator and, worse, making the
    deletion detector claim losses that never happened.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for part in parts:
        if part not in seen:
            seen.add(part)
            kept.append(part)
    return "\n".join(kept)


def _parsebench_gt(facet: str) -> dict[str, str]:
    """Same lower-bound caveat as olmOCR for every facet except `table`."""
    path = PARSEBENCH_GT_DIR / f"{facet}.jsonl"
    out: dict[str, list[str]] = {}
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            pdf = str(row.get("pdf") or "")
            unit = pdf.removeprefix("docs/").removesuffix(".pdf")
            if not unit:
                continue
            bucket = out.setdefault(unit, [])
            expected = row.get("expected_markdown")
            if isinstance(expected, str) and expected:
                bucket.append(expected)
            rule = row.get("rule")
            if isinstance(rule, str) and rule:
                try:
                    payload = json.loads(rule)
                except json.JSONDecodeError:
                    continue
                bucket.extend(_rule_strings(payload))
    return {unit: _join_unique(parts) for unit, parts in out.items()}


def _rule_strings(payload: Any) -> list[str]:
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, dict):
        out: list[str] = []
        for key, value in payload.items():
            if key in {"max_diffs", "normalize_numbers", "level", "case_sensitive"}:
                continue
            if key == "bag_of_sentence" and isinstance(value, dict):
                out.extend(str(k) for k in value)
                continue
            out.extend(_rule_strings(value))
        return out
    if isinstance(payload, list):
        out = []
        for item in payload:
            out.extend(_rule_strings(item))
        return out
    return []


def ground_truth(surface_key: str) -> dict[str, str]:
    if surface_key == "omnidoc":
        return _omnidoc_gt()
    if surface_key == "olmocr":
        return _olmocr_gt()
    if surface_key.startswith("parsebench:"):
        return _parsebench_gt(surface_key.split(":", 1)[1])
    return {}


GT_COMPLETENESS = {
    "omnidoc": "FULL — every layout block's text, latex and html from OmniDocBench.json",
    "olmocr": "PARTIAL — the union of asserted `present`/`math`/`table` spans; a lower bound",
    "parsebench:table": "FULL for tables — expected_markdown per document",
    "parsebench:chart": "PARTIAL — asserted chart labels and values only",
    "parsebench:text_content": "PARTIAL — the bag-of-sentence keys only",
    "parsebench:text_formatting": "PARTIAL — asserted heading/format spans only",
}


# ---------------------------------------------------------------------------
# the frozen critical-opportunity detector (SCLR denominator)
# ---------------------------------------------------------------------------


def count_opportunities(text: str) -> dict[str, int]:
    """Critical-fact opportunities in one piece of ground truth.

    `identifier` is 0 by construction and is reported as NOT_MEASURABLE: the
    production detector takes an explicit `expected_identifiers` list and no
    public benchmark here supplies one. Zero here means "no denominator", never
    "no identifiers".
    """
    counts = {
        kind: sum(_ct._counter(pattern, text).values())
        for kind, pattern in OPPORTUNITY_PATTERNS
    }
    counts["table_cell"] = len(_TABLE_CELL.findall(text))
    counts["identifier"] = 0
    return counts


def build_opportunity_freeze(surface_keys: Sequence[str]) -> dict[str, Any]:
    """Count the denominator over ground truth, BEFORE any arm is scored."""
    surfaces: dict[str, Any] = {}
    for key in surface_keys:
        gt = ground_truth(key)
        per_unit = {unit: count_opportunities(text) for unit, text in gt.items()}
        totals: Counter[str] = Counter()
        for row in per_unit.values():
            totals.update(row)
        surfaces[key] = {
            "gt_completeness": GT_COMPLETENESS.get(key, "UNKNOWN"),
            "n_units_with_gt": len(per_unit),
            "totals": dict(sorted(totals.items())),
            "units_with_at_least_one_opportunity": sum(
                1 for row in per_unit.values() if sum(row.values()) > 0
            ),
            "per_unit": per_unit,
        }
    payload: dict[str, Any] = {
        "schema": "tavonel.router_replay.sclr_opportunity_freeze.v1",
        "freeze_id": OPPORTUNITY_FREEZE_ID,
        "frozen_before_scoring": True,
        "detector": {
            "source_module": "akc_cir.critical_tokens",
            "kinds": [kind for kind, _ in OPPORTUNITY_PATTERNS]
            + ["table_cell", "identifier"],
            "risk_weights": RISK,
            "table_cell_rule": "regex `<td|<th|^\\s*\\|` occurrences in the GT text",
            "identifier_rule": (
                "NOT_MEASURABLE — verify_critical_tokens needs an explicit "
                "expected_identifiers list and no benchmark here publishes one"
            ),
        },
        "gt_assembly": (
            "Ground-truth strings are deduplicated per unit before counting: a "
            "benchmark that repeats the same payload across several rules would "
            "otherwise multiply the denominator."
        ),
        "loss_event_definition": (
            "DELETION ONLY: a critical token whose multiplicity in the accepted "
            "output is strictly lower than in the ground truth. Insertion is "
            "hallucination, a different class, and is not counted here."
        ),
        "surfaces": surfaces,
    }
    return payload


def hidden_critical_loss(gt_text: str, output_text: str) -> tuple[int, float, tuple[str, ...]]:
    """Deletion-direction critical-token loss. HIDDEN: reads ground truth.

    Returns (events, max risk, kinds). `events` counts token multiplicities lost,
    not distinct tokens, so a table that drops six identical zeros counts six.
    """
    events = 0
    worst = 0.0
    kinds: set[str] = set()
    for kind, pattern in OPPORTUNITY_PATTERNS:
        source = _ct._counter(pattern, gt_text)
        if not source:
            continue
        produced = _ct._counter(pattern, output_text)
        for token, count in source.items():
            missing = count - produced.get(token, 0)
            if missing > 0:
                events += missing
                kinds.add(kind)
                worst = max(worst, RISK[kind])
    return events, worst, tuple(sorted(kinds))


def sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def write_json(path: Path, payload: Mapping[str, Any]) -> str:
    data = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    path.write_bytes(data)
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


__all__ = [
    "GT_COMPLETENESS",
    "HARD_FAIL_TAU",
    "OPPORTUNITY_FREEZE_ID",
    "add_native_olmocr_surface",
    "build_opportunity_freeze",
    "count_opportunities",
    "ground_truth",
    "hidden_critical_loss",
    "load_surfaces",
    "oracle_unit_loss",
    "unit_loss",
    "write_json",
]
