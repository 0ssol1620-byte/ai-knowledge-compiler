"""Build the public gold corpus and the four task case sets.

``python -m karena gold --execute`` fetches (cached, receipted) and writes:

    inputs/raw/<sha256>.bin, inputs/fetch_index.jsonl   every byte read
    gold/documents.jsonl                                  one licensed document per line
    gold/sec_facts.jsonl                                  values two SEC sources agree on
    gold/build_receipt.json                               quotas, counts, drops, hashes
    cases/<task>.<SPLIT>.jsonl                            Appendix A.1 cases

Everything is ordered by sha256 over a fixed seed -- no PRNG -- so a rebuild
over the same cache produces byte-identical case files.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from arena.provider.safety import utc_now_iso, write_json_atomic

from karena import CAMPAIGN_ID, NAMESPACE_ROOT
from karena.corpus import (
    SPLITS,
    Case,
    Document,
    assign_split,
    check_split_integrity,
    read_jsonl,
    write_jsonl,
)
from karena.gold import kogl, sec, usgov
from karena.gold.fetch import Fetcher
from karena.gold.htmltext import tidy

__all__ = ["BuildConfig", "build_cases", "build_gold"]

SEED: Final = "karena-20261104-gold-v1"
DOC_TYPE_CHARS: Final = 6000
BUNDLE_EXCERPT_CHARS: Final = 2500
UNANSWERABLE_EVERY: Final = 5


@dataclass(frozen=True)
class BuildConfig:
    sec_days: tuple[str, ...] = (
        "20260224",
        "20260226",
        "20260302",
        "20260401",
        "20260415",
        "20260805",
        "20260806",
    )
    sec_quota: dict[str, int] = field(
        default_factory=lambda: {"10-K": 8, "10-Q": 8, "8-K": 6, "DEF 14A": 6, "S-1": 6}
    )
    facts_per_filing: int = 4
    fr_window: tuple[str, str] = ("2026-07-01", "2026-09-30")
    fr_per_type: int = 24
    fr_quota: int = 6
    kogl_list_pages: int = 4
    kogl_limit: int = 40
    kogl_quota: int = 8
    doc_type_per_label: dict[str, int] = field(
        default_factory=lambda: {"SEC": 6, "US_GOV_FR": 4, "KOGL": 4}
    )
    cases_per_split: int = 60


def key(*parts: object) -> str:
    return sec.order_key(SEED, ":".join(str(part) for part in parts))


# ---------------------------------------------------------------- documents


def _sec(
    fetcher: Fetcher, config: BuildConfig, receipt: dict[str, Any]
) -> tuple[list[Document], list[sec.SecFact]]:
    rows: list[sec.IndexRow] = []
    for day in config.sec_days:
        rows += [
            row
            for row in sec.parse_daily_index(fetcher.get(sec.daily_index_url(day)).text())
            if row.form in config.sec_quota
        ]
    documents: list[Document] = []
    facts: list[sec.SecFact] = []
    drops: dict[str, int] = defaultdict(int)
    for form, quota in config.sec_quota.items():
        filled = dict.fromkeys(SPLITS, 0)
        seen_cik: set[int] = set()
        for row in sorted((r for r in rows if r.form == form), key=lambda r: key(r.accession)):
            if all(count >= quota for count in filled.values()):
                break
            split = assign_split(f"sec:cik:{row.cik}")
            if row.cik in seen_cik or filled[split] >= quota:
                continue
            seen_cik.add(row.cik)
            result = sec.fetch_filing(fetcher, row)
            if result is None:
                drops[f"{form}:no_html_primary"] += 1
                continue
            document, parsed = result
            if form in {"10-K", "10-Q"}:
                found, counts = sec.gold_facts(
                    fetcher, document, parsed, per_filing=config.facts_per_filing
                )
                for name, count in counts.items():
                    drops[f"facts:{name}"] += count
                if not found:
                    drops[f"{form}:no_agreed_fact"] += 1
                    continue
                facts += found
            documents.append(
                Document.from_dict({**document.to_dict(), "text": tidy(document.text)})
            )
            filled[split] += 1
        receipt["sec_filled"][form] = filled
    receipt["drops"].update(drops)
    return documents, facts


def _fill(documents: Iterable[Document], quota: int) -> list[Document]:
    filled = dict.fromkeys(SPLITS, 0)
    kept: list[Document] = []
    for document in sorted(documents, key=lambda d: key(d.doc_id)):
        if filled[document.split] < quota:
            filled[document.split] += 1
            kept.append(document)
    return kept


def build_gold(fetcher: Fetcher, config: BuildConfig) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": "tavonel.karena.gold_build_receipt.v1",
        "campaign_id": CAMPAIGN_ID,
        "started_at": utc_now_iso(),
        "seed": SEED,
        "config": {
            "sec_days": list(config.sec_days),
            "sec_quota": config.sec_quota,
            "fr_window": list(config.fr_window),
            "fr_quota": config.fr_quota,
            "kogl_quota": config.kogl_quota,
        },
        "sec_filled": {},
        "drops": {},
    }
    documents, facts = _sec(fetcher, config, receipt)
    skipped: Counter[str] = Counter()
    for type_code in usgov.FR_TYPES:
        pool = list(
            usgov.fr_documents(
                fetcher,
                type_code,
                start=config.fr_window[0],
                end=config.fr_window[1],
                limit=config.fr_per_type,
                drops=skipped,
            )
        )
        documents += [
            Document.from_dict({**d.to_dict(), "text": tidy(d.text)})
            for d in _fill(pool, config.fr_quota)
        ]
    pool = list(
        kogl.kogl_press_releases(
            fetcher,
            list_pages=config.kogl_list_pages,
            limit=config.kogl_limit,
            drops=skipped,
        )
    )
    documents += [
        Document.from_dict({**d.to_dict(), "text": tidy(d.text)})
        for d in _fill(pool, config.kogl_quota)
    ]
    receipt["drops"].update(skipped)
    gold_dir = NAMESPACE_ROOT / "gold"
    receipt["documents_sha256"] = write_jsonl(
        gold_dir / "documents.jsonl", (d.to_dict() for d in documents)
    )
    receipt["sec_facts_sha256"] = write_jsonl(
        gold_dir / "sec_facts.jsonl", (f.to_dict() for f in facts)
    )
    receipt["counts"] = _counts(documents)
    receipt["sec_fact_count"] = len(facts)
    receipt["finished_at"] = utc_now_iso()
    write_json_atomic(gold_dir / "build_receipt.json", receipt, context="gold build receipt")
    return receipt


def _counts(documents: Sequence[Document]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(SPLITS, 0))
    for document in documents:
        counts[str(document.label)][document.split] += 1
    return dict(counts)


# -------------------------------------------------------------------- cases


def build_cases(config: BuildConfig) -> dict[str, dict[str, int]]:
    gold_dir = NAMESPACE_ROOT / "gold"
    documents = [Document.from_dict(row) for row in read_jsonl(gold_dir / "documents.jsonl")]
    facts = list(read_jsonl(gold_dir / "sec_facts.jsonl"))
    by_id = {d.doc_id: d for d in documents}
    produced: dict[str, dict[str, int]] = {}
    for task, builder in (
        ("doc_type", _doc_type_cases),
        ("typed_extraction", _typed_cases),
        ("grounded_answer", _grounded_cases),
        ("schema_induction", _schema_cases),
    ):
        produced[task] = {}
        for split in SPLITS:
            cases = builder(documents, facts, by_id, split, config)
            cases = sorted(cases, key=lambda c: key(task, c.case_id))[: config.cases_per_split]
            check_split_integrity(cases)
            write_jsonl(
                NAMESPACE_ROOT / "cases" / f"{task}.{split}.jsonl", (c.to_dict() for c in cases)
            )
            produced[task][split] = len(cases)
    return produced


def _doc_type_cases(
    documents: Sequence[Document],
    facts: Sequence[dict[str, Any]],
    by_id: dict[str, Document],
    split: str,
    config: BuildConfig,
) -> list[Case]:
    del facts, by_id
    per_label: dict[str, list[Document]] = defaultdict(list)
    for document in sorted(documents, key=lambda d: key("doc_type", d.doc_id)):
        if document.split == split and document.label is not None:
            per_label[document.label].append(document)
    cases: list[Case] = []
    for label, group in sorted(per_label.items()):
        limit = config.doc_type_per_label[group[0].origin]
        for document in group[:limit]:
            cases.append(
                Case(
                    case_id=f"doc_type:{document.doc_id}",
                    task="doc_type",
                    split=document.split,
                    family_ids=(document.family_id,),
                    origin=document.origin,
                    language=document.language,
                    source_doc_ids=(document.doc_id,),
                    licences=(document.licence.licence_id,),
                    input={"text": document.text[:DOC_TYPE_CHARS]},
                    truth={"label": label},
                )
            )
    return cases


def _typed_cases(
    documents: Sequence[Document],
    facts: Sequence[dict[str, Any]],
    by_id: dict[str, Document],
    split: str,
    config: BuildConfig,
) -> list[Case]:
    del documents, config
    cases = []
    for fact in facts:
        document = by_id.get(str(fact["doc_id"]))
        if document is None or document.split != split:
            continue
        cases.append(
            Case(
                case_id=f"typed_extraction:{fact['accession']}:{fact['concept']}",
                task="typed_extraction",
                split=document.split,
                family_ids=(document.family_id,),
                origin="SEC",
                language="en",
                source_doc_ids=(document.doc_id,),
                licences=(document.licence.licence_id,),
                input={"excerpt": fact["excerpt"], "field": _field(fact, document)},
                truth={
                    "value": fact["value"],
                    "unit": fact["unit"],
                    "displayed": fact["displayed"],
                    "sources": {
                        "inline_xbrl": {"doc_url": document.url, "concept": fact["concept"]},
                        "companyconcept": {"url": fact["companyconcept_url"]},
                    },
                },
            )
        )
    return cases


def _field(fact: dict[str, Any], document: Document) -> dict[str, Any]:
    period = (
        f"the period from {fact['period_start']} to {fact['period_end']}"
        if fact["period_start"]
        else f"the date {fact['period_end']}"
    )
    return {
        "name": fact["concept"],
        "description": fact["label"],
        "entity": document.meta.get("company"),
        "period": period,
        "unit": fact["unit"],
    }


def _grounded_cases(
    documents: Sequence[Document],
    facts: Sequence[dict[str, Any]],
    by_id: dict[str, Document],
    split: str,
    config: BuildConfig,
) -> list[Case]:
    del documents, config
    pool = [f for f in facts if by_id[str(f["doc_id"])].split == split]
    pool.sort(key=lambda f: key("grounded", f["accession"], f["concept"]))
    cases = []
    for index, fact in enumerate(pool):
        document = by_id[str(fact["doc_id"])]
        others = [
            other for other in pool if by_id[str(other["doc_id"])].family_id != document.family_id
        ]
        others.sort(
            key=lambda o: key("distractor", fact["accession"], o["accession"], o["concept"])
        )
        answerable = index % UNANSWERABLE_EVERY != UNANSWERABLE_EVERY - 1
        chosen = ([fact] if answerable else []) + others[: 3 if answerable else 4]
        chosen.sort(key=lambda c: key("order", fact["accession"], c["accession"], c["concept"]))
        excerpts = []
        gold_ids: list[str] = []
        for position, item in enumerate(chosen, start=1):
            excerpt_id = f"E{position}"
            excerpts.append({"id": excerpt_id, "text": item["excerpt"]})
            if item is fact:
                gold_ids.append(excerpt_id)
        families = {document.family_id} | {by_id[str(c["doc_id"])].family_id for c in chosen}
        field_ = _field(fact, document)
        question = (
            f"What was {field_['entity']}'s {fact['label']} for {field_['period']}, "
            f"in {fact['unit']}?"
        )
        cases.append(
            Case(
                case_id=f"grounded_answer:{fact['accession']}:{fact['concept']}",
                task="grounded_answer",
                split=document.split,
                family_ids=tuple(sorted(families)),
                origin="SEC",
                language="en",
                source_doc_ids=tuple(
                    sorted({str(c["doc_id"]) for c in chosen} | {document.doc_id})
                ),
                licences=("SEC-EDGAR-PUBLIC-FILING",),
                input={"question": question, "excerpts": excerpts},
                truth={
                    "answerable": answerable,
                    "value": fact["value"] if answerable else None,
                    "unit": fact["unit"],
                    "citation_ids": gold_ids,
                },
            )
        )
    return cases


def _schema_cases(
    documents: Sequence[Document],
    facts: Sequence[dict[str, Any]],
    by_id: dict[str, Document],
    split: str,
    config: BuildConfig,
) -> list[Case]:
    del facts, by_id, config
    per_label: dict[str, list[Document]] = defaultdict(list)
    for document in sorted(documents, key=lambda d: key("schema", d.doc_id)):
        if document.split == split and document.label is not None:
            per_label[document.label].append(document)
    cases = []
    for label, group in sorted(per_label.items()):
        if len(group) < 3:
            continue
        seen: set[frozenset[str]] = set()
        for offset in range(len(group)):
            members = [group[(offset + step) % len(group)] for step in range(3)]
            member_ids = frozenset(m.doc_id for m in members)
            if member_ids in seen:
                continue
            seen.add(member_ids)
            excerpts = [
                {"id": f"D{n}", "doc_id": m.doc_id, "text": m.text[:BUNDLE_EXCERPT_CHARS]}
                for n, m in enumerate(members, start=1)
            ]
            cases.append(
                Case(
                    case_id=f"schema_induction:{label}:{offset}",
                    task="schema_induction",
                    split=members[0].split,
                    family_ids=tuple(sorted({m.family_id for m in members})),
                    origin=members[0].origin,
                    language=members[0].language,
                    source_doc_ids=tuple(m.doc_id for m in members),
                    licences=tuple(sorted({m.licence.licence_id for m in members})),
                    input={"collection_label": label, "excerpts": excerpts},
                    # The reference schema is written by a person (programme F-10);
                    # until it exists, type recall is NOT_MEASURED, never estimated.
                    truth={"reference_schema": None},
                )
            )
    return cases
