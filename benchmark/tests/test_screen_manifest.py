from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from benchmark.screen.manifest import (
    EG04_MIN_DOCS,
    EG04_MIN_PAGES,
    EG04_STRATA,
    PROFILES,
    SEC_LICENCE,
    HoldoutGuard,
    HoldoutSealedError,
    assign_split,
    freeze,
    main,
    verify,
)
from benchmark.v6.contracts import ContractError, canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "benchmark" / "schemas" / "screen-manifest.schema.json"
RECIPE_A = "sha256:" + "a" * 64
RECIPE_B = "sha256:" + "b" * 64


def _digest(tag: str) -> str:
    return "sha256:" + hashlib.sha256(tag.encode()).hexdigest()


def _doc(
    i: int, stratum: str = "s0", pages: int = 2, lang: str = "ko", cls: str = "c0"
) -> dict[str, Any]:
    return {
        "doc_id": f"d{i:04d}.pdf",
        "source_sha256": _digest(f"doc{i}"),
        "byte_size": 100 + i,
        "page_count": pages,
        "stratum": stratum,
        "language": lang,
        "document_class": cls,
        "rights": {
            "source_url": f"https://example.invalid/{i}",
            "licence_id": "CC0-1.0",
            "licence_snapshot_sha256": _digest(f"lic{i}"),
            "rights_class": "public_domain",
            "redistribution": True,
            "recorded_by": "tester",
            "recorded_at": "2026-11-16T00:00:00Z",
        },
    }


def _screen_docs() -> list[dict[str, Any]]:
    # 4 strata x 50 docs x 2 pages = 400 pages
    return [_doc(i, stratum=f"s{i % 4}") for i in range(200)]


def _frozen() -> dict[str, Any]:
    return freeze(assign_split(_screen_docs(), "salt"), "salt")


def test_split_counts_and_both_splits_per_stratum() -> None:
    m = _frozen()
    c = m["counts"]
    assert c["dev_pages"] >= 300 and 100 <= c["holdout_pages"] <= 110
    assert c["dev_pages"] + c["holdout_pages"] == 400
    for s in {"s0", "s1", "s2", "s3"}:
        splits = {d["split"] for d in m["documents"] if d["stratum"] == s}
        assert splits == {"dev", "holdout"}
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(m, json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_split_is_independent_of_input_order() -> None:
    docs = _screen_docs()
    a = {d["doc_id"]: d["split"] for d in assign_split(docs, "salt")}
    docs = docs[57:] + docs[:57][::-1]
    b = {d["doc_id"]: d["split"] for d in assign_split(docs, "salt")}
    assert a == b
    c = {d["doc_id"]: d["split"] for d in assign_split(docs, "other-salt")}
    assert a != c


def test_split_is_independent_of_pythonhashseed() -> None:
    code = (
        "import hashlib,sys;sys.path.insert(0,'.');"
        "from benchmark.tests.test_screen_manifest import _screen_docs;"
        "from benchmark.screen.manifest import assign_split;"
        "print(hashlib.sha256(''.join(d['doc_id']+d['split'] for d in "
        "sorted(assign_split(_screen_docs(),'salt'),"
        "key=lambda d:d['doc_id'])).encode()).hexdigest())"
    )
    outs = set()
    for seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"}
        r = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        outs.add(r.stdout.strip())
    assert len(outs) == 1


def test_missing_rights_field_rejected() -> None:
    docs = _screen_docs()
    del docs[0]["rights"]["recorded_by"]
    with pytest.raises(ContractError, match="recorded_by"):
        assign_split(docs, "salt")
    docs = _screen_docs()
    del docs[0]["rights"]
    with pytest.raises(ContractError, match="rights"):
        assign_split(docs, "salt")


def test_rights_class_outside_enum_rejected() -> None:
    docs = _screen_docs()
    docs[3]["rights"]["rights_class"] = "research_only_non_commercial"
    with pytest.raises(ContractError, match="rights_class"):
        assign_split(docs, "salt")


def test_non_owned_without_licence_snapshot_rejected() -> None:
    docs = _screen_docs()
    docs[0]["rights"]["licence_snapshot_sha256"] = None
    with pytest.raises(ContractError, match="snapshot"):
        assign_split(docs, "salt")


def test_same_source_in_both_splits_rejected() -> None:
    docs = assign_split(_screen_docs(), "salt")
    dev = next(d for d in docs if d["split"] == "dev")
    twin = copy.deepcopy(dev)
    twin["doc_id"] = "twin.pdf"
    twin["split"] = "holdout"
    with pytest.raises(ContractError, match="more than one document"):
        freeze([*docs, twin], "salt")
    dup = copy.deepcopy(dev)
    with pytest.raises(ContractError, match="duplicate doc_id"):
        freeze([*docs, dup], "salt")


def test_counts_below_300_100_refuse_freeze() -> None:
    docs = assign_split(_screen_docs(), "salt")
    with pytest.raises(ContractError, match="below 300/100"):
        freeze(docs[:150], "salt")
    with pytest.raises(ContractError, match="every document assigned"):
        freeze(_screen_docs(), "salt")


def test_single_document_stratum_refused() -> None:
    docs = [*_screen_docs(), _doc(999, stratum="lonely")]
    with pytest.raises(ContractError, match="one document"):
        assign_split(docs, "salt")


def test_holdout_overshoot_beyond_10_pages_refused() -> None:
    docs = _screen_docs() + [_doc(i, stratum=f"s{i % 4}") for i in range(200, 300)]
    for d in docs:
        d["split"] = "holdout" if d["doc_id"] < "d0070" else "dev"
    with pytest.raises(ContractError, match="overshoots"):
        freeze(docs, "salt")


def _eg04_docs(
    extra_en: int = 0, offset: int = 10_000, drop: str | None = None
) -> list[dict[str, Any]]:
    """Every ADR-009 floor met exactly (per-document cap respected); `extra_en` adds English
    pages above the floors, `drop` moves one stratum's documents into en_native."""
    docs: list[dict[str, Any]] = []
    for sid, lang, floor, mind in EG04_STRATA:
        for _ in range(mind):
            docs.append(
                _doc(
                    offset + len(docs),
                    stratum="en_native" if sid == drop else sid,
                    pages=-(-floor // mind),
                    lang="en" if sid == drop or lang == "open" else lang,
                    cls=f"c{len(docs) % 10}",
                )
            )
    docs += [
        _doc(offset + len(docs) + k, stratum="en_native", pages=20, lang="en", cls="c0")
        for k in range(extra_en // 20)
    ]
    return docs


def _eg04_fails(match: str, docs: list[dict[str, Any]]) -> None:
    with pytest.raises(ContractError, match=match):
        freeze(docs, "s", profile="eg04", screen_manifest=_frozen())


def test_eg04_floor_table_sums_to_the_minimums() -> None:
    assert sum(f for _, _, f, _ in EG04_STRATA) == EG04_MIN_PAGES == 1500
    assert sum(m for _, _, _, m in EG04_STRATA) == EG04_MIN_DOCS == 150
    assert len(EG04_STRATA) == 11


def test_eg04_profile_accepts_disjoint_and_rejects_overlap_and_low_korean() -> None:
    screen = _frozen()
    ok = freeze(_eg04_docs(), "s", profile="eg04", screen_manifest=screen)
    assert ok["profile"] == "eg04"
    # 40% Korean passes once every floor is met (Korean floors alone are 625/1,500 = 41.7%)
    low_ko = freeze(_eg04_docs(extra_en=1000), "s", profile="eg04", screen_manifest=screen)
    assert low_ko["counts"]["korean_pages"] / low_ko["counts"]["pages"] < 0.4
    overlap = _eg04_docs()
    keep = {k: overlap[0][k] for k in ("stratum", "language", "document_class")}
    overlap[0] = {**copy.deepcopy(screen["documents"][0]), **keep}
    overlap[0]["doc_id"] = "x.pdf"
    overlap[0]["page_count"] = 12
    overlap[0].pop("split")
    with pytest.raises(ContractError, match="shares 1 source"):
        freeze(overlap, "s", profile="eg04", screen_manifest=screen)
    with pytest.raises(ContractError, match=r"stratum 'en_tables': page floor 225"):
        freeze(_eg04_docs(drop="en_tables"), "s", profile="eg04", screen_manifest=screen)
    with pytest.raises(ContractError, match="minimums"):
        freeze(_eg04_docs()[:100], "s", profile="eg04", screen_manifest=screen)
    with pytest.raises(ContractError, match="screen manifest"):
        freeze(_eg04_docs(), "s", profile="eg04")


def test_eg04_shortfall_in_documents_and_per_document_cap() -> None:
    docs = _eg04_docs()
    en = [d for d in docs if d["stratum"] == "en_tables"]
    # one large document cannot fill the floor: cap is ceil(225/10) = 23 pages
    for d in en[1:]:
        d["stratum"] = "en_native"
    en[0]["page_count"] = 500
    with pytest.raises(ContractError) as e:
        freeze(docs, "s", profile="eg04", screen_manifest=_frozen())
    assert "stratum 'en_tables': page floor 225 not met (23 counted)" in str(e.value)
    assert "stratum 'en_tables': minimum documents 20 not met (1 counted)" in str(e.value)


def test_eg04_unknown_stratum_language_and_synthetic_refused() -> None:
    d = _eg04_docs()
    d[0]["stratum"] = "s0"
    _eg04_fails("stratum 's0'.*unknown stratum", d)
    d = _eg04_docs()
    next(x for x in d if x["stratum"] == "ko_native")["language"] = "en"
    _eg04_fails("stratum 'ko_native'.*fixed language 'ko'", d)
    d = _eg04_docs()
    scan = next(x for x in d if x["stratum"] == "distorted")
    scan["rights"]["rights_class"] = "synthetic"
    scan["rights"]["licence_snapshot_sha256"] = None
    _eg04_fails("stratum 'distorted'.*synthetic document in a scan stratum", d)
    d = _eg04_docs()  # synthetic in a non-scan stratum counts toward no floor
    syn = next(x for x in d if x["stratum"] == "slides")
    syn["rights"]["rights_class"] = "synthetic"
    syn["rights"]["licence_snapshot_sha256"] = None
    _eg04_fails("stratum 'slides': minimum documents 10", d)
    d = _eg04_docs()  # ... except adversarial's
    syn = next(x for x in d if x["stratum"] == "adversarial")
    syn["rights"]["rights_class"] = "synthetic"
    syn["rights"]["licence_snapshot_sha256"] = None
    assert freeze(d, "s", profile="eg04", screen_manifest=_frozen())["profile"] == "eg04"
    d = _eg04_docs()  # an open stratum takes any language
    next(x for x in d if x["stratum"] == "slides")["language"] = "ko"
    assert freeze(d, "s", profile="eg04", screen_manifest=_frozen())["profile"] == "eg04"


def _real_corpus(tmp_path: Path) -> dict[str, Any]:
    docs = []
    for i in range(4):
        data = f"payload-{i}".encode()
        (tmp_path / f"f{i}.txt").write_bytes(data)
        d = _doc(i)
        d.update(
            doc_id=f"f{i}.txt",
            source_sha256="sha256:" + hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
            page_count=1,
        )
        docs.append(d)
    # profile screen floors do not apply to this verify-only fixture
    body = {"profile": "screen", "salt": "s", "counts": {}, "documents": docs}
    from benchmark.v6.contracts import canonical_sha256

    return {**body, "manifest_sha256": canonical_sha256(body)}


def test_verify_passes_then_catches_one_byte_change(tmp_path: Path) -> None:
    m = _real_corpus(tmp_path)
    verify(m, tmp_path)
    p = tmp_path / "f2.txt"
    p.write_bytes(b"payload-3")  # same length, one byte differs
    with pytest.raises(ContractError, match="byte hash mismatch"):
        verify(m, tmp_path)


def test_verify_catches_missing_file_page_count_and_tampered_manifest(tmp_path: Path) -> None:
    m = _real_corpus(tmp_path)
    with pytest.raises(ContractError, match="page count"):
        verify(m, tmp_path, page_counter=lambda _b: 2)
    tampered = copy.deepcopy(m)
    tampered["documents"][0]["page_count"] = 9
    with pytest.raises(ContractError, match="manifest_sha256"):
        verify(tampered, tmp_path)
    (tmp_path / "f1.txt").unlink()
    with pytest.raises(ContractError, match="missing"):
        verify(m, tmp_path)


def test_holdout_guard(tmp_path: Path) -> None:
    m = _frozen()
    log = tmp_path / "log" / "access.jsonl"
    guard = HoldoutGuard(m, log)
    assert guard.load("dev", "tune")
    for purpose in ("tune", "calibrate"):
        with pytest.raises(HoldoutSealedError):
            guard.load("holdout", purpose, RECIPE_A)
    with pytest.raises(HoldoutSealedError, match="frozen_recipe_sha256"):
        guard.load("holdout", "evaluate_frozen")
    assert not log.exists()  # refusals never open the seal
    docs = guard.load("holdout", "evaluate_frozen", RECIPE_A)
    assert docs and all(d["split"] == "holdout" for d in docs)
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1
    # same recipe is idempotent, including from a fresh guard on the same log
    assert HoldoutGuard(m, log).load("holdout", "evaluate_frozen", RECIPE_A) == docs
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1
    with pytest.raises(HoldoutSealedError, match="different frozen recipe"):
        HoldoutGuard(m, log).load("holdout", "evaluate_frozen", RECIPE_B)
    with pytest.raises(HoldoutSealedError):
        guard.load("holdout", "tune", RECIPE_A)  # still sealed for tuning after evaluation
    with pytest.raises(ValueError):
        guard.load("holdout", "peek")


def _mixed_corpus(total: int, strata: int = 9, max_pages: int = 30) -> list[dict[str, Any]]:
    docs, i, pages_left = [], 0, total
    while pages_left > 0:
        pc = min((i // strata * 7 + i % strata) % max_pages + 1, pages_left)
        docs.append(_doc(i, stratum=f"s{i % strata}", pages=pc))
        pages_left -= pc
        i += 1
    return docs


def test_split_hits_holdout_window_on_mixed_page_counts() -> None:
    for total in (460, 600, 1000):
        docs = _mixed_corpus(total)
        for salt in ("a", "b", "c", "d", "e"):
            m = freeze(assign_split(docs, salt), salt)
            c = m["counts"]
            assert 100 <= c["holdout_pages"] <= 110 and c["dev_pages"] >= 300, (total, salt, c)
            for s in {d["stratum"] for d in docs}:
                assert {d["split"] for d in m["documents"] if d["stratum"] == s} == {
                    "dev",
                    "holdout",
                }


def test_freeze_rejects_hand_picked_split_that_salt_does_not_assign() -> None:
    docs = assign_split(_screen_docs(), "salt")
    dev = next(d for d in docs if d["split"] == "dev" and d["stratum"] == "s0")
    hold = next(d for d in docs if d["split"] == "holdout" and d["stratum"] == "s0")
    dev["split"], hold["split"] = "holdout", "dev"  # same stratum, same pages: counts still pass
    with pytest.raises(ContractError, match="is not what salt"):
        freeze(docs, "salt")


def test_doc_id_cannot_escape_corpus_root_and_eg04_needs_intact_screen_manifest() -> None:
    for bad in ("../x.pdf", "/abs.pdf", "a/b.pdf", "..", "a\\b.pdf"):
        docs = _screen_docs()
        docs[0]["doc_id"] = bad
        with pytest.raises(ContractError, match="plain file name"):
            assign_split(docs, "salt")
    tampered = {**_frozen(), "salt": "other"}
    with pytest.raises(ContractError, match="intact manifest"):
        freeze(_eg04_docs(), "s", profile="eg04", screen_manifest=tampered)


def _held(docs: list[dict[str, Any]]) -> int:
    return sum(d["page_count"] for d in docs if d["split"] == "holdout")


def test_smallest_document_sorted_last_is_still_chosen() -> None:
    # s0/s1: 80 + 1 pages; s2: forty-six 10-page docs -> 1 + 1 + 10x10 = 102 holdout exists
    docs = [_doc(0, "s0", 80), _doc(1, "s0", 1), _doc(2, "s1", 80), _doc(3, "s1", 1)]
    docs += [_doc(10 + i, "s2", 10) for i in range(46)]
    for n in range(40):
        out = assign_split(docs, f"salt{n}")
        assert 100 <= _held(out) <= 110
        assert sum(d["page_count"] for d in out if d["split"] == "dev") >= 300


def test_assign_split_never_returns_a_short_or_long_holdout() -> None:
    def rnd(*key: object, lo: int, hi: int) -> int:  # deterministic stand-in for random
        h = hashlib.sha256(repr(key).encode()).digest()
        return lo + int.from_bytes(h[:4], "big") % (hi - lo + 1)

    raised = 0
    for trial in range(300):
        strata = rnd(trial, "k", lo=2, hi=3)
        docs = [
            _doc(i, f"s{i % strata}", rnd(trial, i, lo=5, hi=80))
            for i in range(rnd(trial, "n", lo=6, hi=14))
        ]
        try:
            out = assign_split(docs, f"salt{trial}")
        except ContractError:
            raised += 1
            continue
        assert 100 <= _held(out) <= 110
        assert sum(d["page_count"] for d in out if d["split"] == "dev") >= 300
        assert {d["split"] for d in out if d["stratum"] == "s0"} == {"dev", "holdout"}
    assert raised > 0  # the failure path is exercised, and it is a ContractError


def test_unsplittable_corpus_raises_contract_error_not_short_holdout() -> None:
    docs = [_doc(0, "s0", 60), _doc(1, "s0", 60), _doc(2, "s1", 60), _doc(3, "s1", 60)]
    docs += [_doc(10 + i, "s2", 90) for i in range(2)]
    with pytest.raises(ContractError):
        assign_split(docs, "x")


def test_exact_400_page_corpus_leaves_dev_300() -> None:
    for n in range(20):
        try:
            out = assign_split(_screen_docs(), f"s{n}")
        except ContractError:
            pytest.fail("a 400-page corpus must split to exactly 300/100")
        assert sum(d["page_count"] for d in out if d["split"] == "dev") >= 300


def test_drive_relative_doc_id_rejected() -> None:
    with pytest.raises(ContractError):
        assign_split([_doc(0), dict(_doc(1), doc_id="C:evil.pdf")], "x")


def test_public_record_needs_snapshot_and_enum_matches_schema() -> None:
    from benchmark.screen.manifest import RIGHTS_CLASSES, _check_doc

    docs = _screen_docs()
    docs[0]["rights"]["rights_class"] = "public_record"
    _check_doc(docs[0])
    docs[0]["rights"]["licence_snapshot_sha256"] = None
    with pytest.raises(ContractError, match="snapshot"):
        _check_doc(docs[0])
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    rights_props = schema["properties"]["documents"]["items"]["properties"]["rights"]["properties"]
    enum = rights_props["rights_class"]["enum"]
    assert tuple(enum) == RIGHTS_CLASSES


# ---------------------------------------------------------------- lpc_sec (WO-D02-3A, 5H-1)


def _sec(i: int, cik: int | str | None = None, data: bytes | None = None) -> dict[str, Any]:
    """One synthetic SEC source page (no real corpus is read)."""
    data = data if data is not None else f"sec-page-{i}".encode()
    d = _doc(i, stratum="en_native", pages=1, lang="en", cls="sec_10q_statement_print")
    d.update(
        doc_id=f"sec-{i:04d}.pdf",
        source_sha256="sha256:" + hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        page_origin="born_digital_html_print",
        notes="synthetic fixture",
    )
    d["rights"].update(licence_id=SEC_LICENCE, rights_class="public_record", redistribution=False)
    d["provenance"] = {
        "adsh": f"0000000{i:03d}-25-000001",
        "cik": 1000 + i if cik is None else cik,
        "form": "10-Q",
    }
    return d


def _derived(src: dict[str, Any], level: str) -> dict[str, Any]:
    d = copy.deepcopy(src)
    data = f"{src['doc_id']}:{level}".encode()
    d.update(
        doc_id=src["doc_id"].replace(".pdf", f"-{level}.pdf"),
        source_sha256="sha256:" + hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        derived_from=src["source_sha256"],
        page_origin="synthetic_degradation",
        stratum="distorted",
        degradation={"level": level, "parameters": {"dpi": 100}},
    )
    return d


def _sec_set(start: int, n: int = 33, derived: bool = False) -> list[dict[str, Any]]:
    src = [_sec(i) for i in range(start, start + n)]
    return src + [_derived(s, lv) for s in src for lv in ("scan_fair", "scan_poor")] * derived


def _dev() -> dict[str, Any]:
    return freeze(_sec_set(0, derived=True), "s", "lpc_sec", split="dev")


def test_lpc_sec_33_page_all_dev_freeze_admits_derived_pages_and_validates() -> None:
    m = freeze(_sec_set(0), "s", "lpc_sec", split="dev")
    assert m["counts"]["dev_documents"] == 33 and m["counts"]["holdout_documents"] == 0
    full = _dev()  # 33 clean + 66 derived = 99 pages, all dev
    assert full["counts"]["dev_pages"] == 99 and full["counts"]["holdout_pages"] == 0
    assert {d["split"] for d in full["documents"]} == {"dev"}
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for frozen in (m, full):
        jsonschema.validate(frozen, schema)
    assert tuple(schema["properties"]["profile"]["enum"]) == PROFILES
    bad = copy.deepcopy(full)  # the schema still refuses an unknown document field
    bad["documents"][0]["gold"] = "x"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_lpc_sec_holdout_needs_an_intact_disjoint_from() -> None:
    hold = _sec_set(100, n=5, derived=True)
    with pytest.raises(ContractError, match="needs disjoint_from"):
        freeze(hold, "s", "lpc_sec", split="holdout")
    m = freeze(hold, "s", "lpc_sec", split="holdout", disjoint_from=_dev())
    assert m["counts"]["holdout_pages"] == 15 and m["counts"]["dev_pages"] == 0
    with pytest.raises(ContractError, match="intact"):
        freeze(hold, "s", "lpc_sec", split="holdout", disjoint_from={**_dev(), "salt": "t"})


def test_lpc_sec_holdout_refuses_a_shared_company() -> None:
    hold = _sec_set(100, n=5)
    # dev page 7 is CIK 1007; zero padding is not a new company
    hold[2]["provenance"]["cik"] = "0001007"
    with pytest.raises(ContractError, match="shares 1 company"):
        freeze(hold, "s", "lpc_sec", split="holdout", disjoint_from=_dev())


def test_lpc_sec_holdout_refuses_a_shared_source_hash() -> None:
    dev = _dev()
    for twin in (
        next(d for d in dev["documents"] if "derived_from" not in d),
        next(d for d in dev["documents"] if "derived_from" in d),  # a derived page's bytes too
    ):
        hold = _sec_set(100, n=5)
        hold[0]["source_sha256"] = twin["source_sha256"]
        with pytest.raises(ContractError, match="shares 1 source sha256"):
            freeze(hold, "s", "lpc_sec", split="holdout", disjoint_from=dev)
    # a disjoint_from page derived from bytes that manifest does not itself carry
    hold = _sec_set(100, n=5)
    other = copy.deepcopy(dev)
    next(d for d in other["documents"] if "derived_from" in d)["derived_from"] = hold[0][
        "source_sha256"
    ]
    other["manifest_sha256"] = canonical_sha256(
        {k: v for k, v in other.items() if k != "manifest_sha256"}
    )
    with pytest.raises(ContractError, match="shares 1 source sha256"):
        freeze(hold, "s", "lpc_sec", split="holdout", disjoint_from=other)


def test_lpc_sec_document_without_company_or_sec_rights_refused() -> None:
    cases: list[tuple[str, Any]] = [
        (r"provenance\.cik", lambda d: d["provenance"].pop("cik")),
        (r"provenance\.cik", lambda d: d["provenance"].update(cik=True)),
        (r"provenance\.cik", lambda d: d["provenance"].update(cik=" ")),
        (r"provenance\.adsh", lambda d: d["provenance"].pop("adsh")),
        ("provenance object", lambda d: d.pop("provenance")),
        ("licence_id", lambda d: d["rights"].update(licence_id="CC0-1.0")),
        ("rights", lambda d: d.pop("rights")),
    ]
    for match, mutate in cases:
        docs = _sec_set(0)
        mutate(docs[4])
        with pytest.raises(ContractError, match=match):
            freeze(docs, "s", "lpc_sec", split="dev")
    other = _dev()  # a disjoint_from document without a company cannot prove disjointness
    del other["documents"][0]["provenance"]["cik"]
    other["manifest_sha256"] = canonical_sha256(
        {k: v for k, v in other.items() if k != "manifest_sha256"}
    )
    with pytest.raises(ContractError, match=r"provenance\.cik"):
        freeze(_sec_set(100, n=2), "s", "lpc_sec", split="holdout", disjoint_from=other)


def test_lpc_sec_one_source_page_per_company() -> None:
    docs = _sec_set(0)
    docs[5]["provenance"]["cik"] = "0001003"
    with pytest.raises(ContractError, match="company 1003 has more than one source page"):
        freeze(docs, "s", "lpc_sec", split="dev")


def test_lpc_sec_derived_page_must_follow_its_source() -> None:
    src = _sec_set(0, n=3)
    orphan = _derived(_sec(50), "scan_poor")
    with pytest.raises(ContractError, match="names no source page"):
        freeze([*src, orphan], "s", "lpc_sec", split="dev")
    moved = _derived(src[0], "scan_poor")
    moved["provenance"]["cik"] = 1001
    with pytest.raises(ContractError, match="differs from its source"):
        freeze([*src, moved], "s", "lpc_sec", split="dev")
    other_filing = _derived(src[0], "scan_poor")
    other_filing["provenance"]["adsh"] = "0000000999-25-000001"
    with pytest.raises(ContractError, match="differs from its source"):
        freeze([*src, other_filing], "s", "lpc_sec", split="dev")
    first = _derived(src[0], "scan_fair")
    of_derived = _derived(first, "scan_poor")  # names a derived page, not a source page
    with pytest.raises(ContractError, match="names no source page"):
        freeze([*src, first, of_derived], "s", "lpc_sec", split="dev")
    bad = _derived(src[0], "scan_poor")
    bad["derived_from"] = "abc"
    with pytest.raises(ContractError, match="derived_from"):
        freeze([*src, bad], "s", "lpc_sec", split="dev")


def test_lpc_sec_split_rules_and_other_profiles_take_no_split() -> None:
    docs = _sec_set(0, n=3)
    with pytest.raises(ContractError, match="needs split"):
        freeze(docs, "s", "lpc_sec")
    docs[1]["split"] = "holdout"
    with pytest.raises(ContractError, match="not the manifest's 'dev'"):
        freeze(docs, "s", "lpc_sec", split="dev")
    with pytest.raises(ContractError, match="apply to profile 'lpc_sec'"):
        freeze(assign_split(_screen_docs(), "salt"), "salt", split="dev")
    with pytest.raises(ContractError, match="apply to profile 'lpc_sec'"):
        freeze(_eg04_docs(), "s", "eg04", screen_manifest=_frozen(), disjoint_from=_dev())


def test_sec_licence_constant_matches_sec_screen() -> None:
    from benchmark.local_public import sec_screen

    assert SEC_LICENCE == sec_screen.LICENCE


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _cli(capsys: pytest.CaptureFixture[str], *argv: str | Path) -> tuple[int, str]:
    code = main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out + out.err


def test_cli_freeze_is_write_once_and_verify_catches_one_byte(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    recs = []
    for i in range(3):
        data = f"page-bytes-{i}".encode()  # not a PDF: the default page counter reads 1 page
        (corpus / f"sec-{i:04d}.pdf").write_bytes(data)
        recs.append(_sec(i, data=data))
    records = _write_jsonl(tmp_path / "records.jsonl", recs)
    out = tmp_path / "manifest.json"
    args = (
        "freeze",
        "--records",
        records,
        "--profile",
        "lpc_sec",
        "--split",
        "dev",
        "--salt",
        "s",
        "--out",
        out,
    )
    code, text = _cli(capsys, *args)
    assert code == 0, text
    frozen = out.read_bytes()
    assert json.loads(frozen)["manifest_sha256"] in text
    code, text = _cli(capsys, *args)
    assert code == 1 and "write-once" in text and out.read_bytes() == frozen
    code, text = _cli(capsys, "verify", "--manifest", out, "--corpus-root", corpus)
    assert code == 0 and '"verified": 3' in text
    p = corpus / "sec-0001.pdf"
    p.write_bytes(p.read_bytes()[:-1] + b"X")  # same length, one byte differs
    code, text = _cli(capsys, "verify", "--manifest", out, "--corpus-root", corpus)
    assert code == 1 and "byte hash mismatch" in text
    hold = _write_jsonl(tmp_path / "hold.jsonl", _sec_set(100, n=2))
    code, text = _cli(
        capsys,
        "freeze",
        "--records",
        hold,
        "--profile",
        "lpc_sec",
        "--split",
        "holdout",
        "--salt",
        "s",
        "--out",
        tmp_path / "hold.json",
    )
    assert code == 1 and "needs disjoint_from" in text and not (tmp_path / "hold.json").exists()
    code, text = _cli(
        capsys,
        "freeze",
        "--records",
        hold,
        "--profile",
        "lpc_sec",
        "--split",
        "holdout",
        "--salt",
        "s",
        "--out",
        tmp_path / "hold.json",
        "--disjoint-from",
        out,
    )
    assert code == 0, text
    assert json.loads((tmp_path / "hold.json").read_text("utf-8"))["counts"]["holdout_pages"] == 2


def test_freeze_then_split_gold_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from benchmark.local_public import sec_screen

    recs = _sec_set(0)
    records = _write_jsonl(tmp_path / "records.jsonl", recs)
    sealed = _write_jsonl(
        tmp_path / "gold.sealed.jsonl",
        [
            {
                "page_id": r["doc_id"] + "#0",
                "truth": {"critical_fields": [{"field_id": "f", "value": "1"}]},
            }
            for r in recs
        ],
    )
    out = tmp_path / "manifest.json"
    code, text = _cli(
        capsys,
        "freeze",
        "--records",
        records,
        "--profile",
        "lpc_sec",
        "--split",
        "dev",
        "--salt",
        "s",
        "--out",
        out,
    )
    assert code == 0, text
    rec = sec_screen.split_gold(out, sealed)
    assert rec["documents"] == {"dev": 33, "holdout": 0}
    assert not sealed.exists()
    dev = (tmp_path / "gold.dev.jsonl").read_text("utf-8").splitlines()
    assert sorted(json.loads(x)["page_id"] for x in dev) == sorted(r["doc_id"] + "#0" for r in recs)
    assert (tmp_path / "gold.holdout.jsonl").read_text("utf-8") == ""
