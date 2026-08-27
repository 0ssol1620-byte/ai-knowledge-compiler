#!/usr/bin/env python3
"""Turn receipts and frozen protocol files into the paper's tables and figures.

This generator does not know any result. Every number it prints is read out of
a receipt or a protocol file that exists on disk right now, or the cell says
``PENDING (no receipt yet: <reason>)`` in words a reader cannot mistake for
data. There is no code path here that fills a missing value with 0, "" or
"N/A" -- those read as measurements, and this study's whole discipline is not
letting an absence read as a result.

``receipts/latest/*.json`` files are mutable convenience pointers, not
evidence (see ``tools/evidence.py``). This module never reads one without
verifying that the immutable file it names still hashes to what the pointer
says -- a mismatch is refused, not warned about, the same way
``tools/build_claim_matrix.py`` refuses a receipt whose bytes moved under a
pinned claim.

Five artifacts, matching PAPER CLOSURE PROGRAM Lane F:

* Table 1 -- source families and declared roots (``acquisition.sources_sfir4``
  and the SFIR4 design charter -- both exist today, so this table is fully
  populated).
* Table 2 -- the nine E1..E9 endpoints, PRIMARY vs the E8 VETO, and which
  claim-chain link (``paper/SFIR4_CLAIM_CHAIN.yaml``) each one's
  ``evidence_source`` field names. A link mentioned only in a ``measured``
  narrative, not in ``evidence_source``, does not count as a declared mapping
  -- that field is the one place the chain states a binding, and an endpoint
  it never names comes back UNMAPPED rather than guessed.
* Table 3 -- baselines. SFIR4 declares none of its own; this sweeps every
  frozen protocol for one, and reports what it finds instead of manufacturing
  a control this study does not have.
* Table 5 -- GPU seconds and USD, summed from every receipt directly under
  ``receipts/`` that carries the field, alongside how many receipts
  contributed, so a summed zero reads as measured rather than missing.
* Figure 5 -- the SFIR4 evidence chain as a Mermaid flowchart, one node per
  stage from charter freeze to acceptance, each labelled SEALED (with the sha
  it hashed to) or PENDING (with why), read fresh from ``receipts/`` on every
  run -- never hardcoded.

Also emits ``reproducibility.json``: the exact input files and their sha256
for every artifact above, written through ``common.write_hashed``.
"""

from __future__ import annotations

import importlib
import itertools
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

_HERE = Path(__file__).resolve().parent
NS = _HERE.parent
ROOT = NS.parents[1]

sys.path.insert(0, str(NS / "tools"))
sys.path.insert(0, str(NS))

import sfir4_execution as sfir4_execution_module  # noqa: E402
import sfir4_protocol as sfir4_protocol_module  # noqa: E402
import yaml  # noqa: E402
from acquisition import sources_sfir4 as sources_sfir4_module  # noqa: E402
from common import canonical_sha, now, rel, sha_file, write_hashed  # noqa: E402

try:
    gpu_successor_preflight_module: ModuleType | None = importlib.import_module(
        "gpu_successor_preflight"
    )
except ImportError:  # pragma: no cover -- optional, Table 3 degrades cleanly
    gpu_successor_preflight_module = None

GENERATED_DIR = NS / "paper" / "generated"
CLAIM_MATRIX_PATH = NS / "paper" / "CLAIM_MATRIX.yaml"
CLAIM_CHAIN_PATH = NS / "paper" / "SFIR4_CLAIM_CHAIN.yaml"
PROTOCOLS_DIR = NS / "protocols"
SFIR4_PROTOCOL_PATH = PROTOCOLS_DIR / "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4.yaml"
SFIR4_CHARTER_PATH = PROTOCOLS_DIR / "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4_DESIGN_CHARTER.yaml"
RECEIPTS_DIR = NS / "receipts"

POINTER_SCHEMA = "tavonel.v2.receipt_pointer.v1"

#: SFIR4's authority chain (charter, capacity, roster, protocol-freeze) is
#: verified by an exact path + sha256 supplied at call time
#: (``tools/sfir4_protocol.py::verify_authority``), not located by a fixed
#: filename convention in this tree. Naming a stem for these would be a guess;
#: this sentence is the honest state instead.
NO_FIXED_PATH_REASON = (
    "this stage's authority receipt is verified by an exact path + sha256 "
    "supplied at call time (tools/sfir4_protocol.py::verify_authority), not "
    "located by a fixed filename convention in this tree -- none is committed "
    "under research/tavonel_eval_v2/receipts/ as of this generator run"
)

FIGURE5_ORDER = (
    "charter_freeze",
    "spent_authority",
    "live_capacity_census",
    "capacity_seal",
    "roster_freeze",
    "protocol_freeze",
    "execution",
    "scoring",
    "acceptance",
)


class GenerationRefused(RuntimeError):
    """An input was absent, a digest mismatched, or a forbidden phrase surfaced."""


def pending(reason: str) -> str:
    return f"PENDING (no receipt yet: {reason})"


def safe_rel(path: Path) -> str:
    try:
        return str(rel(path))
    except ValueError:
        return str(path)


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise GenerationRefused(f"required input missing: {safe_rel(path)}")
    return path


def require_dir(path: Path) -> Path:
    if not path.is_dir():
        raise GenerationRefused(f"required input directory missing: {safe_rel(path)}")
    return path


# ---------------------------------------------------------------------------
# forbidden-phrase gate


def load_forbidden_phrases(claim_matrix_path: Path = CLAIM_MATRIX_PATH) -> list[tuple[str, str]]:
    require_file(claim_matrix_path)
    matrix = yaml.safe_load(claim_matrix_path.read_text(encoding="utf-8"))
    return [
        (entry["id"], phrase)
        for entry in matrix["forbidden_claims"]
        for phrase in entry["phrases"]
    ]


def assert_clean(text: str, forbidden: list[tuple[str, str]], *, where: str) -> None:
    """Refuse if any forbidden phrase (CLAIM_MATRIX.yaml's own list) appears in ``text``.

    This is the generator's own gate, not only a test's -- ``build_claim_matrix.py``
    scans the paper draft the same way; a generated table is exactly the kind of
    string a forbidden phrase could hide inside without anyone re-reading it by eye.
    """
    lowered = text.casefold()
    hits = [(claim_id, phrase) for claim_id, phrase in forbidden if phrase.casefold() in lowered]
    if hits:
        raise GenerationRefused(f"forbidden phrase found in {where}: {hits}")


# ---------------------------------------------------------------------------
# receipt resolution -- pointer-first, verified, fail-closed


def resolve_receipt(
    stem: str, *, receipts_dir: Path, root: Path
) -> dict[str, Any] | None:
    """Resolve one receipt by stem.

    Prefers ``<receipts_dir>/latest/<stem>.json`` (the immutable-pointer
    system): the pointer is followed and the target's sha256 is verified
    against ``points_to_file_sha256`` before anything is read from it. A
    missing target or a digest mismatch is refused, never silently skipped.

    Falls back to a bare ``<receipts_dir>/<stem>.json`` (a receipt written
    before the pointer system existed, per ``tools/evidence.py``'s own
    docstring). If that receipt declares its own ``receipt_sha256``, the
    self-hash is recomputed and a mismatch is refused the same way.

    Returns ``None`` when neither exists -- the caller decides what a
    genuine absence means (usually PENDING).
    """
    pointer_path = receipts_dir / "latest" / f"{stem}.json"
    if pointer_path.is_file():
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        if pointer.get("schema") != POINTER_SCHEMA:
            raise GenerationRefused(
                f"{safe_rel(pointer_path)} does not declare {POINTER_SCHEMA}"
            )
        target = root / pointer["points_to"]
        if not target.is_file():
            raise GenerationRefused(
                f"pointer {stem} names a target that does not exist: {pointer['points_to']}"
            )
        found_sha = sha_file(target)
        if found_sha != pointer["points_to_file_sha256"]:
            raise GenerationRefused(
                f"pointer {stem} digest mismatch: pointer says "
                f"{pointer['points_to_file_sha256']}, target hashes to {found_sha}"
            )
        body = json.loads(target.read_text(encoding="utf-8"))
        return {"path": target, "sha256": found_sha, "body": body, "via": "pointer"}

    bare_path = receipts_dir / f"{stem}.json"
    if bare_path.is_file():
        found_sha = sha_file(bare_path)
        body = json.loads(bare_path.read_text(encoding="utf-8"))
        declared = body.get("receipt_sha256")
        if declared:
            bare_body = {key: value for key, value in body.items() if key != "receipt_sha256"}
            if canonical_sha(bare_body) != declared:
                raise GenerationRefused(
                    f"{safe_rel(bare_path)}: declared self-hash does not recompute"
                )
        return {"path": bare_path, "sha256": found_sha, "body": body, "via": "legacy_bare"}

    return None


# ---------------------------------------------------------------------------
# Table 1 -- source families and declared roots


_PER_ROOT_CAP_KEY = {
    "git_docs": "max_candidates_per_repository",
    "regulation_ecfr": "max_candidates_per_title",
    "encyclopedia_wikipedia": "max_candidates_per_category",
}


def build_table1(
    *, sources_module: ModuleType = sources_sfir4_module, charter_path: Path = SFIR4_CHARTER_PATH
) -> dict[str, Any]:
    require_file(charter_path)
    charter = yaml.safe_load(charter_path.read_text(encoding="utf-8"))
    rule = charter["capacity_rule"]
    minimum_c = rule["minimum_c_per_family"]
    minimum_q = rule["minimum_q_per_family"]
    formula = rule["formula"]
    criterion = f"C_f >= {minimum_c}; Q_f = min(1000, floor(0.8*C_f)) >= {minimum_q} ({formula})"

    rows = []
    for family in sources_module.FAMILIES:
        cap_key = _PER_ROOT_CAP_KEY[family]
        rows.append(
            {
                "family": family,
                "authority": sources_module.FAMILY_AUTHORITIES[family],
                "declared_roots": len(sources_module.declared_roots(family)),
                "per_root_candidate_cap": sources_module.SOURCE_POOLS[family][cap_key],
                "capacity_criterion": criterion,
            }
        )

    return {
        "title": "Table 1 -- source families and declared roots",
        "rows": rows,
        "inputs": {
            "sources_module": "research/tavonel_eval_v2/acquisition/sources_sfir4.py",
            "charter": safe_rel(charter_path),
        },
    }


# ---------------------------------------------------------------------------
# Table 2 -- primary endpoints


def build_table2(
    *,
    execution_module: ModuleType = sfir4_execution_module,
    claim_chain_path: Path = CLAIM_CHAIN_PATH,
) -> dict[str, Any]:
    require_file(claim_chain_path)
    chain = yaml.safe_load(claim_chain_path.read_text(encoding="utf-8"))
    links = chain["links"]

    mapping: dict[str, set[str]] = {name: set() for name in execution_module.ENDPOINTS}
    short_codes = {name: name.split("_", 1)[0] for name in execution_module.ENDPOINTS}

    for link in links:
        link_id = link["id"]
        text = link.get("evidence_source", "") or ""
        for name, short in short_codes.items():
            if name in text:
                mapping[name].add(link_id)
                continue
            # A short code such as "E5" is a declared reference on its own
            # ("E5/E6", "E2 (provenance continuity)", "scores all of E2, E5,
            # E6, E7, E9"), but the same two characters also appear as one end
            # of a scope-range mention like "SFIR4's analysis floor (E1-E9)"
            # (L7's evidence_source) -- a range naming the whole protocol's
            # endpoint span, not a per-endpoint evidence binding for that
            # link. The hyphen guards on both sides exclude exactly that
            # range form without excluding the comma/slash/paren-delimited
            # short references the chain actually uses to bind a link.
            if re.search(rf"(?<!-)\b{re.escape(short)}\b(?!-)", text):
                mapping[name].add(link_id)

    rows = []
    for name in execution_module.ENDPOINTS:
        link_ids = sorted(mapping[name])
        rows.append(
            {
                "endpoint": name,
                "role": "VETO" if name == execution_module.VETO_ENDPOINT else "PRIMARY",
                "claim_links": link_ids if link_ids else "UNMAPPED",
            }
        )

    return {
        "title": "Table 2 -- primary endpoints",
        "rows": rows,
        "inputs": {
            "execution_module": "research/tavonel_eval_v2/tools/sfir4_execution.py",
            "claim_chain": safe_rel(claim_chain_path),
        },
    }


# ---------------------------------------------------------------------------
# Table 3 -- baselines


def build_table3(
    *,
    protocols_dir: Path = PROTOCOLS_DIR,
    preflight_module: ModuleType | None = gpu_successor_preflight_module,
) -> dict[str, Any]:
    require_dir(protocols_dir)

    checked: list[str] = []
    text_hits: list[dict[str, Any]] = []
    for path in sorted(protocols_dir.glob("*.yaml")):
        checked.append(safe_rel(path))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "baseline" in line.casefold():
                text_hits.append(
                    {"protocol_file": safe_rel(path), "line": lineno, "excerpt": line.strip()}
                )

    declared_arms: dict[str, Any] | None = None
    if preflight_module is not None and hasattr(preflight_module, "ARMS"):
        declared_arms = {
            "study": "GPU_SUCCESSOR preflight",
            "arms": list(preflight_module.ARMS),
            "cohort_floor": getattr(preflight_module, "COHORT_FLOOR", None),
            "status": "declared, not measured -- no cohort has been walked",
            "source": "research/tavonel_eval_v2/tools/gpu_successor_preflight.py::ARMS",
        }

    if declared_arms is None and not text_hits:
        return {
            "title": "Table 3 -- baselines",
            "rows": [{"status": "NO BASELINE DECLARED", "checked_protocols": checked}],
        }

    return {
        "title": "Table 3 -- baselines",
        "declared_arms": declared_arms,
        "text_mentions": text_hits,
        "checked_protocols": checked,
        "note": (
            "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4 (this paper's primary protocol) and its "
            "design charter declare no baseline arm of their own."
        ),
    }


# ---------------------------------------------------------------------------
# Table 5 -- efficiency / cost


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def build_table5(*, receipts_dir: Path = RECEIPTS_DIR) -> dict[str, Any]:
    require_dir(receipts_dir)

    gpu_total = 0.0
    gpu_count = 0
    cost_total = 0.0
    cost_count = 0
    scanned = 0

    for path in sorted(receipts_dir.glob("*.json")):
        scanned += 1
        body = json.loads(path.read_text(encoding="utf-8"))
        if "gpu_seconds" in body:
            value = body["gpu_seconds"]
            if not _numeric(value):
                raise GenerationRefused(f"{safe_rel(path)}: gpu_seconds is not numeric: {value!r}")
            gpu_total += value
            gpu_count += 1
        if "estimated_cost_usd" in body:
            value = body["estimated_cost_usd"]
            if not _numeric(value):
                raise GenerationRefused(
                    f"{safe_rel(path)}: estimated_cost_usd is not numeric: {value!r}"
                )
            cost_total += value
            cost_count += 1

    return {
        "title": "Table 5 -- efficiency / cost",
        "receipts_scanned": scanned,
        "gpu_seconds": {"sum": gpu_total, "contributing_receipts": gpu_count},
        "estimated_cost_usd": {"sum": cost_total, "contributing_receipts": cost_count},
        "inputs": {"receipts_dir": safe_rel(receipts_dir)},
    }


# ---------------------------------------------------------------------------
# Figure 5 -- the experimental evidence chain



def current_head(root: Path) -> str | None:
    """The commit this checkout is on, or None when git cannot say.

    None rather than a guess: "we could not ask git" and "the receipt is current"
    are different facts, and a receipt whose staleness is unknown must not be
    rendered as fresh.
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip() or None



LEDGER_PATH = NS / "incident_ledger.md"

_LEDGER_HEADING = re.compile(r"^## ((?:INC|STOP)-V2-(\d+))\b(.*)$", re.M)
#: Deliberately NOT anchored to the start of a line. The ledger writes
#: several fields on one line -- `**GPU seconds:** 0 - **Cost:** $0 -
#: **IP gate:** CLOSED` -- so a line-anchored pattern sees the first and
#: silently misses the rest. That under-counted GPU-seconds coverage as
#: 3/111 when 15 entries declare it, which would have understated the
#: ledger's own discipline in a table about that discipline.
#: The separator class is `[-\u00b7]` because the ledger uses BOTH an ASCII
#: hyphen and a middle dot between the trailing fields. Accepting only the
#: hyphen parsed 11 of the 15 GPU-seconds declarations, and the four it lost
#: were invisible -- a missed entry reads exactly like an entry that never
#: declared the field. The self-check below is what made them visible.
_LEDGER_FIELD = re.compile(
    r"\*\*([A-Za-z ]+):\*\*\s*([^*\n]+?)\s*"
    r"(?:[-\u00b7]\s*$|[-\u00b7]\s+(?=\*\*)|\.\s|\.$|$)",
    re.M,
)


#: The human label each normalised key came from, so the self-check can count
#: occurrences without going through the parser it is checking.
_FIELD_LABELS = {
    "class": "Class",
    "disposition": "Disposition",
    "gpu_seconds": "GPU seconds",
    "cost": "Cost",
    "estimated_cost": "Estimated cost",
}


def build_table4(*, ledger_path: Path = LEDGER_PATH) -> dict[str, Any]:
    """Table 4 -- the incident ledger, with the denominator of every count.

    This paper's thesis is that incidents are a first-class output, so the
    ledger is evidence and not bookkeeping. But its 111 entries were not written
    to one template: the structured `**Class:**` / `**Disposition:**` header is a
    recent convention, and most older entries carry prose instead.

    A table that tabulated only the entries carrying those fields would look
    clean and describe a biased subset -- the recent ones -- while reading as a
    summary of all of them. Every count here therefore reports how many entries
    it could see out of how many exist, which is the same rule the campaign
    applies to every published rate.
    """
    require_file(ledger_path)
    text = ledger_path.read_text(encoding="utf-8")
    headings = _LEDGER_HEADING.findall(text)
    spans = [m.start() for m in _LEDGER_HEADING.finditer(text)] + [len(text)]

    total = len(headings)
    inc = sum(1 for name, _, _ in headings if name.startswith("INC"))
    stop = total - inc

    declared: dict[str, dict[str, int]] = {}
    for index, (_name, _number, _rest) in enumerate(headings):
        body = text[spans[index] : spans[index + 1]]
        for field, value in _LEDGER_FIELD.findall(body):
            key = field.strip().lower().replace(" ", "_")
            if key not in {"class", "disposition", "gpu_seconds", "estimated_cost", "cost"}:
                continue
            bucket = declared.setdefault(key, {})
            bucket[value.strip()] = bucket.get(value.strip(), 0) + 1

    fields = {}
    for key, counts in sorted(declared.items()):
        seen = sum(counts.values())
        # The parser is checked against a count that does not use it. A regex
        # over prose written by hand across 111 entries WILL miss forms nobody
        # anticipated, and the failure is silent: a missed entry looks exactly
        # like an entry that never declared the field. In a table whose whole
        # purpose is to report honest denominators, a denominator its own parser
        # got wrong is the worst possible defect -- so the disagreement is
        # published beside the number rather than tuned until it disappears.
        label = re.escape(_FIELD_LABELS[key])
        raw = len(re.findall(r"\*\*" + label + r":\*\*", text))
        fields[key] = {
            "entries_declaring_it": seen,
            "entries_not_declaring_it": total - seen,
            "coverage": f"{seen}/{total}",
            "raw_occurrences_of_the_label": raw,
            "parser_agrees_with_a_raw_label_count": raw == seen,
            "unparsed": max(0, raw - seen),
            # Only the values are ranked; the reader is told what fraction of
            # the ledger the ranking describes.
            "values": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:12]),
        }

    return {
        "title": "Table 4 -- incident ledger composition",
        "entries_total": total,
        "incidents": inc,
        "stop_the_line": stop,
        "fields": fields,
        "parser_fully_agrees": all(
            f["parser_agrees_with_a_raw_label_count"] for f in fields.values()
        ),
        "what_this_table_is_not": (
            "a summary of all "
            + str(total)
            + " entries. The structured header is a recent convention, so each "
            "field's `coverage` is the denominator its value distribution "
            "describes; the remainder record the same facts in prose and are "
            "counted as not declaring the field rather than as absent data."
        ),
        "inputs": {"ledger": safe_rel(ledger_path)},
    }


def _node_no_fixed_path(node_id: str, label: str, schema: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "schema": schema,
        "stem": None,
        "state": pending(NO_FIXED_PATH_REASON),
    }


def _node_by_fixed_path(
    node_id: str, label: str, path: Path, *, receipts_dir: Path, root: Path
) -> dict[str, Any]:
    stem = path.stem
    found = resolve_receipt(stem, receipts_dir=receipts_dir, root=root)
    if found is None:
        return {
            "id": node_id,
            "label": label,
            "stem": stem,
            "state": pending(
                f"no receipt at receipts/{stem}.json (checked the pointer path and the bare file)"
            ),
        }
    body = found["body"]
    verdict = body.get("verdict")
    head = body.get("head_commit")
    node = {
        "id": node_id,
        "label": label,
        "stem": stem,
        # SEALED says a receipt EXISTS. It does not say the stage passed, and
        # `verdict` below is where that question is answered. Collapsing the two
        # is the delegation defect this study has paid for repeatedly: a true
        # statement about a narrower question ("a receipt is here") standing in
        # for a claim about a wider one ("this stage is good").
        "state": f"SEALED sha256={found['sha256']}",
        "receipt_verdict": verdict,
        "resolved_via": found["via"],
    }
    if head is not None:
        node["receipt_head_commit"] = head
        current = current_head(root)
        node["describes_current_head"] = None if current is None else (head == current)
    if body.get("generated_at") is not None:
        node["receipt_generated_at"] = body["generated_at"]
    return node


def build_figure5(
    *,
    receipts_dir: Path = RECEIPTS_DIR,
    root: Path = ROOT,
    protocol_path: Path = SFIR4_PROTOCOL_PATH,
    execution_module: ModuleType = sfir4_execution_module,
    protocol_module: ModuleType = sfir4_protocol_module,
) -> dict[str, Any]:
    require_dir(receipts_dir)
    require_file(protocol_path)
    protocol_doc = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    protocol_state = protocol_doc.get("state", "UNKNOWN")

    nodes = [
        _node_no_fixed_path("charter_freeze", "charter freeze", protocol_module.CHARTER_SCHEMA),
        _node_by_fixed_path(
            "spent_authority",
            "spent authority",
            execution_module.ACQUISITION_SPENT_AUTHORITY,
            receipts_dir=receipts_dir,
            root=root,
        ),
        _node_no_fixed_path(
            "live_capacity_census", "live capacity census", protocol_module.CAPACITY_INPUT_SCHEMA
        ),
        _node_no_fixed_path("capacity_seal", "capacity seal", protocol_module.CAPACITY_SCHEMA),
        _node_no_fixed_path("roster_freeze", "roster freeze", protocol_module.ROSTER_SCHEMA),
        _node_no_fixed_path(
            "protocol_freeze", "protocol freeze", protocol_module.PROTOCOL_FREEZE_SCHEMA
        ),
        _node_by_fixed_path(
            "execution",
            "execution",
            receipts_dir / "sfir4-execution-closure.json",
            receipts_dir=receipts_dir,
            root=root,
        ),
        _node_by_fixed_path(
            "scoring",
            "scoring",
            execution_module.SCORE_AUTHORITY,
            receipts_dir=receipts_dir,
            root=root,
        ),
        _node_by_fixed_path(
            "acceptance",
            "acceptance",
            execution_module.ACCEPTANCE_AUTHORITY,
            receipts_dir=receipts_dir,
            root=root,
        ),
    ]
    by_id = {node["id"]: node for node in nodes}
    by_id["protocol_freeze"]["protocol_file_note"] = (
        f"{safe_rel(protocol_path)} itself declares state={protocol_state} -- informational "
        "only, not a receipt, and does not change this node's SEALED/PENDING state"
    )

    lines = ["flowchart TD"]
    for node in nodes:
        # The mermaid label is what a reader of the PAPER sees. A node whose JSON
        # carries verdict=REFUSE while its diagram box reads only "SEALED"
        # publishes the opposite of what the receipt says, so the verdict and any
        # staleness are rendered here rather than left in a sibling field.
        state_text = node["state"]
        verdict = node.get("receipt_verdict")
        if verdict is not None:
            state_text += f"<br/>receipt verdict: {verdict}"
        if node.get("describes_current_head") is False:
            state_text += (
                "<br/>STALE: describes commit "
                f"{str(node.get('receipt_head_commit'))[:12]}, not current HEAD"
            )
        label_text = f"{node['label']}<br/>{node['stem'] or 'no fixed path'}<br/>{state_text}"
        label_text = label_text.replace('"', "'")
        lines.append(f'  {node["id"]}["{label_text}"]')
    for left, right in itertools.pairwise(FIGURE5_ORDER):
        lines.append(f"  {left} --> {right}")
    mermaid = "\n".join(lines) + "\n"

    return {
        "title": "Figure 5 -- the experimental evidence chain",
        "nodes": nodes,
        "mermaid": mermaid,
        "inputs": {"receipts_dir": safe_rel(receipts_dir), "protocol": safe_rel(protocol_path)},
    }


# ---------------------------------------------------------------------------
# orchestration


def generate(*, write: bool = False) -> dict[str, Any]:
    forbidden = load_forbidden_phrases()

    table1 = build_table1()
    table2 = build_table2()
    table3 = build_table3()
    table4 = build_table4()
    table5 = build_table5()
    figure5 = build_figure5()

    for name, artifact in (
        ("table1", table1),
        ("table2", table2),
        ("table3", table3),
        ("table4", table4),
        ("table5", table5),
        ("figure5", figure5),
    ):
        assert_clean(json.dumps(artifact, ensure_ascii=False), forbidden, where=name)

    result = {
        "generated_at": now(),
        "table1_source_families": table1,
        "table2_primary_endpoints": table2,
        "table3_baselines": table3,
        "table4_incident_ledger": table4,
        "table5_efficiency_cost": table5,
        "figure5_evidence_chain": figure5,
    }

    if write:
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        _write_lf(
            GENERATED_DIR / "table1_source_families.json",
            json.dumps(table1, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        )
        _write_lf(
            GENERATED_DIR / "table2_primary_endpoints.json",
            json.dumps(table2, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        )
        _write_lf(
            GENERATED_DIR / "table3_baselines.json",
            json.dumps(table3, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        )
        _write_lf(
            GENERATED_DIR / "table4_incident_ledger.json",
            json.dumps(table4, indent=2, sort_keys=True, ensure_ascii=False) + chr(10),
        )
        _write_lf(
            GENERATED_DIR / "table5_efficiency_cost.json",
            json.dumps(table5, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        )
        _write_lf(GENERATED_DIR / "figure5_evidence_chain.mmd", figure5["mermaid"])

        reproducibility = build_reproducibility(table1, table2, table3, table5, figure5)
        write_hashed(GENERATED_DIR / "reproducibility.json", reproducibility)

    return result



def _write_lf(path: Path, text: str) -> None:
    """Write with LF endings on every platform.

    ``Path.write_text`` translates ``
`` to the platform separator, so the same
    generator run on Windows and on Linux emits byte-different files for
    identical content. That is ordinarily harmless. It is not harmless here:
    ``build_reproducibility`` hashes these exact files with ``sha_file``, so a
    manifest whose entire purpose is to certify that a rebuild reproduces would
    disagree with itself across platforms -- for no reason but the line endings.

    This is the hazard ``research/tavonel_eval_v2/.gitattributes`` was written to
    close (``* -text -eol``, so a digest over the working tree means what it
    says), reappearing inside a generated artifact that git never normalises
    because it is never committed.
    """
    path.write_bytes(text.encode("utf-8"))


def build_reproducibility(
    table1: dict[str, Any],
    table2: dict[str, Any],
    table3: dict[str, Any],
    table5: dict[str, Any],
    figure5: dict[str, Any],
) -> dict[str, Any]:
    def hashed(path: Path) -> dict[str, str]:
        return {"path": safe_rel(path), "sha256": sha_file(path)}

    checked_protocol_paths = [
        PROTOCOLS_DIR / Path(entry).name for entry in table3.get("checked_protocols", [])
    ]
    protocols_checked = [
        hashed(path) for path in checked_protocol_paths if path.is_file()
    ]

    return {
        "schema": "tavonel.v2.paper_artifacts_reproducibility.v1",
        "generated_at": now(),
        "table1_source_families": {
            "sources_module": hashed(NS / "acquisition" / "sources_sfir4.py"),
            "charter": hashed(SFIR4_CHARTER_PATH),
        },
        "table2_primary_endpoints": {
            "execution_module": hashed(NS / "tools" / "sfir4_execution.py"),
            "claim_chain": hashed(CLAIM_CHAIN_PATH),
        },
        "table3_baselines": {
            "protocols_checked": protocols_checked,
            "preflight_module": (
                hashed(NS / "tools" / "gpu_successor_preflight.py")
                if table3.get("declared_arms")
                else None
            ),
        },
        "table5_efficiency_cost": {
            "receipts_dir": safe_rel(RECEIPTS_DIR),
            "receipts_scanned": table5["receipts_scanned"],
        },
        "figure5_evidence_chain": {
            "protocol": hashed(SFIR4_PROTOCOL_PATH),
            "resolved_receipts": [
                {"node": node["id"], "stem": node.get("stem"), "state": node["state"]}
                for node in figure5["nodes"]
            ],
        },
        "claim_matrix": hashed(CLAIM_MATRIX_PATH),
    }


def main() -> int:
    try:
        generate(write=True)
    except GenerationRefused as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 4
    print(json.dumps({"generated": True, "output_dir": safe_rel(GENERATED_DIR)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
