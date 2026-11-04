"""Documents, licences, cases and the calibration/evaluation split.

Rules this module enforces rather than documents:

- A document without a licence record is refused, never defaulted.
- Only the three public sources this lane is cleared to build from are
  accepted (SEC EDGAR, US Government works, KOGL type 1).
- The split is decided by document *family*, so no family ever appears on both
  sides; :func:`check_split_integrity` refuses a case set where it does.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from arena.provider.safety import atomic_write_bytes

__all__ = [
    "LICENCE_IDS",
    "SPLITS",
    "Case",
    "CorpusError",
    "Document",
    "Licence",
    "assign_split",
    "check_split_integrity",
    "read_jsonl",
    "write_jsonl",
]

Split = Literal["CALIBRATION", "EVALUATION"]
SPLITS: Final[tuple[Split, Split]] = ("CALIBRATION", "EVALUATION")
SPLIT_SALT: Final = "karena-20261104-family-split-v1"

#: The only licence classes the gold builder may record. Each one is what the
#: *source* declares; none of them has been reviewed by counsel, which the
#: ``review_status`` on every record says out loud.
LICENCE_IDS: Final = frozenset(
    {
        # 17 U.S.C. 105: works of the US Government (Federal Register documents).
        "US-GOV-17USC105",
        # EDGAR filings: public records the SEC disseminates; the filer authored
        # the text, so no licence grant exists -- recorded as such, not as "free".
        "SEC-EDGAR-PUBLIC-FILING",
        # 공공누리 제1유형 (출처표시): commercial use and modification allowed with
        # attribution, read from the mark on the source page itself.
        "KOGL-TYPE-1",
    }
)
REVIEW_STATUS: Final = "DECLARED_BY_SOURCE_NOT_LEGALLY_REVIEWED"


class CorpusError(ValueError):
    """A document, case or split breaks a corpus rule."""


@dataclass(frozen=True, slots=True)
class Licence:
    licence_id: str
    basis: str
    evidence: str
    source_url: str
    attribution: str | None = None
    review_status: str = REVIEW_STATUS

    def __post_init__(self) -> None:
        if self.licence_id not in LICENCE_IDS:
            raise CorpusError(f"licence {self.licence_id!r} is not one this lane may build from")
        if not self.evidence.strip() or not self.source_url.startswith("https://"):
            raise CorpusError("a licence needs the observed evidence and an https source URL")


@dataclass(frozen=True, slots=True)
class Document:
    doc_id: str
    origin: str
    family_id: str
    label: str | None
    language: str
    url: str
    fetched_at: str
    raw_sha256: str
    text: str
    licence: Licence
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise CorpusError(f"{self.doc_id}: empty text is not a document")
        if not self.family_id:
            raise CorpusError(f"{self.doc_id}: family_id is required for the split")

    @property
    def split(self) -> Split:
        return assign_split(self.family_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Document:
        licence = raw.get("licence")
        if not isinstance(licence, Mapping):
            raise CorpusError(f"{raw.get('doc_id')}: no licence record; refused")
        values = dict(raw)
        values["licence"] = Licence(**licence)
        values["meta"] = dict(raw.get("meta") or {})
        return cls(**values)


@dataclass(frozen=True, slots=True)
class Case:
    """Masterplan v5 Appendix A.1, for a text task."""

    case_id: str
    task: str
    split: Split
    family_ids: tuple[str, ...]
    origin: str
    language: str
    source_doc_ids: tuple[str, ...]
    licences: tuple[str, ...]
    input: Mapping[str, Any]
    truth: Mapping[str, Any]

    def input_sha256(self) -> str:
        body = json.dumps(self.input, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Case:
        values = dict(raw)
        for key in ("family_ids", "source_doc_ids", "licences"):
            values[key] = tuple(values[key])
        return cls(**values)


def assign_split(family_id: str) -> Split:
    """Deterministic, family-level split. No PRNG, no state."""

    digest = hashlib.sha256(f"{SPLIT_SALT}:{family_id}".encode()).digest()
    return SPLITS[digest[0] & 1]


def check_split_integrity(cases: Iterable[Case]) -> None:
    """Refuse a case set where a family crosses the split or a case lies about its side."""

    seen: dict[str, Split] = {}
    for case in cases:
        if not case.licences:
            raise CorpusError(f"{case.case_id}: a case without a licence record is refused")
        for family in case.family_ids:
            expected = assign_split(family)
            if expected != case.split:
                raise CorpusError(
                    f"{case.case_id}: family {family!r} belongs to {expected}, "
                    f"case says {case.split}"
                )
            previous = seen.setdefault(family, case.split)
            if previous != case.split:
                raise CorpusError(f"family {family!r} appears in both splits")


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> str:
    body = "".join(
        json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in records
    )
    return atomic_write_bytes(path, body.encode("utf-8"))


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)
