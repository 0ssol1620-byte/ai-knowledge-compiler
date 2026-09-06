#!/usr/bin/env python3
"""Acquire the preregistered W6 v3 long-horizon Wikipedia corpus.

Two deliberately separate phases enforce the freeze boundary:

    manifest  -> fetch category membership, hash-order it, write immutable title manifest
    acquire   -> require that manifest, then fetch historical snapshot revisions

No revision content is requested during `manifest`. `acquire` consumes contiguous
750-title cohorts in the frozen hash order and stops only under the availability
rule in PROTOCOL_V3_ACQUISITION_2026-08-19.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
EXP = ROOT / "research" / "experiments" / "H1-W6-SAME-INTELLIGENCE-01"
PROTOCOL = EXP / "PROTOCOL_V3_ACQUISITION_2026-08-19.md"
API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "TAVONEL-W6-research/1.0 (public reproducibility experiment; no account data)"
CATEGORIES = ("Category:Featured articles", "Category:Good articles")
MIN_CATEGORY_MEMBERS = 1500
ORDER_SALT = "tavonel-w6-v3-candidate-order-2026-08-19|"
ATTRIBUTE_SALT = "w6-v3-primary-attribute|"
BEFORE_CUTOFF = "2023-06-30T23:59:59Z"
AFTER_CUTOFF = "2026-06-30T23:59:59Z"
MIN_SEPARATION_DAYS = 1095
COHORT_SIZE = 750
MAX_COHORTS = 6
BATCH_SIZE = 20
MIN_PRIMARY = 60
MIN_PRIMARY_ARTICLES = 20
MIN_CONTROLS = 40

SKIP = re.compile(
    r"^(image|caption|width|alt|logo|photo|file|align|style|color|colour|"
    r"header|label|above|below|footnote|signature|map|pushpin|module)",
    re.I,
)
VALUE_NOISE = re.compile(r"\{\{|\}\}|<ref|<!--|\[\[File:|\[\[Image:", re.I)


def sha256_bytes(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_text(body)


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def normalize_title(title: str) -> str:
    return " ".join(unicodedata.normalize("NFC", title).replace("_", " ").split())


def order_key(title: str) -> str:
    return hashlib.sha256((ORDER_SALT + normalize_title(title)).encode("utf-8")).hexdigest()


def request_json(params: dict[str, str], *, retries: int = 7) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {"format": "json", "formatversion": "2", "maxlag": "5", **params}
    )
    req = urllib.request.Request(  # noqa: S310 -- URL origin is fixed by API constant
        f"{API}?{query}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=45) as response:  # noqa: S310 -- fixed HTTPS host
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in {429, 503} or attempt + 1 >= retries:
                raise
            retry_after = exc.headers.get("Retry-After")
            try:
                server_delay = float(retry_after) if retry_after else 0.0
            except ValueError:
                server_delay = 0.0
            # Transport-only backoff. This changes neither the frozen title
            # universe nor its ordering, and no historical content has yet been
            # acquired for v3.
            delay = max(server_delay, min(90.0, 8.0 * (2**attempt)))
            print(f"MediaWiki HTTP {exc.code}; retrying after {delay:.1f}s")
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(min(45.0, 3.0 * (2**attempt)))
    raise RuntimeError(f"MediaWiki request failed after {retries} attempts: {last}")


def category_members(category: str) -> list[str]:
    out: list[str] = []
    cont: str | None = None
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmnamespace": "0",
            "cmtype": "page",
            "cmlimit": "max",
        }
        if cont:
            params["cmcontinue"] = cont
        data = request_json(params)
        out.extend(normalize_title(row["title"]) for row in data["query"]["categorymembers"])
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont:
            break
    return sorted(set(out))


def make_manifest(output: Path) -> int:
    if not PROTOCOL.exists():
        raise SystemExit("v3 protocol is absent; acquisition is forbidden")
    chosen: str | None = None
    titles: list[str] = []
    source_counts: dict[str, int] = {}
    for category in CATEGORIES:
        members = category_members(category)
        source_counts[category] = len(members)
        if len(members) >= MIN_CATEGORY_MEMBERS:
            chosen, titles = category, members
            break
    if chosen is None:
        raise SystemExit(
            "no preregistered category reached 1,500 main-namespace members; "
            "v3 protocol says NOT RUN rather than substituting a source"
        )
    ordered = sorted(titles, key=lambda t: (order_key(t), t))
    manifest: dict[str, Any] = {
        "schema": "tavonel.w6-v3-title-manifest.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "api": API,
        "source_category": chosen,
        "source_counts_observed_until_selection": source_counts,
        "selection_rule": "first preregistered category with >=1500 namespace-0 page members",
        "normalization": "Unicode NFC; underscores to spaces; collapse internal whitespace",
        "ordering": "sha256('tavonel-w6-v3-candidate-order-2026-08-19|' + normalized_title)",
        "protocol_sha256": file_sha256(PROTOCOL),
        "acquisition_script_sha256": file_sha256(Path(__file__)),
        "candidate_count": len(ordered),
        "max_candidates_consumable": min(len(ordered), COHORT_SIZE * MAX_COHORTS),
        "titles": [
            {"index": i, "title": title, "order_key": order_key(title)}
            for i, title in enumerate(ordered)
        ],
        "external_gpu_cost_usd": 0.0,
    }
    manifest["receipt_sha256"] = canonical_sha256(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"source category: {chosen}")
    print(f"candidate titles: {len(ordered)}")
    print(f"manifest: {output}")
    print(f"manifest file sha256: {file_sha256(output)}")
    return 0


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(values), size):
        yield values[i : i + size]


def revision_batch(titles: list[str], cutoff: str) -> dict[str, dict[str, Any] | None]:
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": "|".join(titles),
        "redirects": "1",
        "rvprop": "ids|timestamp|sha1|content",
        "rvslots": "main",
        "rvlimit": "1",
        "rvstart": cutoff,
        "rvdir": "older",
    }
    data = request_json(params)
    redirects = {
        normalize_title(r["from"]): normalize_title(r["to"])
        for r in data["query"].get("redirects", [])
    }
    pages_by_title = {
        normalize_title(p.get("title", "")): p for p in data["query"].get("pages", [])
    }
    out: dict[str, dict[str, Any] | None] = {}
    for original in titles:
        lookup = redirects.get(normalize_title(original), normalize_title(original))
        page = pages_by_title.get(lookup)
        revisions = page.get("revisions", []) if page else []
        if not revisions:
            out[original] = None
            continue
        rev = revisions[0]
        slot = rev.get("slots", {}).get("main", {})
        content = slot.get("content")
        if content is None:
            out[original] = None
            continue
        out[original] = {
            "resolved_title": lookup,
            "revision_id": rev["revid"],
            "parent_id": rev.get("parentid"),
            "timestamp": rev["timestamp"],
            "mw_sha1": rev.get("sha1"),
            "content": content,
        }
    return out


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def infobox_facts(text: str) -> dict[str, str]:
    match = re.search(r"\{\{\s*[Ii]nfobox", text)
    if not match:
        return {}
    depth, i = 0, match.start()
    while i < len(text):
        if text.startswith("{{", i):
            depth += 1
            i += 2
        elif text.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                break
        else:
            i += 1
    body = text[match.start() : i]
    facts: dict[str, str] = {}
    for line in body.split("\n|")[1:]:
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = " ".join(key.strip().lower().replace("_", " ").split())
        value = " ".join(value.strip().split("\n")[0].split())
        if not key or not value or SKIP.match(key) or VALUE_NOISE.search(value):
            continue
        if len(value) > 120 or len(key) > 40:
            continue
        facts[key] = value
    return facts


def primary_attrs(title: str, changed: list[str]) -> list[str]:
    return sorted(
        changed,
        key=lambda a: hashlib.sha256(
            (ATTRIBUTE_SALT + title + "|" + a).encode("utf-8")
        ).hexdigest(),
    )[:3]


def page_dir(corpus: Path, index: int, title: str) -> Path:
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]
    return corpus / f"{index:05d}-{digest}"


def acquire(manifest_path: Path, corpus: Path, output: Path) -> int:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if manifest.get("schema") != "tavonel.w6-v3-title-manifest.v1":
        raise SystemExit("unexpected title manifest schema")
    if manifest.get("protocol_sha256") != file_sha256(PROTOCOL):
        raise SystemExit("protocol bytes changed after the title manifest was frozen")
    if manifest.get("acquisition_script_sha256") != file_sha256(Path(__file__)):
        raise SystemExit("acquisition script bytes changed after the title manifest was frozen")

    title_rows = manifest["titles"][: COHORT_SIZE * MAX_COHORTS]
    corpus.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    acquired_primary = 0
    acquired_primary_articles = 0
    acquired_controls = 0
    cohorts_completed = 0
    availability_reached = False

    for cohort_index in range(MAX_COHORTS):
        cohort_rows = title_rows[cohort_index * COHORT_SIZE : (cohort_index + 1) * COHORT_SIZE]
        if not cohort_rows:
            break
        by_title = {row["title"]: row for row in cohort_rows}
        titles = list(by_title)
        before_all: dict[str, dict[str, Any] | None] = {}
        after_all: dict[str, dict[str, Any] | None] = {}
        for batch_no, batch in enumerate(chunks(titles, BATCH_SIZE), start=1):
            before_all.update(revision_batch(batch, BEFORE_CUTOFF))
            after_all.update(revision_batch(batch, AFTER_CUTOFF))
            if batch_no % 10 == 0:
                fetched = min(batch_no * BATCH_SIZE, len(titles))
                print(
                    f"cohort {cohort_index + 1}: fetched {fetched}/{len(titles)} titles"
                )
            time.sleep(0.05)

        for title in titles:
            row = by_title[title]
            before, after = before_all.get(title), after_all.get(title)
            if before is None or after is None:
                exclusions.append(
                    {
                        "index": row["index"],
                        "title": title,
                        "reason": "missing_snapshot_revision",
                    }
                )
                continue
            separation = (parse_ts(after["timestamp"]) - parse_ts(before["timestamp"])).days
            if separation < MIN_SEPARATION_DAYS:
                exclusions.append(
                    {
                        "index": row["index"],
                        "title": title,
                        "reason": "snapshot_revisions_less_than_1095_days_apart",
                        "separation_days": separation,
                    }
                )
                continue
            directory = page_dir(corpus, row["index"], title)
            directory.mkdir(parents=True, exist_ok=True)
            before_path = directory / "before.wikitext"
            after_path = directory / "after.wikitext"
            before_path.write_text(before["content"], encoding="utf-8")
            after_path.write_text(after["content"], encoding="utf-8")
            b_facts = infobox_facts(before["content"])
            a_facts = infobox_facts(after["content"])
            shared = sorted(set(b_facts) & set(a_facts))
            changed = [a for a in shared if b_facts[a] != a_facts[a]]
            unchanged = [a for a in shared if b_facts[a] == a_facts[a]]
            retained_changed = primary_attrs(title, changed)
            record = {
                "manifest_index": row["index"],
                "title": title,
                "resolved_title_before": before["resolved_title"],
                "resolved_title_after": after["resolved_title"],
                "before_revision_id": before["revision_id"],
                "after_revision_id": after["revision_id"],
                "before_timestamp": before["timestamp"],
                "after_timestamp": after["timestamp"],
                "separation_days": separation,
                "before_mw_sha1": before.get("mw_sha1"),
                "after_mw_sha1": after.get("mw_sha1"),
                "before_sha256": file_sha256(before_path),
                "after_sha256": file_sha256(after_path),
                "relative_before_path": str(before_path.relative_to(EXP)).replace("\\", "/"),
                "relative_after_path": str(after_path.relative_to(EXP)).replace("\\", "/"),
                "shared_conservative_infobox_attributes": len(shared),
                "changed_attributes": changed,
                "primary_retained_changed_attributes": retained_changed,
                "unchanged_attributes": unchanged,
            }
            (directory / "metadata.json").write_text(
                json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            records.append(record)

        cohorts_completed += 1
        acquired_primary = sum(len(r["primary_retained_changed_attributes"]) for r in records)
        acquired_primary_articles = sum(
            bool(r["primary_retained_changed_attributes"]) for r in records
        )
        acquired_controls = sum(len(r["unchanged_attributes"]) for r in records)
        print(
            f"after cohort {cohorts_completed}: eligible pages={len(records)}, "
            f"primary-retained={acquired_primary} across {acquired_primary_articles} articles, "
            f"unchanged controls={acquired_controls}"
        )
        if (
            acquired_primary >= MIN_PRIMARY
            and acquired_primary_articles >= MIN_PRIMARY_ARTICLES
            and acquired_controls >= MIN_CONTROLS
        ):
            availability_reached = True
            break

    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-v3-acquisition.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol_sha256": file_sha256(PROTOCOL),
        "acquisition_script_sha256": file_sha256(Path(__file__)),
        "title_manifest_file_sha256": sha256_bytes(manifest_bytes),
        "title_manifest_receipt_sha256": manifest["receipt_sha256"],
        "source_category": manifest["source_category"],
        "before_cutoff": BEFORE_CUTOFF,
        "after_cutoff": AFTER_CUTOFF,
        "minimum_separation_days": MIN_SEPARATION_DAYS,
        "cohort_size": COHORT_SIZE,
        "max_cohorts": MAX_COHORTS,
        "cohorts_completed": cohorts_completed,
        "availability_rule": {
            "min_primary_revision_sensitive_after_three_per_article_cap": MIN_PRIMARY,
            "min_articles_with_primary": MIN_PRIMARY_ARTICLES,
            "min_unchanged_controls": MIN_CONTROLS,
        },
        "availability_reached": availability_reached,
        "eligible_records": len(records),
        "excluded_records": len(exclusions),
        "primary_revision_sensitive_retained": acquired_primary,
        "articles_with_primary": acquired_primary_articles,
        "unchanged_controls": acquired_controls,
        "records": records,
        "exclusions": exclusions,
        "primary_endpoint_status": (
            "ELIGIBLE_FOR_QUESTION_SET"
            if availability_reached
            else "NOT_RUN_INSUFFICIENT_REAL_CASES"
        ),
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"receipt: {output}")
    print(f"status: {receipt['primary_endpoint_status']}")
    return 0 if availability_reached else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="phase", required=True)
    p_manifest = sub.add_parser("manifest")
    p_manifest.add_argument("--output", type=Path, required=True)
    p_acquire = sub.add_parser("acquire")
    p_acquire.add_argument("--manifest", type=Path, required=True)
    p_acquire.add_argument("--corpus", type=Path, required=True)
    p_acquire.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.phase == "manifest":
        return make_manifest(args.output)
    return acquire(args.manifest, args.corpus, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
