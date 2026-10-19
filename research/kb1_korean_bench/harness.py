"""KB1 offline, deterministic scoring harness (KOREAN-BENCHMARK-DESIGN-2026-10-17).

Design sections: §5.3 M1-M9, §5.6 denominators, §5.10 fail-closed, §2.3 numerics.

Scores one arm's run against KB1 gold, per category (K1-K6, KS), for metrics
M1-M9 plus completion and latency. Output keys follow ``KB1-PREREG.json``
(revision ``kb1-prereg-draft-r1``, sha256 ``cb51fd44…``).

**Thresholds are preregistered proposals, not calibrated values.** The page CER
threshold 0.10, the M9 IoU 0.5, the sample floor (n ≥ 50 pages, ≥ 10 families,
≤ 5 pages per family), the bootstrap's 10,000 resamples and its seed are copied
from the DRAFT_PROPOSED preregistration. No corpus has calibrated any of them,
and nothing this module emits is a measured result until a sealed
preregistration and a frozen evaluator record exist.

Rules the code enforces (design section in brackets):

* All text is NFC-normalised before comparison; M1 removes whitespace [§5.3].
  NFKC CER (M1) and raw-code-point recall (M6) are secondary reports.
* Every ratio is ``{"numerator", "denominator", "value"}``; ``value`` is null
  when the denominator is 0 [§5.6].
* Every gold page stays in every denominator. FAILED, TIMEOUT and
  LIMIT_REJECTED rows score as empty output (page CER 1.0); a missing run row
  is a contract error, not a silent drop [§5.6].
* Page CER is capped at 1.0 (repetition runaway); the uncapped insertion count
  is reported under M8 [§5.3 M1]. A runaway is any page whose edit distance
  exceeds its gold length; no separate repetition threshold is invented.
* An evaluator failure is ``EVALUATOR_BLOCKED`` for the whole category metric,
  never 0 and never a partial average; a metric the arm's declared capability
  does not cover is ``UNSUPPORTED``; a metric no gold page annotates is
  ``NOT_MEASURED``; categories are never merged into one headline [§5.10].
* Gold text containing a Private Use Area code point is rejected: a text-layer
  draft with PUA must be re-transcribed by a person [§5.7.4].
* M3 uses ``ko_tokens``, never ``akc_quality.numeric`` [§2.3].
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ko_tokens import TOKENIZER_REVISION, extract

REPORT_SCHEMA = "tavonel.kb1.report.v1"
GOLD_SCHEMA = "tavonel.kb1.gold.v1"
RUN_SCHEMA = "tavonel.kb1.run.v1"
HARNESS_REVISION = "kb1-harness-r1"
NORMALIZATION_REVISION = "kb1-norm-r1: NFC; whitespace removed for M1 (allowlist NOT_FROZEN)"
M6_CHARACTER_SET_REVISION = "kb1-m6-proposed-r1 (NOT_FROZEN)"

CATEGORIES = ("K1", "K2", "K3", "K4", "K5", "K6", "KS")
RUN_STATUSES = frozenset({"SUCCESS", "FAILED", "TIMEOUT", "LIMIT_REJECTED"})
CAPABILITIES = ("blocks", "table_structure", "region_bbox", "approval_box")

# Preregistered proposals (KB1-PREREG.json), uncalibrated.
PAGE_CER_THRESHOLD = 0.10
M9_IOU_THRESHOLD = 0.5
MIN_CONFIRM_PAGES = 50
MIN_FAMILIES = 10
MAX_PAGES_PER_FAMILY = 5
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = "tavonel-kb1-bootstrap-2026-10-17"

# ponytail: pure-Python O(n*m) alignment; a page beyond this many DP cells is
# EVALUATOR_BLOCKED instead of hanging. Upgrade path: a C-backed edit distance
# (a dependency decision) if real runaway pages hit it.
MAX_ALIGNMENT_CELLS = 20_000_000

MEASURED = "MEASURED"
NOT_MEASURED = "NOT_MEASURED"
UNSUPPORTED = "UNSUPPORTED"
EVALUATOR_BLOCKED = "EVALUATOR_BLOCKED"
STATUS_LABELS_KO = {
    NOT_MEASURED: "측정 안 함",
    UNSUPPORTED: "UNSUPPORTED (capability)",
    EVALUATOR_BLOCKED: "EVALUATOR_BLOCKED",
    "INSUFFICIENT_SAMPLE": "표본 부족 — 게시하지 않음",
    "SYNTHETIC_NOT_PUBLISHABLE": "합성 대조군 — 공개 수치로 쓰지 않음",
}

SCRIPTS = ("hangul", "latin", "digit", "hanja", "symbol", "other")
TOKEN_KINDS = (
    "date",
    "article",
    "phone",
    "business_id",
    "amount",
    "percent",
    "number_unit",
    "number",
)
_CIRCLED_1_TO_20 = "".join(chr(cp) for cp in range(0x2460, 0x2474))
# Proposed set (prereg M6, NOT_FROZEN): circled 1-20, reference mark, corner and
# tortoise-shell brackets, parenthesised 주, middle dot, one-dot leader, circle, square.
# Look-alike characters (tortoise-shell brackets, one-dot leader) go through chr()
# so ruff's RUF001 stays meaningful elsewhere.
_LOOKALIKES = "".join(map(chr, (0x3014, 0x3015, 0x2024)))
M6_SYMBOLS = frozenset(_CIRCLED_1_TO_20 + "※「」『』㈜·○□" + _LOOKALIKES)


class GoldContractError(ValueError):
    """Gold payload violates the KB1 gold contract."""


class RunContractError(ValueError):
    """Run payload is incomplete or malformed; it cannot be scored."""


class EvaluatorError(RuntimeError):
    """The evaluator could not score a page; the metric becomes EVALUATOR_BLOCKED."""


# --------------------------------------------------------------------------- text


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _strip_ws(text: str) -> tuple[str, frozenset[int]]:
    """Whitespace-free text and the indices that follow a whitespace run."""
    chars: list[str] = []
    boundaries: set[int] = set()
    pending = False
    for char in text:
        if char.isspace():
            pending = bool(chars)
            continue
        if pending:
            boundaries.add(len(chars))
            pending = False
        chars.append(char)
    return "".join(chars), frozenset(boundaries)


def is_pua(char: str) -> bool:
    cp = ord(char)
    return 0xE000 <= cp <= 0xF8FF or 0xF0000 <= cp <= 0xFFFFD or 0x100000 <= cp <= 0x10FFFD


def is_hanja(char: str) -> bool:
    cp = ord(char)
    return (
        0x4E00 <= cp <= 0x9FFF
        or 0x3400 <= cp <= 0x4DBF
        or 0xF900 <= cp <= 0xFAFF
        or 0x20000 <= cp <= 0x3134F
    )


def script_of(char: str) -> str:
    cp = ord(char)
    if (
        0xAC00 <= cp <= 0xD7A3
        or 0x1100 <= cp <= 0x11FF
        or 0x3130 <= cp <= 0x318F
        or 0xA960 <= cp <= 0xA97F
        or 0xD7B0 <= cp <= 0xD7FF
    ):
        return "hangul"
    if is_hanja(char):
        return "hanja"
    category = unicodedata.category(char)
    if category == "Nd":
        return "digit"
    if category.startswith("L"):
        return "latin" if "LATIN" in unicodedata.name(char, "") else "other"
    return "symbol"


def _ratio(numerator: float, denominator: float) -> dict[str, Any]:
    value = numerator / denominator if denominator else None
    return {"numerator": numerator, "denominator": denominator, "value": value}


def _nearest_rank(sorted_values: Sequence[float], quantile: float) -> float:
    rank = max(1, math.ceil(quantile * len(sorted_values)))
    return sorted_values[rank - 1]


# ---------------------------------------------------------------------- alignment


@dataclass(frozen=True)
class Alignment:
    """One deterministic optimal Levenshtein alignment of gold against output.

    Among alignments of minimal distance it takes one with the fewest
    insertions plus deletions, which makes the S/D/I counts unique; positions
    (M1-s script attribution, M2 boundaries, span errors) follow the remaining
    tie-break: common prefix and suffix match, then substitution, then deletion.
    """

    distance: int
    gold_ops: str  # "M" match, "S" substitution, "D" deletion — one per gold char
    gold_to_out: tuple[int, ...]  # aligned output index, -1 when deleted
    inserted: tuple[int, ...]  # output indices aligned to no gold char


def align(gold: str, output: str) -> Alignment:
    n_total, m_total = len(gold), len(output)
    pre = 0
    while pre < n_total and pre < m_total and gold[pre] == output[pre]:
        pre += 1
    suf = 0
    while (
        suf < n_total - pre
        and suf < m_total - pre
        and gold[n_total - 1 - suf] == output[m_total - 1 - suf]
    ):
        suf += 1
    g = gold[pre : n_total - suf]
    o = output[pre : m_total - suf]
    n, m = len(g), len(o)
    if n * m > MAX_ALIGNMENT_CELLS:
        raise EvaluatorError(
            f"alignment needs {n * m} DP cells, above MAX_ALIGNMENT_CELLS={MAX_ALIGNMENT_CELLS}"
        )
    # Cost = distance * weight + (insertions + deletions); indels < weight always.
    weight = n + m + 1
    sub, indel = weight, weight + 1
    width = m + 1
    back = bytearray(width * (n + 1))  # 0 diagonal, 1 deletion, 2 insertion
    back[1:width] = b"\x02" * m
    prev = [j * indel for j in range(width)]
    for i in range(1, n + 1):
        gc = g[i - 1]
        row = i * width
        back[row] = 1
        cur = [i * indel] + [0] * m
        for j in range(1, width):
            diag = prev[j - 1] if gc == o[j - 1] else prev[j - 1] + sub
            up = prev[j] + indel
            left = cur[j - 1] + indel
            if diag <= up and diag <= left:
                cur[j] = diag
            elif up <= left:
                cur[j] = up
                back[row + j] = 1
            else:
                cur[j] = left
                back[row + j] = 2
        prev = cur

    ops = ["M"] * n_total
    gold_to_out = list(range(pre)) + [-1] * (n_total - pre)
    for k in range(suf):
        gold_to_out[n_total - suf + k] = m_total - suf + k
    inserted: list[int] = []
    i, j = n, m
    while i or j:
        step = back[i * width + j]
        if step == 0:
            ops[pre + i - 1] = "M" if g[i - 1] == o[j - 1] else "S"
            gold_to_out[pre + i - 1] = pre + j - 1
            i, j = i - 1, j - 1
        elif step == 1:
            ops[pre + i - 1] = "D"
            i -= 1
        else:
            inserted.append(pre + j - 1)
            j -= 1
    inserted.reverse()
    return Alignment(prev[m] // weight, "".join(ops), tuple(gold_to_out), tuple(inserted))


def _try_align(gold: str, output: str) -> Alignment | EvaluatorError:
    try:
        return align(gold, output)
    except EvaluatorError as exc:
        return exc


# ------------------------------------------------------------------------ contract


@dataclass(frozen=True)
class Line:
    text: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class GoldPage:
    page_id: str
    family_id: str
    category: str
    synthetic: bool
    text: str
    blocks: tuple[str, ...]
    lines: tuple[Line, ...]
    table_count: int
    seal_text: str | None
    occluded_spans: tuple[tuple[int, int], ...]
    approval_box: bool | None
    table_text_spans: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class RunPage:
    page_id: str
    status: str
    text: str
    blocks: tuple[str, ...]
    regions: tuple[Line, ...]
    approval_box_detected: bool | None
    latency_ms: float | None


_Kind = type | tuple[type, ...]


def _field(
    obj: Mapping[str, Any], key: str, kind: _Kind, where: str, error: type[ValueError]
) -> Any:
    value = obj.get(key)
    if not isinstance(value, kind) or (isinstance(value, bool) and kind is not bool):
        raise error(f"{where}: field {key!r} must be {kind}, got {type(value).__name__}")
    return value


def _optional(
    obj: Mapping[str, Any], key: str, kind: _Kind, where: str, error: type[ValueError]
) -> Any:
    return None if obj.get(key) is None else _field(obj, key, kind, where, error)


def _bbox(
    value: Any, where: str, error: type[ValueError], strict: bool
) -> tuple[float, float, float, float]:
    ok = (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
        and all(math.isfinite(v) for v in value)
    )
    if ok:
        x0, y0, x1, y1 = value
        ok = (x0 < x1 and y0 < y1) if strict else (x0 <= x1 and y0 <= y1)
    if not ok:
        raise error(f"{where}: bbox must be [x0, y0, x1, y1] with x0<x1, y0<y1, got {value!r}")
    x0, y0, x1, y1 = (float(v) for v in value)
    return (x0, y0, x1, y1)


def _no_pua(text: str, where: str) -> str:
    bad = sorted({f"U+{ord(c):04X}" for c in text if is_pua(c)})
    if bad:
        raise GoldContractError(
            f"{where}: Private Use Area code points {bad}; a PUA text-layer draft must be"
            " discarded and transcribed by a person (design §5.7.4)"
        )
    return text


def _lines(raw: Any, where: str, error: type[ValueError], strict: bool) -> tuple[Line, ...]:
    if not isinstance(raw, list):
        raise error(f"{where}: must be a list")
    lines = []
    for index, item in enumerate(raw):
        here = f"{where}[{index}]"
        if not isinstance(item, Mapping):
            raise error(f"{here}: must be an object")
        text = _field(item, "text", str, here, error)
        lines.append(Line(text, _bbox(item.get("bbox"), here, error, strict)))
    return tuple(lines)


def _spans(raw: Any, text_length: int, where: str) -> tuple[tuple[int, int], ...]:
    """[start, end) code-point offsets into the page's NFC text."""
    if not isinstance(raw, list):
        raise GoldContractError(f"{where}: must be a list of [start, end) spans")
    spans = []
    for span in raw:
        ok = (
            isinstance(span, list)
            and len(span) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in span)
            and 0 <= span[0] < span[1] <= text_length
        )
        if not ok:
            raise GoldContractError(f"{where}: span {span!r} is not [start, end) of the NFC text")
        spans.append((span[0], span[1]))
    return tuple(spans)


def _str_list(raw: Any, where: str, error: type[ValueError]) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise error(f"{where}: must be a list of strings")
    return tuple(raw)


def parse_gold(gold: Mapping[str, Any]) -> list[GoldPage]:
    err = GoldContractError
    if gold.get("schema") != GOLD_SCHEMA:
        raise err(f"gold schema must be {GOLD_SCHEMA!r}")
    raw_pages = gold.get("pages")
    if not isinstance(raw_pages, list) or not raw_pages:
        raise err("gold: 'pages' must be a non-empty list")
    pages: list[GoldPage] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_pages):
        where = f"gold.pages[{index}]"
        if not isinstance(raw, Mapping):
            raise err(f"{where}: must be an object")
        page_id = _field(raw, "page_id", str, where, err)
        if not page_id or page_id in seen:
            raise err(f"{where}: page_id {page_id!r} is empty or duplicated")
        seen.add(page_id)
        where = f"gold page {page_id}"
        category = _field(raw, "category", str, where, err)
        if category not in CATEGORIES:
            raise err(f"{where}: category {category!r} not in {CATEGORIES}")
        synthetic = raw.get("synthetic", False)
        if not isinstance(synthetic, bool) or (category == "KS" and not synthetic):
            raise err(f"{where}: KS pages must carry synthetic: true")
        family_id = _field(raw, "family_id", str, where, err)
        if not family_id:
            raise err(f"{where}: family_id must be non-empty")
        text = _no_pua(_field(raw, "text", str, where, err), where)
        nfc_text = _nfc(text)
        if not _strip_ws(nfc_text)[0]:
            raise err(f"{where}: gold text has no non-whitespace character")
        blocks = _str_list(raw.get("blocks", []), f"{where}.blocks", err)
        lines = _lines(raw.get("lines", []), f"{where}.lines", err, strict=True)
        for item in (*blocks, *(line.text for line in lines)):
            _no_pua(item, where)
            if not _strip_ws(_nfc(item))[0]:
                raise err(f"{where}: empty block or line text")
        table_count = raw.get("table_count", 0)
        if not isinstance(table_count, int) or isinstance(table_count, bool) or table_count < 0:
            raise err(f"{where}: table_count must be a non-negative integer")
        seal_text: str | None = None
        occluded: tuple[tuple[int, int], ...] = ()
        seal = raw.get("seal")
        if seal is not None:
            if not isinstance(seal, Mapping):
                raise err(f"{where}.seal: must be an object")
            seal_text = _no_pua(_field(seal, "text", str, f"{where}.seal", err), where)
            occluded = _spans(seal.get("occluded_spans", []), len(nfc_text), f"{where}.seal")
        table_spans = _spans(raw.get("table_text_spans", []), len(nfc_text), where)
        if table_spans and not table_count:
            raise err(f"{where}: table_text_spans need table_count > 0")
        approval_box = _optional(raw, "approval_box", bool, where, err)
        pages.append(
            GoldPage(
                page_id,
                family_id,
                category,
                synthetic,
                text,
                blocks,
                lines,
                table_count,
                seal_text,
                occluded,
                approval_box,
                table_spans,
            )
        )
    return pages


_CAPABILITY_FIELDS = {
    "blocks": "blocks",
    "regions": "region_bbox",
    "approval_box_detected": "approval_box",
}


def parse_run(
    run: Mapping[str, Any], gold_ids: Sequence[str]
) -> tuple[dict[str, Any], dict[str, bool], dict[str, RunPage]]:
    err = RunContractError
    if run.get("schema") != RUN_SCHEMA:
        raise err(f"run schema must be {RUN_SCHEMA!r}")
    arm = run.get("arm")
    if not isinstance(arm, Mapping):
        raise err("run: 'arm' must be an object")
    _field(arm, "arm_id", str, "run.arm", err)
    raw_caps = arm.get("capabilities")
    if not isinstance(raw_caps, Mapping):
        raise err("run.arm: 'capabilities' must be an object declared from capability evidence")
    caps = {name: _field(raw_caps, name, bool, "run.arm.caps", err) for name in CAPABILITIES}
    raw_pages = run.get("pages")
    if not isinstance(raw_pages, list):
        raise err("run: 'pages' must be a list")
    rows: dict[str, RunPage] = {}
    for index, raw in enumerate(raw_pages):
        where = f"run.pages[{index}]"
        if not isinstance(raw, Mapping):
            raise err(f"{where}: must be an object")
        page_id = _field(raw, "page_id", str, where, err)
        if page_id in rows:
            raise err(f"{where}: duplicate page_id {page_id!r}")
        status = _field(raw, "status", str, where, err)
        if status not in RUN_STATUSES:
            raise err(f"{where}: status {status!r} not in {sorted(RUN_STATUSES)}")
        success = status == "SUCCESS"
        if success:
            text = _field(raw, "text", str, where, err)
        elif raw.get("text") not in (None, ""):
            raise err(f"{where}: a {status} row must not carry output text")
        else:
            text = ""
        for key, cap in _CAPABILITY_FIELDS.items():
            if key in raw and not caps[cap]:
                raise err(f"{where}: carries {key!r} but the arm declares {cap}: false")
            if success and caps[cap] and key not in raw:
                raise err(f"{where}: arm declares {cap}: true but the row has no {key!r}")
        blocks = _str_list(raw.get("blocks", []), f"{where}.blocks", err) if success else ()
        regions = _lines(raw.get("regions", []), f"{where}.regions", err, strict=False)
        detected = (
            _field(raw, "approval_box_detected", bool, where, err)
            if success and caps["approval_box"]
            else None
        )
        latency = _optional(raw, "latency_ms", (int, float), where, err)
        if latency is not None and (not math.isfinite(latency) or latency < 0):
            raise err(f"{where}: latency_ms must be a finite non-negative number")
        rows[page_id] = RunPage(
            page_id,
            status,
            text,
            blocks,
            regions if success else (),
            detected,
            None if latency is None else float(latency),
        )
    missing = [page_id for page_id in gold_ids if page_id not in rows]
    extra = sorted(set(rows) - set(gold_ids))
    if missing or extra:
        raise err(
            f"run must have exactly one row per gold page: missing {len(missing)} {missing[:10]},"
            f" unknown {len(extra)} {extra[:10]}"
        )
    return dict(arm), caps, rows


# ---------------------------------------------------------------------- page score


@dataclass(frozen=True)
class _Mark:
    status: str  # EVALUATOR_BLOCKED or UNSUPPORTED
    detail: str


PageMetric = dict[str, float] | _Mark | None


def _cer_counts(gold_ns: str, out_ns: str, al: Alignment | EvaluatorError) -> PageMetric:
    gold_chars = len(gold_ns)
    if isinstance(al, Alignment):
        raw = al.distance
    elif len(out_ns) - gold_chars > gold_chars:
        raw = len(out_ns) - gold_chars  # a lower bound already past the 1.0 cap
    else:
        return _Mark(EVALUATOR_BLOCKED, str(al))
    edits = min(raw, gold_chars)
    page_cer = edits / gold_chars
    return {
        "edits": edits,
        "gold_chars": gold_chars,
        "runaway_capped": int(raw > gold_chars),
        "over_threshold": int(page_cer > PAGE_CER_THRESHOLD),
        "pages": 1,
    }


def _kendall(gold_blocks: Sequence[str], out_blocks: Sequence[str]) -> dict[str, float]:
    """Pairs out of gold order, counting a pair with an unmatched block as discordant.

    ponytail: greedy one-to-one matching on character-bigram Dice; upgrade to an
    assignment solver if the KB-A4 OmniDocBench cross-check disagrees.
    """

    def grams(text: str) -> Counter[str]:
        flat = _strip_ws(_nfc(text))[0]
        if len(flat) < 2:
            return Counter(flat)
        return Counter(flat[k : k + 2] for k in range(len(flat) - 1))

    gold_grams = [grams(b) for b in gold_blocks]
    out_grams = [grams(b) for b in out_blocks]
    candidates = []
    for gi, gg in enumerate(gold_grams):
        for oi, og in enumerate(out_grams):
            shared = sum((gg & og).values())
            if shared:
                dice = 2 * shared / (sum(gg.values()) + sum(og.values()))
                candidates.append((-dice, gi, oi))
    candidates.sort()
    position: dict[int, int] = {}
    used: set[int] = set()
    for _, gi, oi in candidates:
        if gi not in position and oi not in used:
            position[gi] = oi
            used.add(oi)
    n = len(gold_blocks)
    discordant = 0
    for a in range(n):
        for b in range(a + 1, n):
            if a not in position or b not in position or position[a] > position[b]:
                discordant += 1
    return {
        "discordant_pairs": discordant,
        "pairs": n * (n - 1) // 2,
        "matched_blocks": len(position),
        "gold_blocks": n,
    }


def _iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _external_teds(
    page_id: str, evaluator_scores: Mapping[str, Any] | None
) -> dict[str, float] | _Mark:
    if evaluator_scores is None:
        return _Mark(EVALUATOR_BLOCKED, "no OmniDocBench TEDS scores supplied (KB-A4 adapter)")
    record = evaluator_scores.get("evaluator")
    if not isinstance(record, Mapping) or not all(
        isinstance(record.get(key), str) and record.get(key) for key in ("repository", "main_pin")
    ):
        return _Mark(EVALUATOR_BLOCKED, "TEDS scores lack an evaluator repository and main_pin")
    scores = evaluator_scores.get("pages")
    row = scores.get(page_id) if isinstance(scores, Mapping) else None
    values: list[float] = []
    for key in ("teds", "teds_struct"):
        value = row.get(key) if isinstance(row, Mapping) else None
        if not isinstance(value, int | float) or isinstance(value, bool) or not 0 <= value <= 1:
            return _Mark(EVALUATOR_BLOCKED, f"no valid {key} score for page {page_id}")
        values.append(float(value))
    return {"teds_sum": values[0], "teds_struct_sum": values[1], "table_pages": 1}


def score_page(
    gold: GoldPage,
    row: RunPage,
    caps: Mapping[str, bool],
    evaluator_scores: Mapping[str, Any] | None = None,
) -> dict[str, PageMetric]:
    out_text = row.text if row.status == "SUCCESS" else ""
    gold_nfc, out_nfc = _nfc(gold.text), _nfc(out_text)
    gold_ns, gold_bounds = _strip_ws(gold_nfc)
    out_ns, out_bounds = _strip_ws(out_nfc)
    al = _try_align(gold_ns, out_ns)
    metrics: dict[str, PageMetric] = {}

    metrics["M1"] = _cer_counts(gold_ns, out_ns, al)
    gold_k = _strip_ws(unicodedata.normalize("NFKC", gold_nfc))[0]
    out_k = _strip_ws(unicodedata.normalize("NFKC", out_nfc))[0]
    same = gold_k == gold_ns and out_k == out_ns
    metrics["M1-nfkc"] = _cer_counts(gold_k, out_k, al if same else _try_align(gold_k, out_k))
    if isinstance(metrics["M1-nfkc"], dict):
        metrics["M1-nfkc"] = {k: metrics["M1-nfkc"][k] for k in ("edits", "gold_chars")}

    blocked = _Mark(EVALUATOR_BLOCKED, str(al)) if isinstance(al, EvaluatorError) else None
    if isinstance(al, Alignment):
        per_script: dict[str, float] = {f"{s}.{k}": 0 for s in SCRIPTS for k in ("errors", "gold")}
        for char, op in zip(gold_ns, al.gold_ops, strict=True):
            per_script[f"{script_of(char)}.gold"] += 1
            per_script[f"{script_of(char)}.errors"] += op != "M"
        for index in al.inserted:
            per_script[f"{script_of(out_ns[index])}.errors"] += 1
        metrics["M1-s"] = per_script

        out_to_gold = {o: g for g, o in enumerate(al.gold_to_out) if o >= 0}
        tp = sum(1 for j in out_bounds if out_to_gold.get(j, -1) in gold_bounds)
        fp, fn = len(out_bounds) - tp, len(gold_bounds) - tp
        metrics["M2"] = {
            "tp": tp,
            "predicted": tp + fp,
            "gold": tp + fn,
            "f1_num": 2 * tp,
            "f1_den": 2 * tp + fp + fn,
        }

        excess = Counter(out_ns) - Counter(gold_ns)
        metrics["M8"] = {
            "insertions": len(al.inserted),
            "foreign_excess": sum(n for c, n in excess.items() if script_of(c) == "other"),
            "gold_chars": len(gold_ns),
            "output_pua_chars": sum(is_pua(c) for c in out_ns),
            "output_chars": len(out_ns),
        }
        metrics["M6"] = _m6_counts(gold_ns, al)
    else:
        metrics["M1-s"] = metrics["M2"] = metrics["M8"] = metrics["M6"] = blocked

    gold_raw, out_raw = _strip_ws(gold.text)[0], _strip_ws(out_text)[0]
    if gold_raw == gold_ns and out_raw == out_ns:
        metrics["M6-raw"] = metrics["M6"]
    else:
        raw_al = _try_align(gold_raw, out_raw)
        metrics["M6-raw"] = (
            _m6_counts(gold_raw, raw_al)
            if isinstance(raw_al, Alignment)
            else _Mark(EVALUATOR_BLOCKED, str(raw_al))
        )

    gold_tokens = Counter((t.kind, t.value) for t in extract(gold_nfc))
    out_tokens = Counter((t.kind, t.value) for t in extract(out_nfc))
    tokens: Counter[str] = Counter()
    bags = (("gold", gold_tokens), ("output", out_tokens), ("matched", gold_tokens & out_tokens))
    for suffix, bag in bags:
        for (kind, _), count in bag.items():
            tokens[f"{kind}.{suffix}"] += count
    metrics["M3"] = dict(tokens)

    metrics["M4"] = None
    if gold.table_count:
        if not caps["table_structure"]:
            metrics["M4"] = _Mark(UNSUPPORTED, "table_structure")
        elif row.status != "SUCCESS":
            metrics["M4"] = {"teds_sum": 0.0, "teds_struct_sum": 0.0, "table_pages": 1}
        else:
            metrics["M4"] = _external_teds(gold.page_id, evaluator_scores)

    # Design §5.3 M4: an arm without table structure still gets the text CER of
    # the gold table regions, so a table page is never silently unscored.
    metrics["M4-text"] = None
    if gold.table_text_spans:
        if isinstance(al, Alignment):
            errors, chars = _span_errors(gold_nfc, gold.table_text_spans, al)
            metrics["M4-text"] = {"errors": errors, "chars": chars}
        else:
            metrics["M4-text"] = blocked

    metrics["M5"] = None
    if gold.blocks:
        metrics["M5"] = (
            _kendall(gold.blocks, row.blocks) if caps["blocks"] else _Mark(UNSUPPORTED, "blocks")
        )

    metrics["M7"] = metrics["M7c"] = None
    if gold.seal_text is not None:
        metrics["M7"] = (
            _m7_counts(gold, gold_nfc, gold_ns, out_ns, al)
            if isinstance(al, Alignment)
            else blocked
        )
    if gold.approval_box:
        metrics["M7c"] = (
            {"detected": int(row.approval_box_detected is True), "approval_box_pages": 1}
            if caps["approval_box"]
            else _Mark(UNSUPPORTED, "approval_box")
        )

    metrics["M9"] = None
    if gold.lines:
        if not caps["region_bbox"]:
            metrics["M9"] = _Mark(UNSUPPORTED, "region_bbox")
        else:
            regions = [(_strip_ws(_nfc(r.text))[0], r.bbox) for r in row.regions]
            matched = 0
            for line in gold.lines:
                want = _strip_ws(_nfc(line.text))[0]
                matched += any(
                    want in text and _iou(line.bbox, bbox) >= M9_IOU_THRESHOLD
                    for text, bbox in regions
                )
            metrics["M9"] = {"matched_lines": matched, "gold_lines": len(gold.lines)}

    metrics["completion"] = {"with_output": int(bool(out_ns)), "pages": 1}
    return metrics


def _m6_counts(gold_ns: str, al: Alignment) -> dict[str, float]:
    in_set = [k for k, c in enumerate(gold_ns) if is_hanja(c) or c in M6_SYMBOLS]
    return {
        "recalled": sum(al.gold_ops[k] == "M" for k in in_set),
        "gold_set_chars": len(in_set),
    }


def _span_errors(gold_nfc: str, spans: Sequence[tuple[int, int]], al: Alignment) -> tuple[int, int]:
    """Substituted or deleted gold characters inside ``spans``, and the characters there.

    Insertions have no gold position, so they are not attributed to a span (M8 has them).
    """
    ns_index: dict[int, int] = {}
    for offset, char in enumerate(gold_nfc):
        if not char.isspace():
            ns_index[offset] = len(ns_index)
    inside = {ns_index[o] for start, end in spans for o in range(start, end) if o in ns_index}
    return sum(al.gold_ops[k] != "M" for k in inside), len(inside)


def _m7_counts(
    gold: GoldPage, gold_nfc: str, gold_ns: str, out_ns: str, al: Alignment
) -> dict[str, float]:
    """(a) errors on gold characters a seal occludes; (b) seal characters the output
    carries beyond the gold body's own count (alignment-free, so tie-break free)."""
    errors, chars = _span_errors(gold_nfc, gold.occluded_spans, al)
    seal = Counter(_strip_ws(_nfc(gold.seal_text or ""))[0])
    leaked = (Counter(out_ns) - Counter(gold_ns)) & seal
    return {
        "occluded_errors": errors,
        "occluded_chars": chars,
        "leaked_seal_chars": sum(leaked.values()),
        "seal_chars": sum(seal.values()),
    }


# --------------------------------------------------------------------- aggregation


def family_cluster_bootstrap(
    clusters: Sequence[tuple[float, float]], *, seed: str, resamples: int
) -> dict[str, Any]:
    """95% percentile CI of sum(numerators)/sum(denominators), resampling whole clusters.

    Deterministic for a given (seed, resamples, cluster order) on CPython's
    Mersenne Twister; the seed string is hashed by ``random.Random``.
    """
    if not clusters or resamples < 1:
        raise ValueError("bootstrap needs at least one cluster and one resample")
    rng = random.Random(seed)  # noqa: S311 - statistical resampling, not security
    k = len(clusters)
    stats = []
    for _ in range(resamples):
        num = den = 0.0
        for _ in range(k):
            a, b = clusters[rng.randrange(k)]
            num += a
            den += b
        stats.append(num / den)
    stats.sort()
    return {
        "method": "family-cluster bootstrap 95% percentile (nearest rank)",
        "low": _nearest_rank(stats, 0.025),
        "high": _nearest_rank(stats, 0.975),
        "resamples": resamples,
        "seed": seed,
        "clusters": k,
    }


def _combine(
    page_ids: Sequence[str], values: Sequence[PageMetric]
) -> dict[str, float] | dict[str, Any]:
    """Sum page counters, or return the fail-closed status of the metric."""
    applicable = [(pid, v) for pid, v in zip(page_ids, values, strict=True) if v is not None]
    if not applicable:
        return {"status": NOT_MEASURED, "reason": "no gold page in this category annotates it"}
    blocked = [
        (pid, v) for pid, v in applicable if isinstance(v, _Mark) and v.status == EVALUATOR_BLOCKED
    ]
    if blocked:
        return {
            "status": EVALUATOR_BLOCKED,
            "blocked_pages": _ratio(len(blocked), len(applicable)),
            "page_ids": [pid for pid, _ in blocked][:20],
            "reasons": sorted({v.detail for _, v in blocked if isinstance(v, _Mark)}),
        }
    unsupported = sorted({v.detail for _, v in applicable if isinstance(v, _Mark)})
    if unsupported:
        return {"status": UNSUPPORTED, "capability": unsupported}
    total: Counter[str] = Counter()
    for _, v in applicable:
        assert isinstance(v, dict)
        total.update(v)
    return {"status": MEASURED, "_sums": dict(total)}


def _render(metric: str, combined: dict[str, Any]) -> dict[str, Any]:
    if combined["status"] != MEASURED:
        return combined
    s: dict[str, float] = combined["_sums"]
    out: dict[str, Any] = {"status": MEASURED}
    if metric == "M1":
        out["micro_cer"] = _ratio(s["edits"], s["gold_chars"])
        out["runaway_capped_pages"] = _ratio(s["runaway_capped"], s["pages"])
        out[f"pages_cer_over_{PAGE_CER_THRESHOLD}"] = _ratio(s["over_threshold"], s["pages"])
    elif metric == "M1-nfkc":
        out["micro_cer"] = _ratio(s["edits"], s["gold_chars"])
    elif metric == "M1-s":
        for script in SCRIPTS:
            out[script] = _ratio(s[f"{script}.errors"], s[f"{script}.gold"])
    elif metric == "M2":
        out["precision"] = _ratio(s["tp"], s["predicted"])
        out["recall"] = _ratio(s["tp"], s["gold"])
        out["f1"] = _ratio(s["f1_num"], s["f1_den"])
    elif metric == "M3":
        for kind in TOKEN_KINDS:
            matched = s.get(f"{kind}.matched", 0)
            out[kind] = {
                "recall": _ratio(matched, s.get(f"{kind}.gold", 0)),
                "precision": _ratio(matched, s.get(f"{kind}.output", 0)),
            }
    elif metric == "M4":
        out["teds"] = _ratio(s["teds_sum"], s["table_pages"])
        out["teds_struct"] = _ratio(s["teds_struct_sum"], s["table_pages"])
    elif metric == "M4-text":
        out["cer_on_gold_table_characters"] = _ratio(s["errors"], s["chars"])
    elif metric == "M5":
        out["kendall_tau_distance"] = _ratio(s["discordant_pairs"], s["pairs"])
        out["matched_blocks"] = _ratio(s["matched_blocks"], s["gold_blocks"])
    elif metric in ("M6", "M6-raw"):
        out["recall"] = _ratio(s["recalled"], s["gold_set_chars"])
    elif metric == "M7":
        out["occluded_cer"] = _ratio(s["occluded_errors"], s["occluded_chars"])
        out["seal_leak"] = _ratio(s["leaked_seal_chars"], s["seal_chars"])
    elif metric == "M7c":
        out["detected"] = _ratio(s["detected"], s["approval_box_pages"])
    elif metric == "M8":
        out["insertion_rate"] = _ratio(s["insertions"], s["gold_chars"])
        # Characters of other scripts (kana, Cyrillic …) beyond the gold count.
        out["foreign_script_excess_rate"] = _ratio(s["foreign_excess"], s["gold_chars"])
        out["output_pua_chars"] = _ratio(s["output_pua_chars"], s["output_chars"])
    elif metric == "M9":
        out["lines_located"] = _ratio(s["matched_lines"], s["gold_lines"])
        out["iou_threshold"] = M9_IOU_THRESHOLD
    elif metric == "completion":
        out["pages_with_output"] = _ratio(s["with_output"], s["pages"])
        out["note"] = "completion is not accuracy"
    return out


_INTERNAL = (
    "M1",
    "M1-nfkc",
    "M1-s",
    "M2",
    "M3",
    "M4",
    "M4-text",
    "M5",
    "M6",
    "M6-raw",
    "M7",
    "M7c",
    "M8",
    "M9",
    "completion",
)


def _category_report(
    pages: Sequence[GoldPage],
    rows: Mapping[str, RunPage],
    page_metrics: Mapping[str, dict[str, PageMetric]],
    *,
    seed: str,
    resamples: int,
) -> dict[str, Any]:
    families = Counter(page.family_id for page in pages)
    floor = {
        "pages": len(pages),
        "families": len(families),
        "max_pages_per_family_observed": max(families.values(), default=0),
        "min_pages": MIN_CONFIRM_PAGES,
        "min_families": MIN_FAMILIES,
        "max_pages_per_family": MAX_PAGES_PER_FAMILY,
    }
    floor["met"] = bool(
        pages
        and len(pages) >= MIN_CONFIRM_PAGES
        and len(families) >= MIN_FAMILIES
        and floor["max_pages_per_family_observed"] <= MAX_PAGES_PER_FAMILY
    )
    if not pages:
        return {"publication_status": NOT_MEASURED, "sample_floor": floor}
    if any(page.synthetic for page in pages):
        status = "SYNTHETIC_NOT_PUBLISHABLE"
    elif not floor["met"]:
        status = "INSUFFICIENT_SAMPLE"
    else:
        status = "SAMPLE_FLOOR_MET_PROPOSED"

    ids = [page.page_id for page in pages]
    rendered = {
        m: _render(m, _combine(ids, [page_metrics[pid][m] for pid in ids])) for m in _INTERNAL
    }
    m1 = rendered["M1"]
    if m1["status"] == MEASURED:
        per_family: dict[str, list[float]] = {}
        for pid, page in zip(ids, pages, strict=True):
            counts = page_metrics[pid]["M1"]
            assert isinstance(counts, dict)
            acc = per_family.setdefault(page.family_id, [0.0, 0.0])
            acc[0] += counts["edits"]
            acc[1] += counts["gold_chars"]
        page_cers = sorted(
            float(c["edits"]) / float(c["gold_chars"])
            for c in (page_metrics[pid]["M1"] for pid in ids)
            if isinstance(c, dict)
        )
        m1["page_distribution"] = {
            "p50": _nearest_rank(page_cers, 0.5),
            "p90": _nearest_rank(page_cers, 0.9),
            "pages": len(page_cers),
        }
        m1["ci95"] = family_cluster_bootstrap(
            [(a, b) for a, b in per_family.values()], seed=seed, resamples=resamples
        )
    m1["nfkc_secondary"] = rendered.pop("M1-nfkc")
    rendered["M4"]["table_text_cer"] = rendered.pop("M4-text")
    rendered["M6"]["raw_codepoint_secondary"] = rendered.pop("M6-raw")
    rendered["M7"]["approval_box"] = rendered.pop("M7c")

    latencies = sorted(lat for pid in ids if (lat := rows[pid].latency_ms) is not None)
    latency: dict[str, Any] = {"pages_reporting": _ratio(len(latencies), len(ids))}
    if latencies:
        latency.update(
            status=MEASURED,
            p50_ms=_nearest_rank(latencies, 0.5),
            p95_ms=_nearest_rank(latencies, 0.95),
        )
    else:
        latency["status"] = NOT_MEASURED
    operational = {
        "completion": rendered.pop("completion"),
        "latency": latency,
        "cost": {
            "status": NOT_MEASURED,
            "reason": "receipt-based (price snapshot sha256); outside the offline harness",
        },
    }
    return {
        "publication_status": status,
        "sample_floor": floor,
        "metrics": rendered,
        "operational": operational,
    }


def _digest(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _source_sha256() -> str:
    """Digest of this harness's sources with line endings normalised to LF."""
    here = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in ("harness.py", "ko_tokens.py"):
        digest.update((here / name).read_bytes().replace(b"\r\n", b"\n"))
    return "sha256:" + digest.hexdigest()


def score(
    gold: Mapping[str, Any],
    run: Mapping[str, Any],
    evaluator_scores: Mapping[str, Any] | None = None,
    *,
    seed: str = BOOTSTRAP_SEED,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> dict[str, Any]:
    """Score one arm's run against KB1 gold. Raises on contract errors; never guesses."""
    gold_pages = parse_gold(gold)
    arm, caps, rows = parse_run(run, [page.page_id for page in gold_pages])
    page_metrics = {
        page.page_id: score_page(page, rows[page.page_id], caps, evaluator_scores)
        for page in gold_pages
    }
    categories = {
        category: _category_report(
            [page for page in gold_pages if page.category == category],
            rows,
            page_metrics,
            seed=f"{seed}:{category}",
            resamples=resamples,
        )
        for category in CATEGORIES
    }
    return {
        "schema": REPORT_SCHEMA,
        "status_note": (
            "Thresholds are preregistered proposals (KB1-PREREG DRAFT_PROPOSED), not calibrated."
            " Categories are never merged into one headline. 1 - CER is not accuracy."
        ),
        "evaluator": {
            "name": "kb1_harness",
            "repository": "ai-knowledge-compiler:research/kb1_korean_bench",
            "main_pin": None,
            "revision": HARNESS_REVISION,
            "source_sha256": _source_sha256(),
            "tokenizer_revision": TOKENIZER_REVISION,
            "normalization_revision": NORMALIZATION_REVISION,
            "m6_character_set_revision": M6_CHARACTER_SET_REVISION,
            "dataset_revision": gold.get("dataset_revision"),
            "dataset_manifest_sha256": gold.get("dataset_manifest_sha256"),
            "license": None,
            "frozen": False,
        },
        "normalization": {
            "unicode": "NFC",
            "whitespace": "removed_for_M1",
            "allowlist_revision": None,
            "compat_ideograph": "folded_primary_raw_secondary",
            "nfkc_secondary_report": True,
        },
        "statistics": {
            "ci": "family-cluster bootstrap 95% percentile",
            "resamples": resamples,
            "seed": seed,
            "per_category_seed": "<seed>:<category>",
        },
        "status_labels_ko": STATUS_LABELS_KO,
        "arm": arm,
        "inputs": {
            "gold_sha256": _digest(gold),
            "run_sha256": _digest(run),
            "evaluator_scores_sha256": (
                None if evaluator_scores is None else _digest(evaluator_scores)
            ),
        },
        "categories": categories,
    }


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score a KB1 run against KB1 gold, offline.")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--evaluator-scores", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = score(
        _load(args.gold),
        _load(args.run),
        None if args.evaluator_scores is None else _load(args.evaluator_scores),
    )
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
