#!/usr/bin/env python3
"""Build the P4c cohort: one revision pair per source document, four families.

Network reads only. Nothing is sent anywhere, no credential is transmitted, and
every artifact lands under research/tavonel_eval_v2/.

The two families already on disk — sec_edgar and git_docs — are taken from the
existing raw acquisition rather than refetched, with the frozen selection rule
applied to collapse each document's several consecutive pairs down to one. The
two new families are fetched here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "canonicalization"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from canonical_document import MIN_TEXT_CHARS, Section, assemble, canonical_document  # noqa: E402
from common import NS, ROOT, canonical_sha, now, rel, sha_bytes, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from sources_p4c import (  # noqa: E402
    DART,
    ECFR_PARTS,
    LICENCES,
    REDISTRIBUTION,
    SELECTION_RULE,
    USER_AGENT,
    WIKIPEDIA_ARTICLES,
)

RAW = NS / "artifacts" / "development" / "raw_p4c"
CANONICAL = NS / "artifacts" / "development" / "canonical_p4c"
CONTAINER_CAP = 4
MIN_UNITS = 3
PAUSE_SECONDS = 0.4


def fetch(url: str, *, retries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except Exception as error:  # transient network, not a result
            last = error
            time.sleep(PAUSE_SECONDS * (attempt + 1) * 2)
    raise RuntimeError("fetch failed after %d attempts: %s" % (retries, last))


# --- eCFR --------------------------------------------------------------------

_XML_TAG = re.compile(r"<[^>]+>")
_SECTION_HEAD = re.compile(r"<HEAD>(?P<head>.*?)</HEAD>", re.DOTALL)
_PARAGRAPH = re.compile(r"<P[^>]*>(?P<body>.*?)</P>", re.DOTALL)
_ENUM = re.compile(r"\A\(([a-z0-9ivx]{1,4})\)")


def ecfr_sections(payload: bytes) -> list[Section]:
    """Section head plus paragraphs, grouped by top-level enumerated subsection.

    A CFR section's paragraphs are lettered, and that lettering is the
    document's own structure rather than something inferred, so it is used as
    the heading path exactly as the protocol requires of explicit paths.
    """
    text = payload.decode("utf-8", errors="replace")
    head_match = _SECTION_HEAD.search(text)
    head = _XML_TAG.sub(" ", head_match.group("head")) if head_match else "section"
    head = re.sub(r"\s+", " ", head).strip()

    blocks: list[tuple[str | None, str]] = [("1", head)]
    current: str | None = None
    buffer: list[str] = []
    for match in _PARAGRAPH.finditer(text):
        body = re.sub(r"\s+", " ", _XML_TAG.sub(" ", match.group("body"))).strip()
        if not body:
            continue
        enumerated = _ENUM.match(body)
        if enumerated:
            if buffer:
                blocks.append((None, " ".join(buffer)))
                buffer = []
            current = "(" + enumerated.group(1) + ")"
            blocks.append(("2", current))
            buffer.append(body[enumerated.end() :].strip())
        else:
            buffer.append(body)
    if buffer:
        blocks.append((None, " ".join(buffer)))
    return assemble(blocks)


def ecfr_documents() -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for title, part, part_name in ECFR_PARTS:
        url = (
            "https://www.ecfr.gov/api/versioner/v1/versions/title-%s.json?part=%s"
            % (title, part)
        )
        rows = json.loads(fetch(url)).get("content_versions", [])
        by_section: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if row.get("type") != "section" or row.get("removed"):
                continue
            by_section.setdefault(row["identifier"], []).append(row)
        eligible = [
            (identifier, sorted({row["date"] for row in versions}))
            for identifier, versions in sorted(by_section.items())
        ]
        eligible = [item for item in eligible if len(item[1]) >= 2]
        for identifier, dates in eligible[:CONTAINER_CAP]:
            documents.append(
                {
                    "family": "regulation_ecfr",
                    "container": "%s CFR %s" % (title, part),
                    "container_name": part_name,
                    "document_id": "ecfr:%s:%s:%s" % (title, part, identifier),
                    "title_field": "%s CFR part %s %s" % (title, part, part_name),
                    "doc_type": "Code of Federal Regulations section",
                    "spoken_type": "Code of Federal Regulations section",
                    "identity": "%s CFR %s" % (title, identifier),
                    "before_version": dates[-2],
                    "after_version": dates[-1],
                    "licence": LICENCES["regulation_ecfr"],
                    "fetch": {
                        side: (
                            "https://www.ecfr.gov/api/versioner/v1/full/%s/title-%s.xml"
                            "?part=%s&section=%s" % (date, title, part, identifier)
                        )
                        for side, date in (("before", dates[-2]), ("after", dates[-1]))
                    },
                    "suffix": ".xml",
                }
            )
            time.sleep(PAUSE_SECONDS)
    return documents


# --- Wikipedia ---------------------------------------------------------------


class _WikiReader(HTMLParser):
    """Headings and paragraph text from rendered article HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str | None, str]] = []
        self._level: str | None = None
        self._buffer: list[str] = []
        self._capture = 0
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in ("style", "script", "table", "sup"):
            self._skip += 1
            return
        if lowered in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush()
            self._level = lowered[1]
            self._capture = 1
        elif lowered == "p":
            self._capture = 2

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in ("style", "script", "table", "sup"):
            self._skip = max(0, self._skip - 1)
            return
        if lowered in ("h1", "h2", "h3", "h4", "h5", "h6") and self._capture == 1:
            heading = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
            heading = heading.replace("[edit]", "").strip()
            if heading:
                self.blocks.append((self._level, heading))
            self._buffer = []
            self._capture = 0
        elif lowered == "p" and self._capture == 2:
            body = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
            if body:
                self.blocks.append((None, body))
            self._buffer = []
            self._capture = 0

    def handle_data(self, data: str) -> None:
        if self._capture and not self._skip:
            self._buffer.append(data)

    def _flush(self) -> None:
        self._buffer = []


def wikipedia_sections(payload: bytes) -> list[Section]:
    reader = _WikiReader()
    reader.feed(payload.decode("utf-8", errors="replace"))
    return assemble(reader.blocks)


def wikipedia_documents() -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for article in WIKIPEDIA_ARTICLES:
        url = (
            "https://en.wikipedia.org/w/api.php?action=query&prop=revisions&titles=%s"
            "&rvlimit=2&rvprop=ids%%7Ctimestamp&format=json&formatversion=2"
            % urllib.parse.quote(article)
        )
        pages = json.loads(fetch(url)).get("query", {}).get("pages", [])
        if not pages or "revisions" not in pages[0] or len(pages[0]["revisions"]) < 2:
            continue
        newest, previous = pages[0]["revisions"][0], pages[0]["revisions"][1]
        documents.append(
            {
                "family": "encyclopedia_wikipedia",
                "container": "en.wikipedia.org",
                "container_name": "English Wikipedia",
                "document_id": "wikipedia:en:%s" % article,
                "title_field": article,
                "doc_type": "encyclopedia article",
                "spoken_type": "encyclopedia article",
                "identity": article,
                "before_version": str(previous["revid"]),
                "after_version": str(newest["revid"]),
                "before_known_at": previous["timestamp"],
                "after_known_at": newest["timestamp"],
                "licence": LICENCES["encyclopedia_wikipedia"],
                "fetch": {
                    side: (
                        "https://en.wikipedia.org/w/api.php?action=parse&oldid=%s"
                        "&prop=text&format=json&formatversion=2" % revision
                    )
                    for side, revision in (
                        ("before", previous["revid"]),
                        ("after", newest["revid"]),
                    )
                },
                "suffix": ".html",
                "unwrap": "parse.text",
            }
        )
        time.sleep(PAUSE_SECONDS)
    # container cap does not bind here: one article is one container-member, and
    # the declared list is already the cap
    return documents


# --- families already on disk ------------------------------------------------


def existing_documents(manifest: Path) -> list[dict[str, Any]]:
    """Apply the frozen selection rule to the pairs already acquired."""
    acquisition = json.loads(manifest.read_text(encoding="utf-8"))
    best: dict[str, dict[str, Any]] = {}
    for pair in acquisition["pairs"]:
        if pair.get("group") != "natural":
            continue
        key = pair["source_id"]
        candidate = (pair.get("after_known_at") or "", pair["pair_id"])
        held = best.get(key)
        if held is None or (
            candidate[0] > held["_sort"][0]
            or (candidate[0] == held["_sort"][0] and candidate[1] < held["_sort"][1])
        ):
            best[key] = {**pair, "_sort": candidate}

    documents: list[dict[str, Any]] = []
    per_container: dict[str, int] = {}
    for source_id, pair in sorted(best.items()):
        family = pair["source_family"]
        if family == "sec_edgar":
            parts = source_id.split(":")
            container = parts[1]
            identity = parts[2]
            title = parts[2] + " filing"
            doc_type = parts[2]
            spoken = parts[2] + " filing"
        else:
            parts = source_id.split(":", 2)
            container = parts[1]
            stem = parts[2].rsplit("/", 1)[-1].rsplit(".", 1)[0]
            identity = parts[1] + " " + stem.replace("-", " ").replace("_", " ")
            title = identity
            doc_type = "markdown documentation"
            spoken = "documentation"
        count = per_container.get(container, 0)
        if count >= CONTAINER_CAP:
            continue
        per_container[container] = count + 1
        documents.append(
            {
                "family": family,
                "container": container,
                "container_name": container,
                "document_id": source_id,
                "title_field": title,
                "doc_type": doc_type,
                "spoken_type": spoken,
                "identity": identity,
                "before_version": pair["before_version_id"],
                "after_version": pair["after_version_id"],
                "licence": pair.get("license", LICENCES.get(family, "unknown")),
                "reused_pair_id": pair["pair_id"],
                "on_disk": {
                    side: rel(ROOT / pair[side]["path"]) for side in ("before", "after")
                },
                "suffix": Path(pair["after"]["path"]).suffix,
            }
        )
    return documents


# --- canonicalisation --------------------------------------------------------


def canonicalise(document: dict[str, Any], side: str, payload: bytes) -> dict[str, Any]:
    family = document["family"]
    if family == "regulation_ecfr":
        sections = ecfr_sections(payload)
    elif family == "encyclopedia_wikipedia":
        sections = wikipedia_sections(payload)
    else:
        return canonical_document(
            source_family=family,
            source_id=document["document_id"],
            version_id=document[side + "_version"],
            payload=payload,
            source_digest=sha_bytes(payload),
            known_at=document.get(side + "_known_at"),
            valid_from=None,
            licence=document["licence"],
        )

    seen: dict[tuple[str, ...], int] = {}
    units: list[dict[str, Any]] = []
    for ordinal, section in enumerate(sections):
        count = seen.get(section.path, 0)
        seen[section.path] = count + 1
        explicit = list(section.path)
        if count:
            explicit[-1] = explicit[-1] + "#" + str(count)
        units.append(
            {
                "explicit_path": explicit,
                "heading": section.heading,
                "ordinal": ordinal,
                "text": section.text,
                "text_sha256": sha_bytes(section.text.encode("utf-8")),
            }
        )
    return {
        "schema": "tavonel.v2.canonical_document.v1",
        "source_family": family,
        "source_id": document["document_id"],
        "version_id": document[side + "_version"],
        "version_time": {
            "known_at": document.get(side + "_known_at"),
            "valid_from": None,
        },
        "source_digest": sha_bytes(payload),
        "license": document["licence"],
        "units": units,
        "structure": {
            "order": ["/".join(unit["explicit_path"]) for unit in units],
            "block_count": len(units),
        },
    }


def payload_for(document: dict[str, Any], side: str) -> bytes:
    if "on_disk" in document:
        return (ROOT / document["on_disk"][side]).read_bytes()
    raw = fetch(document["fetch"][side])
    if document.get("unwrap") == "parse.text":
        raw = json.loads(raw)["parse"]["text"].encode("utf-8")
    time.sleep(PAUSE_SECONDS)
    return raw


def probe_dart() -> dict[str, Any]:
    """Attempt DART so its absence is recorded, not inferred."""
    try:
        body = fetch(DART["endpoint"] + "?crtfc_key=&corp_code=00126380", retries=1)
        parsed = json.loads(body)
        return {
            **DART,
            "state": "BLOCKED_MISSING_CREDENTIAL",
            "api_status": parsed.get("status"),
            "api_message": parsed.get("message"),
            "documents_acquired": 0,
            "resolution": "founder decision: a DART certification key is a missing secret",
        }
    except Exception as error:
        return {
            **DART,
            "state": "BLOCKED_UNREACHABLE",
            "error": type(error).__name__,
            "documents_acquired": 0,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--acquisition",
        type=Path,
        default=NS / "receipts" / "p0-acquisition-manifest.json",
    )
    args = parser.parse_args()
    started = now()

    dart = probe_dart()
    documents = existing_documents(args.acquisition)
    documents.extend(ecfr_documents())
    documents.extend(wikipedia_documents())

    admitted: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for document in documents:
        try:
            sides = {side: payload_for(document, side) for side in ("before", "after")}
        except Exception as error:
            excluded.append(
                {
                    "document_id": document["document_id"],
                    "reason": "FETCH_FAILED",
                    "error": type(error).__name__,
                }
            )
            continue
        if sides["before"] == sides["after"]:
            excluded.append(
                {"document_id": document["document_id"], "reason": "INELIGIBLE_NO_SOURCE_CHANGE"}
            )
            continue

        canonical = {side: canonicalise(document, side, sides[side]) for side in sides}
        if any(len(value["units"]) < MIN_UNITS for value in canonical.values()):
            excluded.append(
                {
                    "document_id": document["document_id"],
                    "reason": "INELIGIBLE_PARSE_FLOOR",
                    "units": {side: len(value["units"]) for side, value in canonical.items()},
                }
            )
            continue

        slug = re.sub(r"[^A-Za-z0-9]+", "-", document["document_id"]).strip("-").lower()[:80]
        record: dict[str, Any] = {
            key: value for key, value in document.items() if not key.startswith("_")
        }
        record["document_slug"] = slug
        for side in ("before", "after"):
            raw_path = RAW / slug / (side + document["suffix"])
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(sides[side])
            canonical_path = CANONICAL / slug / (side + ".json")
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical_path.write_text(
                json.dumps(canonical[side], sort_keys=True, indent=2, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            record[side] = {
                "raw_path": rel(raw_path),
                "raw_sha256": sha_file(raw_path),
                "canonical_path": rel(canonical_path),
                "canonical_sha256": canonical_sha(canonical[side]),
                "unit_count": len(canonical[side]["units"]),
            }
        record.pop("fetch", None)
        record.pop("on_disk", None)
        admitted.append(record)

    families: dict[str, int] = {}
    containers: dict[str, int] = {}
    for record in admitted:
        families[record["family"]] = families.get(record["family"], 0) + 1
        containers[record["container"]] = containers.get(record["container"], 0) + 1

    body = {
        "schema": "tavonel.v2.p4c_cohort_manifest.v1",
        "protocol": "P4c_retrieval_validity",
        "started_at": started,
        "ended_at": now(),
        "selection_rule": SELECTION_RULE,
        "selection_rule_frozen_before_any_retrieval_result": True,
        "network_reads_only": True,
        "credentials_sent": False,
        "redistribution": REDISTRIBUTION,
        "dart": dart,
        "fetcher_sha256": sha_file(Path(__file__).resolve()),
        "sources_module_sha256": sha_file(
            Path(__file__).resolve().parent / "sources_p4c.py"
        ),
        "document_count": len(admitted),
        "family_counts": dict(sorted(families.items())),
        "container_counts": dict(sorted(containers.items())),
        "container_cap": CONTAINER_CAP,
        "excluded": excluded,
        "documents": admitted,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    written = write_immutable("p4c-cohort-manifest", body, tool=Path(__file__).resolve())
    print(
        json.dumps(
            {
                "documents": len(admitted),
                "families": body["family_counts"],
                "excluded": len(excluded),
                "dart": dart["state"],
                **written,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
