"""AT-3: price/terms snapshots bind WEB-RECEIPTS-MANIFEST rows; the validator fails closed.

The committed snapshots are checked for shape, for agreement with ``cost.py`` and for the 7-day
rule at fixed instants. Binding to the saved vendor pages needs the receipts directory, which
lives outside this repository; it is exercised here on SYNTHETIC pages and receipts in tmp_path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from research.vendor_comparison_20261017 import cost
from research.vendor_comparison_20261017.snapshots import validate
from research.vendor_comparison_20261017.snapshots.price_snapshot_schema import (
    SCHEMA,
    PriceSnapshot,
    SnapshotError,
    load,
    load_all,
    parse_utc,
)

VENDORS = {"reducto", "llamaparse", "unstructured", "landingai"}
MANIFEST_SHA256 = "8b095f3801a545ce534ceef1ba3b4128e2b10032869a4d865bf1aeae384bb37c"

FETCHED = "2026-10-17T01:00:00.000Z"
FETCHED_AT = datetime(2026, 10, 17, 1, tzinfo=UTC)
LATER = FETCHED_AT + timedelta(days=1)
VENDOR = "synthetic_vendor"
MANIFEST = "receipts/SYNTHETIC-WEB-RECEIPTS-MANIFEST.json"
PAGES = {
    "SYNTHETIC-pricing.html": (
        b"<html><body><h1>SYNTHETIC pricing page</h1><table><tr><td>Parse</td>"
        b"<td>$10 per 1,000 pages</td></tr></table>"
        b"<script>var hidden = '$99 per page';</script></body></html>"
    ),
    "SYNTHETIC-terms.html": b"<p>SYNTHETIC terms: no benchmarking &amp; no resale.</p>",
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class World:
    """A SYNTHETIC receipts root (manifest + two saved pages) and a snapshot bound to it."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.root = tmp_path / "SYNTHETIC-receipts-root"
        (self.root / "receipts" / "web").mkdir(parents=True)
        self.manifest: dict[str, Any] = {"schema": "tavonel.web-receipts.v1", "rows": []}
        for name, body in PAGES.items():
            self.put_page(name, body)
        self.snapshot: dict[str, Any] = {
            "schema": SCHEMA,
            "label": "SYNTHETIC",
            "vendor": VENDOR,
            "arm_id": "D-V-synthetic",
            "price_point": "synthetic_default",
            "currency": "USD",
            "captured_at": FETCHED,
            "manifest": {"file": MANIFEST, "sha256": ""},
            "prices": [
                {
                    "name": "parse_per_1000_pages",
                    "value": 10,
                    "unit": "usd_per_1000_pages",
                    **self.row("SYNTHETIC-pricing.html", "Parse $10 per 1,000 pages"),
                }
            ],
            "conditions": [],
            "terms": self.row("SYNTHETIC-terms.html", "no benchmarking & no resale."),
        }
        self.manifest_sha256: str | None = None  # None: the sha256 of the manifest as written
        self.fd1: dict[str, Any] = {
            "decision": "FD-1",
            "approved_arms": ["D-V-synthetic"],
            "terms_sha256": {VENDOR: _sha(PAGES["SYNTHETIC-terms.html"])},
        }

    def put_page(self, name: str, body: bytes) -> None:
        (self.root / "receipts" / "web" / name).write_bytes(body)
        rows = [row for row in self.manifest["rows"] if row["file"] != f"web/{name}"]
        rows.append(
            {
                "file": f"web/{name}",
                "url": f"https://synthetic.invalid/{name}",
                "bytes": len(body),
                "sha256": _sha(body),
                "downloaded_utc": FETCHED,
            }
        )
        self.manifest["rows"] = rows

    def row(self, name: str, quoted: str) -> dict[str, Any]:
        body = (self.root / "receipts" / "web" / name).read_bytes()
        return {
            "quoted_text": quoted,
            "file": f"receipts/web/{name}",
            "url": f"https://synthetic.invalid/{name}",
            "sha256": _sha(body),
            "fetched_at": FETCHED,
        }

    def override_manifest_sha256(self, value: str) -> None:
        self.manifest_sha256 = value

    def write(self) -> PriceSnapshot:
        manifest = _write_json(self.root / MANIFEST, self.manifest)
        self.snapshot["manifest"]["sha256"] = self.manifest_sha256 or _sha(manifest.read_bytes())
        return load(_write_json(self.tmp / f"{VENDOR}.price_snapshot.json", self.snapshot))

    def fd1_path(self) -> Path:
        return _write_json(self.tmp / "fd1.json", self.fd1)

    def check(self, now: datetime = LATER) -> dict[str, list[str]]:
        snapshot = self.write()
        return validate.check(
            snapshot, now=now, fd1_receipt=self.fd1_path(), receipts_root=self.root
        )


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


# --- the committed snapshots ------------------------------------------------------------------


def test_committed_snapshots_cover_the_four_vendor_arms() -> None:
    snapshots = load_all()
    assert set(snapshots) == VENDORS
    for vendor, snapshot in snapshots.items():
        assert snapshot.arm_id == f"D-V-{vendor}"
        assert snapshot.currency == "USD"
        assert snapshot.manifest_file == "competitor-protocol-receipts/WEB-RECEIPTS-MANIFEST.json"
        assert snapshot.manifest_sha256 == MANIFEST_SHA256
        assert all(
            r.file.startswith("competitor-protocol-receipts/web/") for r in snapshot.receipts
        )


def test_committed_terms_rows_are_the_prereg_terms_pages() -> None:
    terms = {vendor: snapshot.terms.file for vendor, snapshot in load_all().items()}
    assert terms == {
        "reducto": "competitor-protocol-receipts/web/reducto-terms.html",
        "llamaparse": "competitor-protocol-receipts/web/llamaindex-terms.html",
        "unstructured": "competitor-protocol-receipts/web/unstructured-platform-terms.html",
        "landingai": "competitor-protocol-receipts/web/landingai-terms.html",
    }


def test_committed_snapshots_bind_every_receipt_cost_py_prices_from() -> None:
    snapshots = load_all()
    for vendor, priced in cost.SNAPSHOTS.items():
        bound = {(r.file, r.sha256, r.fetched_at) for r in snapshots[vendor].receipts}
        for file, sha256, utc in priced.sources:
            assert (file, sha256, parse_utc(utc, file)) in bound, (vendor, file)


def test_committed_snapshot_numbers_equal_the_cost_constants() -> None:
    s = load_all()
    assert s["reducto"].price("r1_parse_per_1000_pages") / 1000 == cost.REDUCTO_USD_PER_PAGE
    assert s["unstructured"].price("usd_per_page") == cost.UNSTRUCTURED_USD_PER_PAGE
    llama = s["llamaparse"]
    assert llama.price("usd_per_1000_credits") / 1000 == cost.LLAMAPARSE_USD_PER_CREDIT
    for tier, credits in cost.LLAMAPARSE_CREDITS_PER_PAGE.items():
        assert llama.price(f"{tier}_credits_per_page") == credits
    landing = s["landingai"]
    assert 1 / landing.price("credits_per_usd") == cost.LANDINGAI_USD_PER_CREDIT
    assert landing.price("dpt3_pro_priority_credits_per_page") == cost.LANDINGAI_CREDITS_PER_PAGE
    assert (
        landing.price("dpt3_pro_priority_credits_per_1000_output_characters")
        == cost.LANDINGAI_CREDITS_PER_1000_CHARS
    )
    assert landing.price("credit_total_rounding_up_increment") == Decimal("0.1")
    with pytest.raises(KeyError, match="no price row"):
        landing.price("SYNTHETIC-absent")


@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_committed_snapshot_expires_seven_days_after_capture(vendor: str) -> None:
    snapshot = load_all()[vendor]
    limit = snapshot.captured_at + timedelta(days=7)
    assert validate.freshness_problems(snapshot, limit) == []
    stale = validate.freshness_problems(snapshot, limit + timedelta(microseconds=1))
    assert len(stale) == 1 and stale[0].startswith("stale:")


@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_committed_snapshot_without_fd1_receipt_is_refused(vendor: str, tmp_path: Path) -> None:
    snapshot = load_all()[vendor]
    assert validate.fd1_problems(snapshot, None) == ["FD-1 receipt absent: none was given"]
    assert validate.fd1_problems(snapshot, tmp_path / "FD-1.json")[0].startswith(
        "FD-1 receipt absent:"
    )


# --- the validator on SYNTHETIC receipts ------------------------------------------------------


def test_bound_fresh_snapshot_with_matching_fd1_passes(world: World) -> None:
    assert world.check() == {"fd1": [], "binding": [], "freshness": []}


def test_page_text_follows_html2txt() -> None:
    text = validate.page_text(PAGES["SYNTHETIC-pricing.html"] + b"<br/>a&nbsp;&lt;b&gt;&#39;")
    assert text == "SYNTHETIC pricing page\nParse $10 per 1,000 pages\na <b>'"


@pytest.mark.parametrize(
    "hidden",
    [
        b"<script>var p = '$99 per page';</script >",
        b"<SCRIPT type=\"text/javascript\">var p = '$99 per page';</SCRIPT\n>",
        b"<script>var p = '$99 per page';</script\tdata-x=\"y\">",
        b"<style>.p::after { content: '$99 per page' }</style >",
        b"<Style media=\"all\">.p::after { content: '$99 per page' }</STYLE\r\n>",
        # Text that only resembles an end tag does not end the element early.
        b"<script>var s = '<script>', t = '</scripts>'; var p = '$99 per page';</script>",
        b"<script>var t = '</script-x>'; var p = '$99 per page';</script>",
        # A browser folds tag names in ASCII only: U+017F LONG S is not "s".
        "<script>var t = '</\u017fcript>'; var p = '$99 per page';</script>".encode(),
    ],
    ids=[
        "space",
        "upper_newline",
        "attribute",
        "style_space",
        "style_mixed_crlf",
        "nested_like",
        "dash_like",
        "non_ascii_fold",
    ],
)
def test_script_and_style_bodies_are_not_text_whatever_the_end_tag(hidden: bytes) -> None:
    """CodeQL py/bad-tag-filter: ``</script >`` ends a script for a browser, so it does here."""
    assert validate.page_text(b"<p>Visible</p>" + hidden + b"<p>After</p>") == "Visible\nAfter"


def test_an_unclosed_script_runs_to_the_end_of_the_page() -> None:
    page = b"<p>Visible</p><script>var p = '$99 per page';<p>still script</p>"
    assert validate.page_text(page) == "Visible"


def test_a_quote_hidden_in_a_script_is_refused_whatever_its_end_tag(world: World) -> None:
    page = PAGES["SYNTHETIC-pricing.html"].replace(b"</script>", b"</script >")
    world.put_page("SYNTHETIC-pricing.html", page)
    price = world.row("SYNTHETIC-pricing.html", "Parse $10 per 1,000 pages")
    world.snapshot["prices"][0].update(price)
    world.snapshot["conditions"].append(world.row("SYNTHETIC-pricing.html", "$99 per page"))
    problems = validate.binding_problems(world.write(), world.root)
    assert problems == [
        "receipts/web/SYNTHETIC-pricing.html: quoted_text not found: '$99 per page'"
    ]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda w: w.fd1.update(decision="FD-2"), "does not record decision FD-1"),
        (lambda w: w.fd1.update(label="SYNTHETIC"), "is SYNTHETIC, not a founder decision"),
        (lambda w: w.fd1.pop("terms_sha256"), "records no terms_sha256 for synthetic_vendor"),
        (lambda w: w.fd1.update(terms_sha256="x"), "records no terms_sha256"),
        (lambda w: w.fd1.update(terms_sha256={"other": "a" * 64}), "records no terms_sha256"),
        (lambda w: w.fd1.update(terms_sha256={VENDOR: "a" * 64}), "terms changed since FD-1"),
    ],
)
def test_invalid_fd1_receipt_is_refused(
    world: World, change: Callable[[World], object], reason: str
) -> None:
    change(world)
    problems = world.check()
    assert problems["binding"] == problems["freshness"] == []
    assert len(problems["fd1"]) == 1 and reason in problems["fd1"][0]


def test_fd1_receipt_absent_unreadable_or_synthetic_named_is_refused(world: World) -> None:
    snapshot = world.write()
    assert validate.fd1_problems(snapshot, None) == ["FD-1 receipt absent: none was given"]
    assert "does not exist" in validate.fd1_problems(snapshot, world.tmp / "missing.json")[0]
    broken = world.tmp / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert "not readable JSON" in validate.fd1_problems(snapshot, broken)[0]
    listed = _write_json(world.tmp / "listed.json", ["FD-1"])
    assert "does not record decision FD-1" in validate.fd1_problems(snapshot, listed)[0]
    named = _write_json(world.tmp / "SYNTHETIC-fd1.json", world.fd1)
    assert "is SYNTHETIC" in validate.fd1_problems(snapshot, named)[0]


def test_terms_page_refetched_with_new_bytes_after_fd1_is_refused(world: World) -> None:
    """A clean re-fetch binds fine, but its terms bytes differ from what FD-1 approved."""
    world.put_page("SYNTHETIC-terms.html", b"<p>SYNTHETIC terms v2: no benchmarking.</p>")
    world.snapshot["terms"] = world.row("SYNTHETIC-terms.html", "no benchmarking.")
    problems = world.check()
    assert problems["binding"] == problems["freshness"] == []
    assert len(problems["fd1"]) == 1 and "terms changed since FD-1" in problems["fd1"][0]


def test_snapshot_older_than_seven_days_is_refused(world: World) -> None:
    assert world.check(FETCHED_AT + timedelta(days=7))["freshness"] == []
    stale = world.check(FETCHED_AT + timedelta(days=7, seconds=1))
    assert stale["fd1"] == stale["binding"] == []
    assert len(stale["freshness"]) == 1 and stale["freshness"][0].startswith("stale:")


def test_page_fetched_after_now_is_refused(world: World) -> None:
    problems = world.check(FETCHED_AT - timedelta(seconds=1))["freshness"]
    assert len(problems) == 1 and "is after now" in problems[0]


def test_now_without_offset_is_a_caller_error(world: World) -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        world.check(datetime(2026, 10, 18))  # naive on purpose


def _tamper_page(world: World) -> None:
    (world.root / "receipts" / "web" / "SYNTHETIC-terms.html").write_bytes(b"SYNTHETIC tamper")


def _drop_page(world: World) -> None:
    (world.root / "receipts" / "web" / "SYNTHETIC-terms.html").unlink()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda w: w.snapshot["manifest"].update(file="receipts/absent.json"), "manifest absent"),
        (lambda w: w.override_manifest_sha256("b" * 64), "manifest sha256 is"),
        (lambda w: w.snapshot["terms"].update(file="receipts/web/x.html"), "not a row of"),
        (lambda w: w.snapshot["terms"].update(url="https://other.invalid/"), "url "),
        (lambda w: w.snapshot["terms"].update(sha256="c" * 64), "sha256 "),
        (
            lambda w: w.manifest["rows"][0].update(downloaded_utc="2026-10-16T00:00:00Z"),
            "manifest downloaded_utc",
        ),
        (lambda w: w.manifest["rows"][0].update(downloaded_utc="yesterday"), "not ISO-8601"),
        (_drop_page, "saved page absent"),
        (_tamper_page, "saved bytes hash to"),
        (lambda w: w.snapshot["terms"].update(quoted_text="no resale, ever."), "not found"),
        (
            lambda w: w.snapshot["conditions"].append(
                w.row("SYNTHETIC-pricing.html", "$99 per page")  # inside <script>: not text
            ),
            "quoted_text not found: '$99 per page'",
        ),
    ],
)
def test_unbound_snapshot_is_refused(
    world: World, change: Callable[[World], object], reason: str
) -> None:
    change(world)
    snapshot = world.write()
    problems = validate.binding_problems(snapshot, world.root)
    assert problems and any(reason in problem for problem in problems), problems


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda d: d.update(schema="tavonel.arena.opus-price-snapshot.v1"), "schema is not"),
        (lambda d: d["terms"].update(fetched_at="2026-10-17T01:00:00"), "no UTC offset"),
        (lambda d: d["terms"].update(fetched_at=20261017), "must be a string"),
        (lambda d: d.update(captured_at="2026-10-17T02:00:00Z"), "is not the oldest"),
        (lambda d: d["prices"][0].update(value=0), "positive number"),
        (lambda d: d["prices"][0].update(value=True), "positive number"),
        (lambda d: d["prices"][0].update(value="10"), "positive number"),
        (lambda d: d["prices"][0].pop("unit"), "'unit' must be a non-empty string"),
        (lambda d: d["prices"][0].update(quoted_text=" "), "'quoted_text' must be"),
        (lambda d: d.update(prices=[]), "'prices' is empty"),
        (lambda d: d.update(prices=[d["prices"][0], d["prices"][0]]), "price names repeat"),
        (lambda d: d.update(conditions={}), "'conditions' must be a list"),
        (lambda d: d.update(conditions=["x"]), "must be an object"),
        (lambda d: d.pop("terms"), "terms: must be an object"),
        (lambda d: d.pop("vendor"), "'vendor' must be"),
    ],
)
def test_malformed_snapshot_is_refused_at_load(
    world: World, change: Callable[[dict[str, Any]], object], reason: str
) -> None:
    change(world.snapshot)
    with pytest.raises(SnapshotError, match=reason):
        world.write()


def test_manifest_sha256_that_is_not_hex_is_refused_at_load(world: World) -> None:
    world.override_manifest_sha256("ABC")
    with pytest.raises(SnapshotError, match="not a lowercase hex sha256"):
        world.write()


def test_non_json_or_non_object_snapshot_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "SYNTHETIC-x.price_snapshot.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(SnapshotError, match="not JSON"):
        load(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(SnapshotError, match="json: must be an object"):
        load(path)


def test_snapshot_file_must_be_named_after_its_vendor(world: World) -> None:
    world.write()
    (world.tmp / f"{VENDOR}.price_snapshot.json").rename(world.tmp / "other.price_snapshot.json")
    with pytest.raises(SnapshotError, match="names vendor"):
        load_all(world.tmp)


# --- the command line ---------------------------------------------------------------------------


def test_cli_refuses_without_fd1_and_passes_with_it(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot = world.write()
    monkeypatch.setattr(validate, "load_all", lambda: {VENDOR: snapshot})
    argv = ["--receipts-root", str(world.root), "--now", "2026-10-18T00:00:00Z"]

    assert validate.main(argv) == validate.EXIT_REFUSED
    refused = json.loads(capsys.readouterr().out)
    assert refused["vendor_calls"] == 0 and refused["max_age_days"] == 7
    [row] = refused["results"]
    assert row["verdict"] == "REFUSED"
    assert row["problems"] == {
        "fd1": ["FD-1 receipt absent: none was given"],
        "binding": [],
        "freshness": [],
    }

    assert validate.main([*argv, "--fd1-receipt", str(world.fd1_path())]) == validate.EXIT_OK
    [row] = json.loads(capsys.readouterr().out)["results"]
    assert row["verdict"] == "PASS" and row["snapshot_sha256"] == snapshot.snapshot_sha256

    stale = ["--receipts-root", str(world.root), "--now", "2026-10-25T00:00:00Z"]
    assert validate.main([*stale, "--fd1-receipt", str(world.fd1_path())]) == 3
    [row] = json.loads(capsys.readouterr().out)["results"]
    assert row["problems"]["freshness"][0].startswith("stale:")
