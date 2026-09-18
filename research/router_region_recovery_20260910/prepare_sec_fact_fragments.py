"""Select frozen SEC Inline XBRL facts and build bounded row fragments."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

EXPECTED_FILINGS = "sha256:e66c483ff52b1259218f8984a24579694812c5a42204a61ae4e0c8fe085a0682"
MAX_PER_FILING = 4
_SPACE = re.compile(r"\s+")
_DIGIT = re.compile(r"\d")


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def normalize(value: str) -> str:
    return _SPACE.sub(" ", value).strip()


def attr(tag: Tag, name: str) -> str:
    value = tag.attrs.get(name.lower())
    return str(value) if value is not None else ""


def selection_hash(filing: dict[str, Any], tag: Tag) -> str:
    parts = (
        str(filing["cik"]),
        str(filing["accession"]),
        attr(tag, "name"),
        attr(tag, "contextref"),
        attr(tag, "unitref"),
        normalize(tag.get_text(" ", strip=False)),
    )
    return digest("\x1f".join(parts).encode())


def fact_tuple(tag: Tag) -> tuple[str, str, str, str]:
    return (
        attr(tag, "name"),
        attr(tag, "contextref"),
        attr(tag, "unitref"),
        normalize(tag.get_text(" ", strip=False)),
    )


def obviously_hidden(tag: Tag) -> bool:
    current: Tag | None = tag
    while current is not None:
        if current.has_attr("hidden"):
            return True
        style = attr(current, "style").replace(" ", "").casefold()
        if "display:none" in style or "visibility:hidden" in style:
            return True
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
    return False


def tag_name_matches(tag: Tag) -> bool:
    return str(tag.name).casefold() == "ix:nonfraction"


def table_opening_tag(table: Tag) -> str:
    rendered: list[str] = ["<table"]
    for key, value in sorted(table.attrs.items()):
        encoded = " ".join(value) if isinstance(value, list) else str(value)
        escaped_key = html.escape(str(key), quote=True)
        escaped_value = html.escape(encoded, quote=True)
        rendered.append(f' {escaped_key}="{escaped_value}"')
    rendered.append(">")
    return "".join(rendered)


def build_fragment(soup: BeautifulSoup, target: Tag, region_id: str) -> str:
    row = target.find_parent("tr")
    cell = target.find_parent(["td", "th"])
    table = target.find_parent("table")
    if row is None or cell is None or table is None:
        raise ValueError("SEC_FACT_TABLE_ANCESTOR_MISSING")
    row_copy_soup = BeautifulSoup(str(row), "lxml")
    row_copy = row_copy_soup.find("tr")
    if row_copy is None:
        raise ValueError("SEC_FACT_ROW_COPY_FAILED")
    expected = fact_tuple(target)
    candidates = [
        candidate
        for candidate in row_copy.find_all(tag_name_matches)
        if isinstance(candidate, Tag) and fact_tuple(candidate) == expected
    ]
    if len(candidates) != 1:
        raise ValueError("SEC_FACT_ROW_TARGET_NOT_UNIQUE")
    candidates[0]["data-tavonel-target"] = region_id
    styles = "\n".join(str(style) for style in soup.find_all("style"))
    colgroups = "\n".join(str(node) for node in table.find_all("colgroup", recursive=False))
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        + styles
        + "<style>html,body{margin:0!important;padding:0!important;background:#fff!important;}"
        + "*,*::before,*::after{animation:none!important;transition:none!important;}"
        + "table{margin:0!important;}</style></head><body>"
        + table_opening_tag(table)
        + colgroups
        + "<tbody>"
        + str(row_copy)
        + "</tbody></table></body></html>"
    )


def run(args: argparse.Namespace) -> None:
    source = args.input.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise ValueError("SEC_FACT_FRAGMENT_OUTPUT_MUST_BE_NEW")
    filings_path = source / "FILINGS.jsonl"
    if digest(filings_path.read_bytes()) != EXPECTED_FILINGS:
        raise ValueError("SEC_FACT_FILINGS_MANIFEST_MISMATCH")
    filings = [
        json.loads(line)
        for line in filings_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    output.mkdir(parents=True)
    (output / "fragments").mkdir()
    runtime_rows: list[dict[str, object]] = []
    truth_rows: list[dict[str, object]] = []
    issuer_counts: dict[str, dict[str, int]] = {}
    for filing in filings:
        if filing.get("status") != "acquired":
            continue
        html_path = (source / str(filing["artifact_relative_path"])).resolve(strict=True)
        if not html_path.is_relative_to(source):
            raise ValueError("SEC_FACT_HTML_PATH_ESCAPE")
        html_bytes = html_path.read_bytes()
        if digest(html_bytes) != filing["filing_html_sha256"]:
            raise ValueError("SEC_FACT_HTML_HASH_MISMATCH")
        soup = BeautifulSoup(html_bytes, "lxml")
        facts = [tag for tag in soup.find_all(tag_name_matches) if isinstance(tag, Tag)]
        eligible = [
            tag
            for tag in facts
            if tag.find_parent(["td", "th"]) is not None
            and tag.find_parent("tr") is not None
            and tag.find_parent("table") is not None
            and attr(tag, "xsi:nil").casefold() != "true"
            and bool(_DIGIT.search(normalize(tag.get_text(" ", strip=False))))
            and all(fact_tuple(tag)[:3])
            and not obviously_hidden(tag)
        ]
        counts = Counter(fact_tuple(tag) for tag in eligible)
        unique = [tag for tag in eligible if counts[fact_tuple(tag)] == 1]
        selected = sorted(unique, key=lambda tag: selection_hash(filing, tag))[:MAX_PER_FILING]
        issuer_counts[str(filing["ticker"])] = {
            "facts": len(facts),
            "eligible": len(eligible),
            "unique": len(unique),
            "selected": len(selected),
        }
        for tag in selected:
            selected_hash = selection_hash(filing, tag)
            region_id = "sec-fact-" + selected_hash.removeprefix("sha256:")[-24:]
            fragment = build_fragment(soup, tag, region_id)
            fragment_bytes = fragment.encode()
            relative = f"fragments/{region_id}.html"
            (output / relative).write_bytes(fragment_bytes)
            runtime = {
                "region_id": region_id,
                "ticker": filing["ticker"],
                "cik": filing["cik"],
                "accession": filing["accession"],
                "filing_url": filing["filing_url"],
                "filing_html_sha256": filing["filing_html_sha256"],
                "fragment_relative_path": relative,
                "fragment_sha256": digest(fragment_bytes),
                "target_selector": f'[data-tavonel-target="{region_id}"]',
            }
            runtime_rows.append(runtime)
            truth_rows.append(
                {
                    **runtime,
                    "fact_name": attr(tag, "name"),
                    "context_ref": attr(tag, "contextref"),
                    "unit_ref": attr(tag, "unitref"),
                    "decimals": attr(tag, "decimals") or None,
                    "scale": attr(tag, "scale") or None,
                    "sign": attr(tag, "sign") or None,
                    "normalized_visible_value": normalize(tag.get_text(" ", strip=False)),
                    "source_fact_sha256": digest("\x1f".join(fact_tuple(tag)).encode()),
                    "selection_sha256": selected_hash,
                }
            )
    runtime_rows.sort(key=lambda row: str(row["region_id"]))
    truth_rows.sort(key=lambda row: str(row["region_id"]))
    runtime_path = output / "FRAGMENT_MANIFEST.jsonl"
    truth_path = output / "SEALED_FACTS.jsonl"
    runtime_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in runtime_rows),
        encoding="utf-8",
    )
    truth_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in truth_rows),
        encoding="utf-8",
    )
    result = {
        "filings": sum(record.get("status") == "acquired" for record in filings),
        "regions": len(runtime_rows),
        "issuer_counts": issuer_counts,
        "fragment_manifest_sha256": digest(runtime_path.read_bytes()),
        "sealed_facts_sha256": digest(truth_path.read_bytes()),
        "hidden_truth_in_runtime_manifest": False,
        "model_output_opened": False,
        "gpu_cost_usd": 0,
    }
    (output / "PREPARE_RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
