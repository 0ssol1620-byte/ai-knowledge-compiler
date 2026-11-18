"""WO-D17-3: family A (`concept_crossover`), `version` in the row index, the blind split.

Synthetic FSDS fixtures built in a temp directory and read through the real pinned-manifest
loader (`sources.Loader`), the real `pit_rows.build` and the real `pit_tasks.main`.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from akc_product_core.semantics import semantic_tokens

from benchmark.local_public import pit_rows as pr
from benchmark.local_public import pit_tasks as pt
from benchmark.local_public import sources
from benchmark.retrieval_baselines.metrics import parse_task
from benchmark.tests.test_local_public_sec_align import gold_value

# ---------------------------------------------------------------- synthetic FSDS world

K1, Q1 = "0000000001-25-000001", "0000000001-25-000002"
B2, D4, X5 = "0000000002-25-000001", "0000000004-25-000001", "0000000005-25-000001"
STD = "us-gaap/2024"
# adsh -> (cik, name, FSDS `accepted` (US Eastern wall clock), bulk acceptanceDateTime (UTC))
FILINGS = {
    K1: ("1", "ACME Corp", "2025-03-01 07:00:00.0", "2025-03-01T12:00:00.000Z"),
    Q1: ("1", "ACME Corp", "2025-08-29 16:00:00.0", "2025-08-29T20:00:00.000Z"),
    B2: ("2", "BETA Inc", "2025-08-29 16:00:00.0", "2025-08-29T20:00:00.000Z"),
    D4: ("4", "DELTA Co", "2025-08-29 16:00:00.0", "2025-08-29T20:00:00.000Z"),
}
QUARTER = {K1: "2025q1", Q1: "2025q3", B2: "2025q3", D4: "2025q3"}
# (tag, version, plabel, tlabel, custom); None tlabel = absent from tag.txt
CONCEPTS = {
    "Revenues": (STD, "Revenues", "Revenues", "0"),  # tlabel == plabel: overlap, no task
    "SalesNet": (STD, "Net sales", "Revenue From Contracts With Customers", "0"),  # admitted
    "GrossMargin": (STD, "Gross margin", "Period Profit", "0"),  # overlaps the period text only
    "AcmeRebates": (K1, "Widget rebates", "Rebate Accrual", "1"),  # custom: no task
    "OddTag": (STD, "Odd item", None, "0"),  # (tag, version) absent from tag.txt
    "ShareCount": (STD, "Common share count", "Shares Outstanding", "0"),  # inflection only
    "NewTag": (STD, "Deferred income", "Contract Liability", "0"),  # first reported in Q1
}
# adsh -> [(tag, value, ddate, qtrs)]
FACTS = {
    K1: [
        ("Revenues", "100", "20241231", "4"),
        ("SalesNet", "90", "20241231", "4"),
        ("GrossMargin", "40", "20241231", "4"),
        ("AcmeRebates", "3", "20241231", "4"),
        ("OddTag", "1", "20241231", "4"),
        ("ShareCount", "7", "20241231", "4"),
    ],
    Q1: [
        ("SalesNet", "95", "20241231", "4"),  # restated later: a `modified` task on K1's row
        ("NewTag", "5", "20250630", "2"),
    ],
    B2: [("SalesNet", "11", "20250630", "2")],
    D4: [("SalesNet", "12", "20250630", "2")],
}
SUB_COLS = ("adsh", "cik", "name", "form", "instance", "accepted")
NUM_COLS = ("adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg", "value")
PRE_COLS = ("adsh", "tag", "version", "stmt", "plabel")
TAG_COLS = ("tag", "version", "custom", "abstract", "datatype", "tlabel")


def _tsv(cols: tuple[str, ...], rows: list[dict[str, str]]) -> bytes:
    return "\n".join(
        "\t".join(r[c] for c in cols) for r in [dict(zip(cols, cols, strict=True)), *rows]
    ).encode()


def _fsds_zip(quarter: str, *, tag_txt: bool, tlabel_override: dict[str, str]) -> bytes:
    subs, nums, pres = [], [], []
    tags: dict[tuple[str, str], dict[str, str]] = {}
    for adsh, (cik, name, accepted, _) in FILINGS.items():
        if QUARTER[adsh] != quarter:
            continue
        subs.append(
            {"adsh": adsh, "cik": cik.zfill(10), "name": name, "form": "10-K",
             "instance": "x-2025.xml", "accepted": accepted}
        )  # fmt: skip
        for tag, value, ddate, qtrs in FACTS[adsh]:
            version, plabel, tlabel, custom = CONCEPTS[tag]
            nums.append(
                {"adsh": adsh, "tag": tag, "version": version, "ddate": ddate, "qtrs": qtrs,
                 "uom": "USD", "segments": "", "coreg": "", "value": value}
            )  # fmt: skip
            pres.append(
                {"adsh": adsh, "tag": tag, "version": version, "stmt": "IS", "plabel": plabel}
            )
            if tlabel is not None:
                tags[(tag, version)] = {
                    "tag": tag, "version": version, "custom": custom, "abstract": "0",
                    "datatype": "monetary", "tlabel": tlabel_override.get(tag, tlabel),
                }  # fmt: skip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("sub.txt", _tsv(SUB_COLS, subs))
        z.writestr("num.txt", _tsv(NUM_COLS, nums))
        z.writestr("pre.txt", _tsv(PRE_COLS, pres))
        if tag_txt:
            z.writestr("tag.txt", _tsv(TAG_COLS, list(tags.values())))
    return buf.getvalue()


def make_world(
    root: Path,
    *,
    no_tag_txt: tuple[str, ...] = (),
    tlabel_override: dict[str, dict[str, str]] | None = None,
) -> Path:
    """Pinned files and a valid manifest under `root`; returns the manifest path."""
    root.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {}
    for q in ("2025q1", "2025q3"):
        files[f"sec_fsds/{q}"] = _fsds_zip(
            q, tag_txt=q not in no_tag_txt, tlabel_override=(tlabel_override or {}).get(q, {})
        )
    bulk = io.BytesIO()
    with zipfile.ZipFile(bulk, "w") as z:
        for adsh, (cik, _, _, stamp) in FILINGS.items():
            recent = {"accessionNumber": [adsh], "acceptanceDateTime": [stamp]}
            z.writestr(
                f"CIK{cik.zfill(10)}-{adsh}.json", json.dumps({"filings": {"recent": recent}})
            )
    files["sec_submissions_bulk"] = bulk.getvalue()
    c2 = [{"cik": int(FILINGS[a][0]), "adsh": a} for a in FILINGS]
    c2.append({"cik": 5, "adsh": X5})  # CIK 5: a c2 filing with no FSDS row in range
    files["c2_manifest"] = "".join(json.dumps(r) + "\n" for r in c2).encode()
    entries = []
    for name, data in sorted(files.items()):
        p = root / name.replace("/", "_")
        p.write_bytes(data)
        entries.append({"name": name, "path": str(p), "sha256": hashlib.sha256(data).hexdigest()})
    manifest: dict[str, Any] = {"schema": sources.SCHEMA, "entries": entries}
    manifest["manifest_sha256"] = sources._digest(manifest)
    m = root / "manifest.json"
    m.write_text(json.dumps(manifest), "utf-8")
    return m


def ciks_file(path: Path, ciks: list[int]) -> Path:
    path.write_text(json.dumps(ciks), "utf-8")
    return path


def build_rows(tmp: Path, manifest: Path, exclude: list[int], k: int, **kw: Any) -> Path:
    out = tmp / f"rows-{len(list(tmp.glob('rows-*')))}"
    ex = ciks_file(tmp / f"{out.name}-ex.json", exclude)
    pr.build(out, ex, k, 0, manifest=manifest, gold_value=gold_value, **kw)
    return out


@pytest.fixture(autouse=True)
def _isolated_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources, "_default", None)


# ---------------------------------------------------------------- byte identity, index, labels

BASE_CORPUS_SHA256 = "6b5e8296811018fae683c85628dd1e92ed0d2d751c2d9e535beaf592984970c8"
BASE_TASKS_SHA256 = "0c4dc89e9408dc00e239f178a39771c5cd19527d07e092c053c40f80e2a6b2ff"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _lines(p: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x]


def tasks_of(tmp: Path, rows: Path, *extra: str) -> tuple[int, Path]:
    out = tmp / f"tasks-{len(list(tmp.glob('tasks-*')))}"
    return pt.main(["build", "--rows-dir", str(rows), "--out", str(out), *extra]), out


def test_corpus_and_existing_family_tasks_are_byte_identical_to_the_base(tmp_path: Path) -> None:
    """Hashes measured at 87d214a (before WO-D17-3) on this same synthetic world."""
    rows = build_rows(tmp_path, make_world(tmp_path / "w"), [4, 5], 2)
    assert _sha(rows / "corpus.jsonl") == BASE_CORPUS_SHA256
    _, out = tasks_of(tmp_path, rows)
    assert _sha(out / "tasks.jsonl") == BASE_TASKS_SHA256
    tasks = _lines(out / "tasks.jsonl")
    assert tasks and all("label_blind_query" not in t and "family" not in t for t in tasks)


def test_index_carries_version_and_name_and_tag_labels_the_used_pairs(tmp_path: Path) -> None:
    rows = build_rows(tmp_path, make_world(tmp_path / "w"), [4, 5], 2)
    corpus = {r["logical_id"]: r for r in _lines(rows / "corpus.jsonl")}
    for i in _lines(rows / "rows_index.jsonl"):
        tag = i["fsds_key"]["tag"]
        assert i["version"] == CONCEPTS[tag][0]
        assert corpus[i["logical_id"]]["text"].startswith(i["name"] + ": ")
    assert all("_index" not in r and "version" not in r for r in corpus.values())
    labels = {(r["tag"], r["version"]): r for r in _lines(rows / "tag_labels.jsonl")}
    assert ("OddTag", STD) not in labels  # absent from tag.txt: not invented
    assert labels[("AcmeRebates", K1)]["custom"] == "1"
    assert labels[("SalesNet", STD)]["tlabel"] == CONCEPTS["SalesNet"][2]
    assert set(labels) <= {(t, c[0]) for t, c in CONCEPTS.items()}


def test_missing_tag_txt_is_refused_by_member_name(tmp_path: Path) -> None:
    m = make_world(tmp_path / "w", no_tag_txt=("2025q1",))
    with pytest.raises(pr.PitError, match=r"tag\.txt missing from sec_fsds/2025q1"):
        build_rows(tmp_path, m, [4, 5], 2)
    assert not list(tmp_path.glob("rows-*/corpus.jsonl"))


def test_two_labels_for_one_tag_version_are_refused(tmp_path: Path) -> None:
    m = make_world(tmp_path / "w", tlabel_override={"2025q3": {"SalesNet": "Other Label"}})
    with pytest.raises(pr.PitError, match=r"SalesNet.*between sec_fsds/2025q1 and sec_fsds/2025q3"):
        build_rows(tmp_path, m, [4, 5], 2)


# ---------------------------------------------------------------- family A on the real path


def family_a(tmp: Path) -> tuple[Path, Path, dict[str, Any]]:
    rows = build_rows(tmp, make_world(tmp / "w"), [4, 5], 2)
    rc, out = tasks_of(tmp, rows, "--family", pt.CONCEPT)
    assert rc == 1  # 6 tasks < FLOOR: the shortfall exit, never padded
    return rows, out, json.loads((out / "tasks_manifest.json").read_text("utf-8"))


def test_family_a_admits_only_full_row_zero_overlap_standard_labels(tmp_path: Path) -> None:
    rows, out, man = family_a(tmp_path)
    tasks = _lines(out / "tasks.jsonl")
    labels = {r["tlabel"]: r for r in _lines(rows / "tag_labels.jsonl")}
    corpus = _lines(rows / "corpus.jsonl")
    index = {i["logical_id"]: i for i in _lines(rows / "rows_index.jsonl")}
    seen_tags = set()
    assert len(tasks) == 6
    for t in tasks:
        parse_task(t)
        name, rest = t["query"].split(": ", 1)
        period = t["label_blind_query"].removeprefix(name + ": ")
        assert t["label_blind_query"] == f"{name}: {period}"
        tlabel = rest.removesuffix(": " + period)
        lab = labels[tlabel]
        assert lab["custom"] == "0"
        tl = set(semantic_tokens(tlabel))
        assert tl and not tl & set(semantic_tokens(t["label_blind_query"]))
        targets = [
            r for r in corpus
            if index[r["logical_id"]]["fsds_key"]["tag"] == lab["tag"]
            and r["text"].startswith(name + ": ") and r["text"].endswith(period)
        ]  # fmt: skip
        assert targets
        for r in targets:  # the whole row text minus the value, independently re-derived
            value = r["text"].split(": ")[2].split(" ")[0]
            assert not tl & set(semantic_tokens(r["text"].replace(f": {value} ", ": ", 1)))
        assert t["family"] == pt.CONCEPT and t["concept_overlap"] == 0
        seen_tags.add(lab["tag"])
    # Revenues overlaps its own label, GrossMargin overlaps only the period text ("period"),
    # AcmeRebates is custom, OddTag has no label: none of them yields a task.
    assert seen_tags == {"SalesNet", "NewTag", "ShareCount"}
    assert man["skipped"]["concept_custom_tag"] == 1
    assert man["skipped"]["concept_tag_version_absent"] == 1
    assert man["skipped"]["concept_label_overlap"] == 2
    assert man["admission"]["by_tag"]["GrossMargin"] == {"standard": 1}
    assert man["family"] == pt.CONCEPT
    assert man["tag_labels_sha256"] == _sha(rows / "tag_labels.jsonl")
    assert pt.CONCEPT_STATEMENT in man["statements"]
    assert "accuracy" not in json.dumps([man["admission"], pt.CONCEPT_STATEMENT]).lower()


def test_inflection_overlap_is_flagged_and_counted_per_stratum(tmp_path: Path) -> None:
    _, out, man = family_a(tmp_path)
    flagged = [t for t in _lines(out / "tasks.jsonl") if t["inflection_overlap"]]
    assert [t["query"].split(": ")[1] for t in flagged] == ["Shares Outstanding"]  # share/shares
    by_sv = man["admission"]["by_stratum_variant"]
    assert by_sv["backdated-A"]["inflection_overlap"] == 1
    assert sum(v.get("inflection_overlap", 0) for v in by_sv.values()) == 1


@pytest.mark.parametrize(
    ("a", "b", "hit"),
    [
        ("share", "shares", True),
        ("tax", "taxes", True),
        ("loss", "losses", True),
        ("quarters.", "quarter", True),
        ("net", "assets", False),
        ("revenue", "income", False),
    ],
)
def test_inflection_overlap_forms(a: str, b: str, hit: bool) -> None:
    assert pt.inflection_overlap([a], [b]) is hit
    assert pt.inflection_overlap([b], [a]) is hit


def test_family_a_generation_is_deterministic_and_readable_by_the_harness(tmp_path: Path) -> None:
    from benchmark.retrieval_baselines.run_baselines import _blind_queries

    rows, out, _ = family_a(tmp_path)
    _, again = tasks_of(tmp_path, rows, "--family", pt.CONCEPT)
    assert (out / "tasks.jsonl").read_bytes() == (again / "tasks.jsonl").read_bytes()
    lines = (out / "tasks.jsonl").read_text("utf-8").splitlines()
    blind = _blind_queries(lines)
    assert len(blind) == len(lines) and all(blind.values())


def test_family_a_refuses_rows_without_version_or_labels(tmp_path: Path) -> None:
    rows = build_rows(tmp_path, make_world(tmp_path / "w"), [4, 5], 2)
    corpus, index = _lines(rows / "corpus.jsonl"), _lines(rows / "rows_index.jsonl")
    labels = pt.load_tag_labels((rows / "tag_labels.jsonl").read_bytes())
    with pytest.raises(pt.PitTaskError, match="tag_labels"):
        pt.generate(corpus, index, family=pt.CONCEPT)
    with pytest.raises(pt.PitTaskError, match="unknown task family"):
        pt.generate(corpus, index, family="statement", tag_labels=labels)
    old = [{k: v for k, v in i.items() if k != "version"} for i in index]
    with pytest.raises(pt.PitTaskError, match="no version/name"):
        pt.generate(corpus, old, family=pt.CONCEPT, tag_labels=labels)
    renamed = [{**i, "name": "Other Corp"} for i in index]
    with pytest.raises(pt.PitTaskError, match="does not start with its index name"):
        pt.generate(corpus, renamed, family=pt.CONCEPT, tag_labels=labels)
    (rows / "tag_labels.jsonl").unlink()
    rc, _ = tasks_of(tmp_path, rows, "--family", pt.CONCEPT)
    assert rc == 1


@pytest.mark.parametrize(
    "line",
    [
        {"tag": "T", "version": "v", "custom": "2", "tlabel": "L"},
        {"tag": "T", "version": "v", "custom": "0"},
        {"tag": "T", "version": "v", "custom": "0", "tlabel": None},
        {"tag": "T", "version": "v", "custom": 0, "tlabel": "L"},
        ["T", "v", "0", "L"],
    ],
)
def test_bad_tag_label_rows_are_refused(line: Any) -> None:
    with pytest.raises(pt.PitTaskError, match="line 1"):
        pt.load_tag_labels((json.dumps(line) + "\n").encode())


def test_repeated_tag_label_is_refused() -> None:
    row = json.dumps({"tag": "T", "version": "v", "custom": "0", "tlabel": "L"}) + "\n"
    with pytest.raises(pt.PitTaskError, match="repeats"):
        pt.load_tag_labels((row * 2).encode())


# ---------------------------------------------------------------- manifest, rebuild, blind split


def test_manifest_must_be_named(tmp_path: Path) -> None:
    ex = ciks_file(tmp_path / "ex.json", [4, 5])
    with pytest.raises(pr.PitError, match="--manifest is required"):
        pr.build(tmp_path / "o", ex, 2, 0, gold_value=gold_value)
    assert pr.main(["build", "--exclude-ciks", str(ex), "--out", str(tmp_path / "o")]) == 1


def test_rebuild_reproduces_or_is_refused(tmp_path: Path) -> None:
    m = make_world(tmp_path / "w")
    rows = build_rows(tmp_path, m, [4, 5], 2)
    again = build_rows(tmp_path, m, [4, 5], 2, rebuild_of=rows)
    assert (again / "corpus.jsonl").read_bytes() == (rows / "corpus.jsonl").read_bytes()
    meta = json.loads((again / "pit_rows_meta.json").read_text("utf-8"))
    assert meta["rebuild_of_meta_sha256"] == _sha(rows / "pit_rows_meta.json")
    other = make_world(tmp_path / "w2")  # same files elsewhere: another manifest digest
    with pytest.raises(pr.PitError, match=r"is not the one the rows in .* were built from"):
        build_rows(tmp_path, other, [4, 5], 2, rebuild_of=rows)
    with pytest.raises(pr.PitError, match="does not reproduce"):
        build_rows(tmp_path, m, [2, 5], 2, rebuild_of=rows)  # another CIK set


def test_blind_split_union_exclude_file_and_holdout_draw(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    m = make_world(tmp_path / "w")
    dev = build_rows(tmp_path, m, [4, 5], 2)
    screen = ciks_file(tmp_path / "screen.json", [3])
    union = tmp_path / "union.json"
    args = ["exclude-union", "--exclude-ciks", str(screen), "--rows-dir", str(dev)]
    capsys.readouterr()
    assert pr.main([*args, "--out", str(union)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["sha256"] == _sha(union) and pr._load_ciks(union) == {"1", "2", "3"}
    assert pr.main([*args, "--out", str(union)]) == 1  # written once, never overwritten
    out = tmp_path / "holdout"
    stats = pr.build(out, union, 2, 7, manifest=m, gold_value=gold_value, holdout_of=dev)
    meta = json.loads((out / "pit_rows_meta.json").read_text("utf-8"))
    assert meta["ciks"] == ["4", "5"] and meta["seed"] == 7
    assert meta["ciks_without_rows"] == ["5"] and stats["ciks_without_rows"] == 1
    assert meta["excluded_ciks_sha256"] == printed["sha256"]
    assert meta["holdout_of_meta_sha256"] == _sha(dev / "pit_rows_meta.json")


def test_holdout_draw_containing_a_dev_company_is_refused_by_name(tmp_path: Path) -> None:
    m = make_world(tmp_path / "w")
    dev = build_rows(tmp_path, m, [4, 5], 2)
    screen_only = ciks_file(tmp_path / "screen.json", [3])
    with pytest.raises(pr.PitError, match=r"dev CIKs \['1', '2'\]"):
        pr.build(
            tmp_path / "h", screen_only, 4, 0, manifest=m, gold_value=gold_value, holdout_of=dev
        )
    assert not (tmp_path / "h").exists()
    other = make_world(tmp_path / "w2")
    union = ciks_file(tmp_path / "u.json", [1, 2, 3])
    with pytest.raises(pr.PitError, match="name that manifest"):
        pr.build(tmp_path / "h", union, 2, 0, manifest=other, gold_value=gold_value, holdout_of=dev)
