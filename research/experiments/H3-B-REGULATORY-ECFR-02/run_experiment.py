"""H3-B-REGULATORY-ECFR-02 -- Family B robustness across seven US regulators.

Audit section 28-C asks for at least one non-Wikipedia, production-shaped
revision family. This runner supplies eCFR (Title 21, Food and Drugs) while
reusing H3-B-CURRENT-CORE-PUBLIC-REVISION-01's evaluator byte-for-byte: only
the transport and the section projection are new, so a PASS here is evidence
about the corpus family and not about a different method.

eCFR was chosen over SEC filings for one reason that matters scientifically:
every content_version record carries a government-assigned `substantive`
boolean. That is an INDEPENDENT external label for "did the meaning change",
which Wikipedia has no equivalent of. It is reported next to TAVONEL's own
channel classification and is deliberately never used to select pairs or to
gate the result -- see protocol.forbidden.

Run:
    python run_experiment.py --freeze     # seal protocol + evaluator + core
    python run_experiment.py --run        # fetch, evaluate, write the receipt
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = Path(__file__).resolve().parent
PROTOCOL = EXPERIMENT / "protocol.json"
CORPUS = EXPERIMENT / "corpus"
RECEIPTS = EXPERIMENT / "receipts"
SEAL = RECEIPTS / "pre-fetch-seal.json"
RESULT = RECEIPTS / "regulatory-revision-result.json"
BLOCKED = RECEIPTS / "blocked-execution.json"

V01_RUNNER = (
    ROOT
    / "research"
    / "experiments"
    / "H3-B-CURRENT-CORE-PUBLIC-REVISION-01"
    / "run_experiment.py"
)
V03_SEAL = (
    ROOT
    / "research"
    / "experiments"
    / "H3-B-CURRENT-CORE-PUBLIC-REVISION-03"
    / "receipts"
    / "pre-fetch-seal.json"
)
AKC_CIR = ROOT / "packages" / "cir-python" / "src" / "akc_cir"

API = "https://www.ecfr.gov/api/versioner/v1"


def _load_v01() -> Any:
    """Import the sealed V01 runner as a module without executing its CLI."""

    spec = importlib.util.spec_from_file_location("h3b_v01_runner", V01_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the V01 evaluator")
    module = importlib.util.module_from_spec(spec)
    sys.modules["h3b_v01_runner"] = module
    spec.loader.exec_module(module)
    return module


V01 = _load_v01()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001 - provenance is best-effort
        return "unknown"


def load_protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL.read_text(encoding="utf-8"))


def frozen_hashes() -> dict[str, str]:
    """Hash everything whose change would invalidate this experiment.

    The entire live akc_cir package is included, exactly as V03 does: the
    result is a claim about the current core, so the core's bytes are part of
    what is sealed.
    """

    hashes = {
        "protocol.json": sha_file(PROTOCOL),
        "run_experiment.py": sha_file(Path(__file__)),
        "v01_evaluator": sha_file(V01_RUNNER),
    }
    for path in sorted(AKC_CIR.rglob("*.py")):
        hashes[str(path.relative_to(ROOT)).replace("\\", "/")] = sha_file(path)
    return hashes


def verify_hash_map(expected: dict[str, str]) -> None:
    for relative, digest in expected.items():
        if relative == "protocol.json":
            actual = sha_file(PROTOCOL)
        elif relative == "run_experiment.py":
            actual = sha_file(Path(__file__))
        elif relative == "v01_evaluator":
            actual = sha_file(V01_RUNNER)
        else:
            actual = sha_file(ROOT / relative)
        if actual != digest:
            raise RuntimeError(f"sealed file changed after freeze: {relative}")


def verify_v03_seal_still_valid() -> str:
    """Refuse to run if the earlier sealed experiment has been disturbed."""

    if not V03_SEAL.exists():
        raise RuntimeError("V03 seal is missing; refusing to run")
    seal = json.loads(V03_SEAL.read_text(encoding="utf-8"))
    for relative, digest in seal["hashes"].items():
        if not relative.startswith("packages/"):
            continue
        actual = sha_file(ROOT / relative)
        if actual != digest:
            raise RuntimeError(
                f"V03 sealed core file changed: {relative}; refusing to run"
            )
    return str(seal["seal_sha256"])


def freeze() -> int:
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    if SEAL.exists():
        raise RuntimeError("seal already exists; this experiment is single-seal")
    hashes = frozen_hashes()
    body = {
        "schema": "tavonel.family-b.regulatory-revision.seal.v2",
        "experiment_id": load_protocol()["experiment_id"],
        "sealed_at": now(),
        "git_head": git_head(),
        "v03_seal_sha256": verify_v03_seal_still_valid(),
        "hashes": hashes,
    }
    body["seal_sha256"] = sha_bytes(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    )
    SEAL.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"sealed": True, "seal_sha256": body["seal_sha256"]}))
    return 0


def verify_seal() -> dict[str, Any]:
    if not SEAL.exists():
        raise RuntimeError("no seal; run --freeze before --run")
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    verify_hash_map(seal["hashes"])
    verify_v03_seal_still_valid()
    return seal


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Revision:
    """Mirrors the V01 Revision contract so run_pair can consume it unchanged."""

    requested_title: str
    resolved_title: str
    revid: int
    parentid: int
    timestamp: str
    mw_sha1: str
    text: str


def _get(url: str, transport: dict[str, Any]) -> bytes:
    """GET with predeclared pacing and bounded, status-restricted retries."""

    retry_statuses = set(int(s) for s in transport["retry_only_for_http_status"])
    backoffs = [float(s) for s in transport["fallback_backoff_seconds_by_retry"]]
    attempts = int(transport["maximum_attempts_per_request"])
    request = urllib.request.Request(
        url, headers={"User-Agent": str(transport["user_agent"])}
    )
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in retry_statuses or attempt == attempts - 1:
                raise
            wait = backoffs[min(attempt, len(backoffs) - 1)]
            if transport["respect_retry_after_header"]:
                header = exc.headers.get("Retry-After") if exc.headers else None
                if header and header.strip().isdigit():
                    wait = min(
                        float(header.strip()),
                        float(transport["maximum_retry_wait_seconds"]),
                    )
            time.sleep(wait)
        except urllib.error.URLError as exc:
            last = exc
            if attempt == attempts - 1:
                raise
            time.sleep(backoffs[min(attempt, len(backoffs) - 1)])
    raise RuntimeError(f"request failed after {attempts} attempts: {last}")


def fetch_part_versions(title: int, part: str, transport: dict[str, Any]) -> list[dict]:
    url = f"{API}/versions/title-{title}.json?part={part}"
    time.sleep(float(transport["minimum_inter_request_seconds"]))
    payload = json.loads(_get(url, transport).decode("utf-8"))
    return list(payload.get("content_versions") or [])


def fetch_part_xml(
    title: int, part: str, date: str, transport: dict[str, Any]
) -> bytes:
    url = f"{API}/full/{date}/title-{title}.xml?part={part}"
    time.sleep(float(transport["minimum_inter_request_seconds"]))
    return _get(url, transport)


def select_pair_dates(versions: list[dict]) -> tuple[str, str] | None:
    """Two most recent distinct issue dates, oldest first.

    Deterministic and computed before any content is fetched.
    """

    dates = sorted({str(v["issue_date"]) for v in versions if v.get("issue_date")})
    if len(dates) < 2:
        return None
    return dates[-2], dates[-1]


def substantive_labels(versions: list[dict], before: str, after: str) -> dict[str, Any]:
    """Summarise the external label for the amendments in the selected window.

    Reported only. Never used to select or to gate.
    """

    window = [
        v
        for v in versions
        if v.get("issue_date") and before < str(v["issue_date"]) <= after
    ]
    return {
        "records_in_window": len(window),
        "substantive_true": sum(1 for v in window if v.get("substantive") is True),
        "substantive_false": sum(1 for v in window if v.get("substantive") is False),
        "any_substantive": any(v.get("substantive") is True for v in window),
        "sections": sorted({str(v.get("identifier")) for v in window})[:20],
    }


# ---------------------------------------------------------------------------
# Projection: eCFR XML -> the flat section text V01's projection consumes
# ---------------------------------------------------------------------------


def ecfr_sections_to_text(xml_bytes: bytes) -> str:
    """Render eCFR part XML into the heading/body form section_units() parses.

    V01's section_units() is a MediaWiki projection: it splits on `== heading ==`
    lines and accumulates body text. Rather than fork that sealed function, the
    regulatory hierarchy is rendered INTO that shape -- each DIV8 SECTION
    becomes one `== <section number> ==` heading followed by its paragraphs.
    The evaluator therefore sees the same input contract while the underlying
    corpus family is entirely different, which is exactly the property this
    robustness experiment needs.
    """

    root = ET.fromstring(xml_bytes)
    lines: list[str] = []
    for node in root.iter("DIV8"):
        if str(node.get("TYPE", "")).upper() != "SECTION":
            continue
        number = str(node.get("N", "")).strip()
        if not number:
            continue
        head_el = node.find("HEAD")
        head_text = "".join(head_el.itertext()).strip() if head_el is not None else ""
        lines.append(f"== {number} ==")
        if head_text:
            lines.append(head_text)
        for para in node.iter("P"):
            text = " ".join("".join(para.itertext()).split())
            if text:
                lines.append(text)
        lines.append("")
    return "\n".join(lines)


def build_revision(
    *, part: str, date: str, xml_bytes: bytes, index: int
) -> Revision:
    text = ecfr_sections_to_text(xml_bytes)
    return Revision(
        requested_title=f"21 CFR part {part}",
        resolved_title=f"21 CFR part {part}",
        revid=index,
        parentid=0,
        timestamp=f"{date}T00:00:00Z",
        mw_sha1=hashlib.sha1(xml_bytes).hexdigest(),  # noqa: S324 - provenance id only
        text=text,
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def run() -> int:
    protocol = load_protocol()
    seal = verify_seal()
    if RESULT.exists():
        raise RuntimeError("result already exists; this experiment is single-result")
    if CORPUS.exists() and any(p.is_file() for p in CORPUS.rglob("*")):
        raise RuntimeError("corpus is not empty before first run")

    transport = dict(protocol["transport"])
    selection = protocol["selection"]
    universe = [
        (int(entry["title"]), str(entry["part"])) for entry in selection["universe"]
    ]
    skip_headings: set[str] = set()

    fetched: list[tuple[str, Revision, Revision, dict[str, Any]]] = []
    try:
        for title, part in universe:
            if len(fetched) >= int(selection["target_pair_count"]):
                break
            versions = fetch_part_versions(title, part, transport)
            window = select_pair_dates(versions)
            if window is None:
                continue
            before_date, after_date = window
            before_xml = fetch_part_xml(title, part, before_date, transport)
            after_xml = fetch_part_xml(title, part, after_date, transport)
            before = build_revision(
                part=part, date=before_date, xml_bytes=before_xml, index=1
            )
            after = build_revision(
                part=part, date=after_date, xml_bytes=after_xml, index=2
            )
            if not before.text.strip() or not after.text.strip():
                continue
            labels = substantive_labels(versions, before_date, after_date)
            labels["before_date"] = before_date
            labels["after_date"] = after_date
            labels["before_xml_sha256"] = sha_bytes(before_xml)
            labels["after_xml_sha256"] = sha_bytes(after_xml)
            fetched.append((f"{title} CFR {part}", before, after, labels))
    except Exception as exc:  # noqa: BLE001 - transport failure is not a result
        RECEIPTS.mkdir(parents=True, exist_ok=True)
        blocked = {
            "schema": "tavonel.family-b.regulatory-revision.blocked.v2",
            "experiment_id": protocol["experiment_id"],
            "blocked_at": now(),
            "stage": "ecfr_fetch_before_corpus_persist",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "seal_sha256": seal["seal_sha256"],
            "corpus_files_persisted": 0,
            "external_gpu_cost_usd": 0.0,
        }
        BLOCKED.write_text(
            json.dumps(blocked, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(blocked, sort_keys=True), file=sys.stderr)
        return 3

    if len(fetched) < int(selection["minimum_evaluable_pairs"]):
        raise RuntimeError(
            f"only {len(fetched)} evaluable pairs; protocol requires "
            f"{selection['minimum_evaluable_pairs']}"
        )

    CORPUS.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    agreement: list[dict[str, Any]] = []

    for part, before, after, labels in fetched:
        (CORPUS / f"part-{part}-before.txt").write_text(before.text, encoding="utf-8")
        (CORPUS / f"part-{part}-after.txt").write_text(after.text, encoding="utf-8")
        record = V01.run_pair(before, after, skip_headings)
        record["part"] = part
        records.append(record)

        semantic = int(record["change_channel_counts"].get("semantic", 0))
        agreement.append(
            {
                "part": part,
                "before_date": labels["before_date"],
                "after_date": labels["after_date"],
                "ecfr_any_substantive": labels["any_substantive"],
                "ecfr_substantive_true": labels["substantive_true"],
                "ecfr_substantive_false": labels["substantive_false"],
                "tavonel_semantic_changes": semantic,
                "agrees": labels["any_substantive"] == (semantic > 0),
            }
        )
        print(
            json.dumps(
                {
                    "part": part,
                    "equivalent": record["equivalent"],
                    "stale": len(record["stale_left_behind"]),
                    "rebuild_fraction": record["rebuild_fraction"],
                    "semantic": semantic,
                    "ecfr_substantive": labels["any_substantive"],
                },
                sort_keys=True,
            )
        )

    gates = protocol["frozen_safety_gates"]
    stale_total = sum(len(r["stale_left_behind"]) for r in records)
    all_equivalent = all(r["equivalent"] for r in records)
    changed = [r for r in records if r["changed_logical_id_count"] > 0]
    safety_pass = all_equivalent and stale_total == int(gates["stale_left_behind_total"])
    adequacy_pass = len(changed) >= int(gates["minimum_changed_pair_count"])

    fractions = [float(r["rebuild_fraction"]) for r in records]
    avoided = [float(r["work_avoided_fraction"]) for r in records]
    channels: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    for r in records:
        channels.update(r["change_channel_counts"])
        kinds.update(r["change_kind_counts"])

    result = {
        "schema": "tavonel.family-b.regulatory-revision.result.v2",
        "experiment_id": protocol["experiment_id"],
        "completed_at": now(),
        "git_head": git_head(),
        "seal_sha256": seal["seal_sha256"],
        "v03_seal_sha256": seal["v03_seal_sha256"],
        "corpus_family": "us_federal_regulation_ecfr_seven_regulators",
        "pairs_evaluated": len(records),
        "all_pairs_equivalent": all_equivalent,
        "stale_left_behind_total": stale_total,
        "changed_pair_count": len(changed),
        "safety_gate_pass": safety_pass,
        "evidence_adequacy_pass": adequacy_pass,
        "mean_rebuild_fraction": sum(fractions) / len(fractions),
        "median_rebuild_fraction": sorted(fractions)[len(fractions) // 2],
        "max_rebuild_fraction": max(fractions),
        "mean_work_avoided_fraction": sum(avoided) / len(avoided),
        "channel_counts": dict(channels),
        "change_kind_counts": dict(kinds),
        "unresolved_identity_total": int(channels.get("unresolved", 0)),
        "external_label_comparison": {
            "note": (
                "Reported only. The eCFR substantive flag was never used to "
                "select pairs and is not a pass gate (protocol.forbidden)."
            ),
            "pairs": agreement,
            "agreement_count": sum(1 for a in agreement if a["agrees"]),
            "disagreement_count": sum(1 for a in agreement if not a["agrees"]),
        },
        "external_gpu_cost_usd": 0.0,
        "claim_boundary": protocol["claim_boundary"],
    }
    result["result_sha256"] = sha_bytes(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    )
    RESULT.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "pairs": len(records),
                "safety_gate_pass": safety_pass,
                "evidence_adequacy_pass": adequacy_pass,
                "mean_work_avoided": result["mean_work_avoided_fraction"],
                "label_agreement": result["external_label_comparison"][
                    "agreement_count"
                ],
                "label_disagreement": result["external_label_comparison"][
                    "disagreement_count"
                ],
            },
            sort_keys=True,
        )
    )
    return 0 if (safety_pass and adequacy_pass) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.freeze:
        return freeze()
    if args.run:
        return run()
    print("specify --freeze or --run", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
