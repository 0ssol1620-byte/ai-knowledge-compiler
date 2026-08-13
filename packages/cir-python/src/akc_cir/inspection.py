"""Post-parse inspection: deciding whether output that exists is output that is right.

Masterplan §N8 and §N9. Invariant 5 states the premise: *parser output이 존재한다고
성공이 아니다.* A parser that returns markdown has returned markdown; whether the
markdown is the document is a separate question, and this module is where it gets
asked.

Three rules shape everything here, and each is a reaction to something that has
already gone wrong.

**No single quality score.** §N9 opens with *단일 quality score를 금지하고 detector
vector를 저장한다*, and the campaign is why: a blind quality detector was built,
tested against 5,132 documents, and the hypothesis was not supported. Collapsing
seven independent signals into one number is what made that detector unable to
say *which* thing was wrong, and a number that cannot name its own cause cannot
route a recovery. So `InspectionResult` has no scalar quality field, deliberately.

**Blank source and empty output are different facts.** §2.6 lists this as a known
weakness of the existing harness, and it cost real work: two documents were scored
as empty when they were not, and one was scored as a failure when the page was
genuinely blank. §N9.2 fixes the rule -- empty output is only acceptable when a
blank classifier says the page was probably blank -- and §N9.1 makes the opposite
case a hard fail. The third case, where blankness is simply unknown, is neither:
it is `UNKNOWN_REFERENCE`, and it escalates rather than resolving in either
direction. Guessing is what produced both errors.

**The thresholds here are not calibrated.** §N9.9 sets launch targets (catastrophic
recall 100%, overall failure recall >= 95%, false escalation <= 15%) and says
plainly: *이 수치는 launch internal target이며 달성 전 외부 claim 금지.* Nothing in
this module has been measured against a labelled corpus, so `CalibrationTable`
carries `calibrated=False` and every result it produces says so. A probability
presented as calibrated when it is not is the same mistake the blind detector
made, dressed better.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

__all__ = [
    "CATASTROPHIC_CODES",
    "SECURITY_CODES",
    "CalibrationTable",
    "DetectorSignal",
    "FailureCode",
    "FailureEvent",
    "InspectionResult",
    "InspectionStatus",
    "Severity",
    "SourceScope",
    "Stage",
    "correlate_failures",
    "detect_completeness",
    "detect_duplication",
    "detect_garble",
    "detect_reading_order",
    "detect_table",
    "inspect_output",
]


class FailureCode(StrEnum):
    """§14's F0-F28 plus §N8's F29-F48.

    One flat vocabulary on purpose. §N8's subtitle is *Detection·Recovery와 1:1
    연결*: a code that the inspector can raise but the recovery policy has no
    entry for is a failure that gets detected and then dropped.
    """

    # -- source and transport ------------------------------------------
    F0_SOURCE_CORRUPT = "F0_SOURCE_CORRUPT"
    F1_SOURCE_UNSUPPORTED = "F1_SOURCE_UNSUPPORTED"
    F2_UPLOAD_STORAGE = "F2_UPLOAD_STORAGE"
    F3_QUEUE_TIMEOUT = "F3_QUEUE_TIMEOUT"
    F4_WORKER_LOST = "F4_WORKER_LOST"
    F5_MODEL_INIT = "F5_MODEL_INIT"
    F6_MODEL_OOM = "F6_MODEL_OOM"
    F7_PARSER_EXCEPTION = "F7_PARSER_EXCEPTION"
    # -- output quality ------------------------------------------------
    F8_EMPTY_OUTPUT = "F8_EMPTY_OUTPUT"
    F9_SUSPICIOUSLY_SHORT = "F9_SUSPICIOUSLY_SHORT"
    F10_DUPLICATED_CONTENT = "F10_DUPLICATED_CONTENT"
    F11_GARBLED_TEXT = "F11_GARBLED_TEXT"
    F12_READING_ORDER = "F12_READING_ORDER"
    F13_TABLE_STRUCTURE = "F13_TABLE_STRUCTURE"
    F14_FORMULA = "F14_FORMULA"
    F15_FIGURE_CAPTION = "F15_FIGURE_CAPTION"
    F16_CROSS_PAGE = "F16_CROSS_PAGE"
    F17_NATIVE_RENDER_DISAGREEMENT = "F17_NATIVE_RENDER_DISAGREEMENT"
    F18_PARSER_DISAGREEMENT = "F18_PARSER_DISAGREEMENT"
    # -- knowledge integrity -------------------------------------------
    F19_ENTITY_AMBIGUITY = "F19_ENTITY_AMBIGUITY"
    F20_AUTHORITY_CONFLICT = "F20_AUTHORITY_CONFLICT"
    F21_TEMPORAL_UNCERTAINTY = "F21_TEMPORAL_UNCERTAINTY"
    F22_LINEAGE_BROKEN = "F22_LINEAGE_BROKEN"
    F23_DEPENDENCY_CYCLE_OR_EXPLOSION = "F23_DEPENDENCY_CYCLE_OR_EXPLOSION"
    F24_RECOMPILE_DIVERGENCE = "F24_RECOMPILE_DIVERGENCE"
    F25_PERMISSION_VIOLATION = "F25_PERMISSION_VIOLATION"
    F26_STALE_WORLD_STATE = "F26_STALE_WORLD_STATE"
    F27_COST_BUDGET_EXCEEDED = "F27_COST_BUDGET_EXCEEDED"
    F28_SECURITY_BLOCKED = "F28_SECURITY_BLOCKED"
    # -- §N8 additions --------------------------------------------------
    F29_PROMPT_INJECTION_SUSPECTED = "F29_PROMPT_INJECTION_SUSPECTED"
    F30_DATA_POISONING_OR_POLICY_SMUGGLING = "F30_DATA_POISONING_OR_POLICY_SMUGGLING"
    F31_SCHEMA_INCOMPATIBLE = "F31_SCHEMA_INCOMPATIBLE"
    F32_MODEL_OR_CONTAINER_UNVERIFIED = "F32_MODEL_OR_CONTAINER_UNVERIFIED"
    F33_LICENSE_NOT_APPROVED = "F33_LICENSE_NOT_APPROVED"
    F34_EVENT_DUPLICATE_OR_OUT_OF_ORDER = "F34_EVENT_DUPLICATE_OR_OUT_OF_ORDER"
    F35_WORLD_STATE_PUBLISH_RACE = "F35_WORLD_STATE_PUBLISH_RACE"
    F36_RLS_OR_TENANT_CONTEXT_MISSING = "F36_RLS_OR_TENANT_CONTEXT_MISSING"
    F37_RETRIEVAL_FILTER_RECALL_FAILURE = "F37_RETRIEVAL_FILTER_RECALL_FAILURE"
    F38_DELETE_OR_RETENTION_INCOMPLETE = "F38_DELETE_OR_RETENTION_INCOMPLETE"
    F39_BACKUP_RESTORE_VALIDATION_FAILED = "F39_BACKUP_RESTORE_VALIDATION_FAILED"
    F40_CONNECTOR_PERMISSION_DRIFT = "F40_CONNECTOR_PERMISSION_DRIFT"
    F41_EMBEDDING_VERSION_MIXED = "F41_EMBEDDING_VERSION_MIXED"
    F42_MODEL_UPGRADE_REGRESSION = "F42_MODEL_UPGRADE_REGRESSION"
    F43_HUMAN_REVIEW_STALE_OR_CONFLICTED = "F43_HUMAN_REVIEW_STALE_OR_CONFLICTED"
    F44_EXTERNAL_REFERENCE_UNAVAILABLE = "F44_EXTERNAL_REFERENCE_UNAVAILABLE"
    F45_ACTIVE_CONTENT_OR_MALWARE = "F45_ACTIVE_CONTENT_OR_MALWARE"
    F46_ARTIFACT_CHECKSUM_MISMATCH = "F46_ARTIFACT_CHECKSUM_MISMATCH"
    F47_PROVENANCE_SIGNATURE_INVALID = "F47_PROVENANCE_SIGNATURE_INVALID"
    F48_RATE_LIMIT_OR_ABUSE = "F48_RATE_LIMIT_OR_ABUSE"


class Severity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SourceScope(StrEnum):
    """How wide the failure is. §N8 distinguishes local from provider-wide.

    The campaign learned this one expensively: four pods were deleted because a
    provider-wide stop was read as four independent worker failures.
    """

    PAGE = "page"
    DOCUMENT = "document"
    WORKSPACE = "workspace"
    TENANT = "tenant"
    PROVIDER = "provider"


class Stage(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    PARSE = "PARSE"
    INSPECTOR = "INSPECTOR"
    RECONCILE = "RECONCILE"
    COMPILE = "COMPILE"
    PUBLISH = "PUBLISH"
    RETRIEVAL = "RETRIEVAL"


class InspectionStatus(StrEnum):
    PASS = "PASS"  # noqa: S105 -- an inspection verdict, not a credential
    SUSPICIOUS = "SUSPICIOUS"
    FAIL = "FAIL"


#: §N9.1's hard-fail list. These need no threshold calibration to be wrong, and
#: a run that produced one is not a run whose other numbers mean anything.
CATASTROPHIC_CODES = frozenset(
    {
        FailureCode.F8_EMPTY_OUTPUT,
        FailureCode.F25_PERMISSION_VIOLATION,
        FailureCode.F24_RECOMPILE_DIVERGENCE,
        FailureCode.F31_SCHEMA_INCOMPATIBLE,
        FailureCode.F32_MODEL_OR_CONTAINER_UNVERIFIED,
        FailureCode.F33_LICENSE_NOT_APPROVED,
        FailureCode.F36_RLS_OR_TENANT_CONTEXT_MISSING,
        FailureCode.F45_ACTIVE_CONTENT_OR_MALWARE,
        FailureCode.F46_ARTIFACT_CHECKSUM_MISMATCH,
        FailureCode.F47_PROVENANCE_SIGNATURE_INVALID,
    }
)

#: §N11.2 -- a security failure is blocked, never retried. Retrying a poisoned
#: document is running it again.
SECURITY_CODES = frozenset(
    {
        FailureCode.F28_SECURITY_BLOCKED,
        FailureCode.F29_PROMPT_INJECTION_SUSPECTED,
        FailureCode.F30_DATA_POISONING_OR_POLICY_SMUGGLING,
        FailureCode.F45_ACTIVE_CONTENT_OR_MALWARE,
    }
)

#: §N9.2's marker for a detector that had nothing to compare against. Not a
#: score of zero and not a pass: a statement that the question was unanswerable.
UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"

_REPLACEMENT = re.compile(r"[�]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class DetectorSignal:
    """One detector's finding, with the numbers it was computed from.

    `raw` is kept because §N9.8 says *detector raw values를 삭제하지 않는다*. A
    ratio without its numerator and denominator cannot be re-derived, and a
    finding that cannot be re-derived cannot be disputed by a reviewer who thinks
    it is wrong.
    """

    code: FailureCode
    score: float
    hard_fail: bool = False
    detail: str = ""
    evidence_refs: tuple[str, ...] = ()
    raw: Mapping[str, float | str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"{self.code}: detector score must be within 0..1")

    @property
    def signature(self) -> str:
        """A stable id for *this kind of failure*, not this occurrence.

        §N8 uses the signature to tell a local failure from a provider-wide one:
        the same signature appearing across unrelated documents and workers at
        the same moment is one incident, not many.
        """
        body = f"{self.code.value}\x1e{self.detail}"
        return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class FailureEvent:
    """§N8's failure event contract."""

    failure_id: str
    code: FailureCode
    stage: Stage
    severity: Severity
    confidence: float
    source_scope: SourceScope
    signature: str
    recoverable: bool = True
    evidence_refs: tuple[str, ...] = ()
    policy_id: str = ""
    first_seen_at: datetime | None = None
    correlated_group_id: str | None = None

    def as_record(self) -> dict[str, object]:
        return {
            "failure_id": self.failure_id,
            "code": self.code.value,
            "stage": self.stage.value,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "source_scope": self.source_scope.value,
            "evidence_refs": list(self.evidence_refs),
            "signature": self.signature,
            "recoverable": self.recoverable,
            "policy_id": self.policy_id,
            "first_seen_at": (
                self.first_seen_at.isoformat() if self.first_seen_at else None
            ),
            "correlated_group_id": self.correlated_group_id,
        }


@dataclass(frozen=True, slots=True)
class CalibrationTable:
    """§N9.8's per-route thresholds, and an honest statement of their provenance.

    `calibrated` is False until these numbers come from a labelled corpus. It is
    not a formality: §N9.9's targets are internal and *달성 전 외부 claim 금지*,
    and the campaign already produced one detector whose confident-looking score
    was not supported by its own evaluation. A threshold nobody measured is a
    guess, and a guess that says so is usable while a guess that does not is not.
    """

    route_class: str = "default"
    document_type: str = "default"
    catastrophic_threshold: float = 0.90
    suspicious_threshold: float = 0.45
    calibrated: bool = False
    calibrated_from: str = ""

    def __post_init__(self) -> None:
        if not 0.0 < self.suspicious_threshold <= self.catastrophic_threshold <= 1.0:
            raise ValueError(
                "thresholds must satisfy 0 < suspicious <= catastrophic <= 1"
            )
        if self.calibrated and not self.calibrated_from:
            raise ValueError(
                "a calibrated table must name the corpus it was calibrated from"
            )


@dataclass(frozen=True, slots=True)
class InspectionResult:
    """The detector vector and what it adds up to.

    There is no scalar quality field, and its absence is the point. §N9 forbids
    one, and the reason sits in the campaign record: a single score cannot say
    which of seven independent things went wrong, so it cannot route a recovery.
    """

    status: InspectionStatus
    severity: Severity
    signals: tuple[DetectorSignal, ...]
    calibration: CalibrationTable
    unknown_references: tuple[str, ...] = ()

    @property
    def codes(self) -> tuple[FailureCode, ...]:
        return tuple(signal.code for signal in self.signals)

    @property
    def thresholds_are_calibrated(self) -> bool:
        return self.calibration.calibrated

    def signal(self, code: FailureCode) -> DetectorSignal | None:
        for candidate in self.signals:
            if candidate.code is code:
                return candidate
        return None

    def recommended_action(self) -> str:
        """§15.2's field. The highest-scoring signal names the recovery to try.

        Deliberately the *cause*, not a severity: `RECOVERY_REROUTE_TABLE` tells
        the policy engine which ladder to walk, where `HIGH` tells it nothing.
        """
        if self.status is InspectionStatus.PASS:
            return "ACCEPT"
        ranked = sorted(
            self.signals, key=lambda s: (not s.hard_fail, -s.score, s.code.value)
        )
        return f"RECOVERY_FOR_{ranked[0].code.value}" if ranked else "ACCEPT"

    def as_record(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "severity": self.severity.value,
            "signals": [
                {
                    "code": s.code.value,
                    "score": s.score,
                    "hard_fail": s.hard_fail,
                    "detail": s.detail,
                    "raw": dict(s.raw),
                }
                for s in self.signals
            ],
            "recommended_action": self.recommended_action(),
            "thresholds_calibrated": self.calibration.calibrated,
            "unknown_references": list(self.unknown_references),
        }


# ---------------------------------------------------------------------------
# §N9.2 — completeness, and the blank/empty distinction that cost the campaign
# ---------------------------------------------------------------------------


def detect_completeness(
    *,
    output_chars: int,
    reference_chars: int | None = None,
    parsed_foreground_area: float | None = None,
    expected_foreground_area: float | None = None,
    blank_probability: float | None = None,
    blank_threshold: float = 0.95,
) -> tuple[DetectorSignal | None, str | None]:
    """Did the parser return as much as the page had?

    Returns the signal and, separately, the name of any reference that was
    unavailable. §N4.4 forbids substituting a zero for a missing reference, and
    §N9.2 says to fall back to visual block coverage and mark the result
    `UNKNOWN_REFERENCE` when there is no character reference to compare against.

    The empty-output branch is the one §2.6 named as a known harness weakness.
    Three states, not two:

      source known non-blank, output empty   -> hard fail (§N9.1)
      source probably blank, output empty    -> correct; no signal
      blankness unknown, output empty        -> unanswerable; escalate

    The campaign made both of the errors this prevents. Two documents were scored
    as empty when they were not, and one page was scored as a failure when zero
    characters was the right answer.
    """
    if output_chars == 0:
        if blank_probability is None:
            return (
                DetectorSignal(
                    code=FailureCode.F8_EMPTY_OUTPUT,
                    score=0.5,
                    hard_fail=False,
                    detail=(
                        "output is empty and no blank-page classifier ran, so "
                        "whether zero characters is correct is unanswerable"
                    ),
                    raw={"output_chars": 0, "blank_probability": None},
                ),
                UNKNOWN_REFERENCE,
            )
        if blank_probability >= blank_threshold:
            return None, None
        return (
            DetectorSignal(
                code=FailureCode.F8_EMPTY_OUTPUT,
                score=1.0,
                hard_fail=True,
                detail=(
                    f"output is empty but the page is {1 - blank_probability:.0%} "
                    "likely to carry content"
                ),
                raw={"output_chars": 0, "blank_probability": blank_probability},
            ),
            None,
        )

    if reference_chars is not None and reference_chars > 0:
        char_ratio = output_chars / reference_chars
        if char_ratio < 0.6:
            return (
                DetectorSignal(
                    code=FailureCode.F9_SUSPICIOUSLY_SHORT,
                    score=min(1.0, 1.0 - char_ratio),
                    detail=(
                        f"{output_chars} chars against a {reference_chars}-char "
                        f"reference ({char_ratio:.0%})"
                    ),
                    raw={
                        "output_chars": output_chars,
                        "reference_chars": reference_chars,
                        "char_ratio": char_ratio,
                    },
                ),
                None,
            )
        return None, None

    if parsed_foreground_area is not None and expected_foreground_area:
        coverage = parsed_foreground_area / expected_foreground_area
        if coverage < 0.6:
            return (
                DetectorSignal(
                    code=FailureCode.F9_SUSPICIOUSLY_SHORT,
                    score=min(1.0, 1.0 - coverage),
                    detail=(
                        f"parsed blocks cover {coverage:.0%} of the page's "
                        "foreground area"
                    ),
                    raw={
                        "parsed_foreground_area": parsed_foreground_area,
                        "expected_foreground_area": expected_foreground_area,
                        "coverage_ratio": coverage,
                    },
                ),
                UNKNOWN_REFERENCE,
            )
        return None, UNKNOWN_REFERENCE

    return None, UNKNOWN_REFERENCE


# ---------------------------------------------------------------------------
# §N9.3 — duplication
# ---------------------------------------------------------------------------


def detect_duplication(
    text: str,
    *,
    header_lines: Sequence[str] = (),
    ngram: int = 5,
    threshold: float = 0.30,
) -> DetectorSignal | None:
    """A decoder that fell into a loop repeats itself, and it is visible.

    Headers and footers repeat legitimately on every page, so they are excluded
    by name rather than by heuristic. §N9.3 also warns that legal documents
    repeat boilerplate on purpose; the threshold is a per-document-type
    calibration input, not a constant this module believes in.
    """
    excluded = {line.strip() for line in header_lines if line.strip()}
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and line.strip() not in excluded
    ]
    if not lines:
        return None

    body = " ".join(lines)
    tokens = _WORD.findall(body.casefold())
    if len(tokens) < ngram * 2:
        return None

    grams = [tuple(tokens[i : i + ngram]) for i in range(len(tokens) - ngram + 1)]
    counts = Counter(grams)
    repeated = sum(count - 1 for count in counts.values() if count > 1)
    dup_ratio = repeated / len(grams)

    if dup_ratio < threshold:
        return None
    return DetectorSignal(
        code=FailureCode.F10_DUPLICATED_CONTENT,
        score=min(1.0, dup_ratio),
        detail=f"{dup_ratio:.0%} of {ngram}-grams repeat outside header lines",
        raw={
            "dup_ratio": dup_ratio,
            "ngram": ngram,
            "total_ngrams": len(grams),
            "repeated_ngrams": repeated,
        },
    )


# ---------------------------------------------------------------------------
# §N9.4 — garble
# ---------------------------------------------------------------------------


def detect_garble(
    text: str,
    *,
    expected_scripts: frozenset[str] = frozenset(),
    threshold: float = 0.02,
) -> DetectorSignal | None:
    """Replacement characters, control bytes and scripts that should not be here.

    `expected_scripts` comes from the profiler. When it is empty the script check
    is skipped rather than assumed: a document this pipeline has never profiled
    is not evidence that its script is wrong.
    """
    if not text:
        return None
    replacements = len(_REPLACEMENT.findall(text))
    controls = len(_CONTROL.findall(text))
    ratio = (replacements + controls) / len(text)

    foreign = 0
    if expected_scripts:
        for char in text:
            if not char.isalpha():
                continue
            try:
                script = unicodedata.name(char).split()[0]
            except ValueError:
                continue
            if script not in expected_scripts:
                foreign += 1
        letters = sum(1 for char in text if char.isalpha())
        foreign_ratio = foreign / letters if letters else 0.0
    else:
        foreign_ratio = 0.0

    worst = max(ratio, foreign_ratio)
    if worst < threshold:
        return None
    return DetectorSignal(
        code=FailureCode.F11_GARBLED_TEXT,
        score=min(1.0, worst / max(threshold, 1e-9) / 10),
        detail=(
            f"{replacements} replacement and {controls} control characters "
            f"in {len(text)} ({ratio:.2%})"
            + (
                f"; {foreign_ratio:.2%} of letters outside the profiled scripts"
                if expected_scripts
                else ""
            )
        ),
        raw={
            "replacement_chars": replacements,
            "control_chars": controls,
            "replacement_ratio": ratio,
            "foreign_script_ratio": foreign_ratio if expected_scripts else None,
        },
    )


# ---------------------------------------------------------------------------
# §N9.5 — reading order
# ---------------------------------------------------------------------------


def detect_reading_order(
    emitted_order: Sequence[int],
    *,
    threshold: float = 0.10,
) -> DetectorSignal | None:
    """How far the emitted sequence is from the expected one.

    `emitted_order` holds each emitted block's index in the geometrically
    expected order. A correct parse is `0, 1, 2, ...`; a two-column page read
    across instead of down produces interleaving, which shows up as inversions.

    Normalised inversion count rather than raw backward jumps: one block that
    jumped to the end is a small error, while a wholesale column interleave is a
    large one, and counting jumps alone scores them the same.
    """
    n = len(emitted_order)
    if n < 2:
        return None
    inversions = sum(
        1
        for i in range(n)
        for j in range(i + 1, n)
        if emitted_order[i] > emitted_order[j]
    )
    worst = n * (n - 1) / 2
    ratio = inversions / worst if worst else 0.0
    if ratio < threshold:
        return None
    backward = sum(
        1 for i in range(1, n) if emitted_order[i] < emitted_order[i - 1]
    )
    return DetectorSignal(
        code=FailureCode.F12_READING_ORDER,
        score=min(1.0, ratio * 2),
        detail=(
            f"{inversions} of {int(worst)} block pairs are out of order "
            f"({ratio:.0%}), with {backward} backward jumps"
        ),
        raw={
            "inversions": inversions,
            "max_inversions": worst,
            "inversion_ratio": ratio,
            "backward_jumps": backward,
        },
    )


# ---------------------------------------------------------------------------
# §N9.6 — tables
# ---------------------------------------------------------------------------


def detect_table(
    *,
    visual_table_probability: float | None,
    emitted_tables: int,
    row_lengths: Sequence[int] = (),
    threshold: float = 0.70,
) -> tuple[DetectorSignal | None, str | None]:
    """A table the page has and the output does not, or a grid that is not one.

    `visual_table_probability` is `None` when no layout model ran. §N4.4 again:
    that is not a probability of zero, and inferring "no table" from "nobody
    looked" is how a missing table becomes a clean pass.
    """
    if row_lengths:
        widths = set(row_lengths)
        if len(widths) > 1:
            spread = (max(widths) - min(widths)) / max(widths)
            if spread > 0.0:
                return (
                    DetectorSignal(
                        code=FailureCode.F13_TABLE_STRUCTURE,
                        score=min(1.0, spread),
                        detail=(
                            f"rows have {sorted(widths)} cells; a grid with "
                            "ragged rows did not round-trip"
                        ),
                        raw={
                            "row_lengths": ",".join(str(v) for v in row_lengths),
                            "width_spread": spread,
                        },
                    ),
                    None,
                )

    if visual_table_probability is None:
        return None, UNKNOWN_REFERENCE
    if visual_table_probability >= threshold and emitted_tables == 0:
        return (
            DetectorSignal(
                code=FailureCode.F13_TABLE_STRUCTURE,
                score=visual_table_probability,
                detail=(
                    f"the page is {visual_table_probability:.0%} likely to hold a "
                    "table and the output has none"
                ),
                raw={
                    "visual_table_probability": visual_table_probability,
                    "emitted_tables": emitted_tables,
                },
            ),
            None,
        )
    return None, None


# ---------------------------------------------------------------------------
# §N9.8 — aggregation
# ---------------------------------------------------------------------------


def inspect_output(
    signals: Iterable[DetectorSignal],
    *,
    calibration: CalibrationTable | None = None,
    unknown_references: Iterable[str] = (),
) -> InspectionResult:
    """Turn a detector vector into a status, and say what the status rests on.

    §N9.8's shape exactly: any hard fail is a FAIL, a catastrophic-risk score
    above the table's threshold is a FAIL, anything above the suspicious
    threshold is SUSPICIOUS, and the rest passes.

    The risk combination is a noisy-or rather than a maximum or a mean. Three
    independent detectors each at 0.5 are more worrying than one at 0.5, and a
    mean would say the opposite. It is not a calibrated probability and the
    result says so.
    """
    table = calibration or CalibrationTable()
    ordered = tuple(sorted(signals, key=lambda s: (not s.hard_fail, -s.score, s.code)))
    unknowns = tuple(dict.fromkeys(ref for ref in unknown_references if ref))

    if not ordered:
        return InspectionResult(
            status=InspectionStatus.PASS,
            severity=Severity.INFO,
            signals=(),
            calibration=table,
            unknown_references=unknowns,
        )

    if any(signal.hard_fail for signal in ordered):
        return InspectionResult(
            status=InspectionStatus.FAIL,
            severity=Severity.CRITICAL,
            signals=ordered,
            calibration=table,
            unknown_references=unknowns,
        )

    catastrophic = [s for s in ordered if s.code in CATASTROPHIC_CODES]
    catastrophic_risk = _noisy_or(s.score for s in catastrophic)
    if catastrophic_risk >= table.catastrophic_threshold:
        return InspectionResult(
            status=InspectionStatus.FAIL,
            severity=Severity.CRITICAL,
            signals=ordered,
            calibration=table,
            unknown_references=unknowns,
        )

    combined = _noisy_or(s.score for s in ordered)
    if combined >= table.suspicious_threshold:
        return InspectionResult(
            status=InspectionStatus.SUSPICIOUS,
            severity=Severity.HIGH if combined >= 0.75 else Severity.MEDIUM,
            signals=ordered,
            calibration=table,
            unknown_references=unknowns,
        )

    return InspectionResult(
        status=InspectionStatus.PASS,
        severity=Severity.LOW,
        signals=ordered,
        calibration=table,
        unknown_references=unknowns,
    )


def _noisy_or(scores: Iterable[float]) -> float:
    """1 - Π(1 - s). Independent evidence accumulates instead of averaging out."""
    product = 1.0
    for score in scores:
        product *= 1.0 - max(0.0, min(1.0, score))
    return 1.0 - product


# ---------------------------------------------------------------------------
# §N8 — one incident or many
# ---------------------------------------------------------------------------


def correlate_failures(
    events: Sequence[FailureEvent],
    *,
    window_seconds: float = 120.0,
    minimum_distinct_workers: int = 3,
    workers: Mapping[str, str] | None = None,
) -> dict[str, SourceScope]:
    """Decide whether repeated failures are one incident or many.

    §N8: *동일 signature가 반복되는지, 여러 worker에서 동시에 발생하는지로 local
    failure와 provider-wide failure를 구분한다.* The campaign paid for this
    distinction -- a provider-wide stop was read as several independent worker
    failures, and four pods were deleted on the strength of that reading.

    Returns signature -> scope. A signature seen on enough distinct workers
    inside the window is a provider incident; anything else stays at the scope
    the event itself claimed.
    """
    assignment = workers or {}
    by_signature: dict[str, list[FailureEvent]] = {}
    for event in events:
        by_signature.setdefault(event.signature, []).append(event)

    verdict: dict[str, SourceScope] = {}
    for signature, group in by_signature.items():
        stamps = [e.first_seen_at for e in group if e.first_seen_at is not None]
        distinct = {assignment.get(e.failure_id, e.failure_id) for e in group}
        widest = max((e.source_scope for e in group), key=_scope_rank)
        simultaneous = (
            len(stamps) >= 2
            and (max(stamps) - min(stamps)).total_seconds() <= window_seconds
        )
        if len(distinct) >= minimum_distinct_workers and simultaneous:
            verdict[signature] = SourceScope.PROVIDER
            continue
        verdict[signature] = widest
    return verdict


_SCOPE_ORDER = {
    SourceScope.PAGE: 0,
    SourceScope.DOCUMENT: 1,
    SourceScope.WORKSPACE: 2,
    SourceScope.TENANT: 3,
    SourceScope.PROVIDER: 4,
}


def _scope_rank(scope: SourceScope) -> int:
    return _SCOPE_ORDER[scope]
