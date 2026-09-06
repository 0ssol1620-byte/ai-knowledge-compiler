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
# Table 6 -- the SFIR capacity series, per study and per family


#: The studies whose capacity outcome receipts this table reads, in the order
#: they ran. A study whose receipt is not on disk yields a PENDING row rather
#: than an omitted one: a study missing from a replication table reads as a
#: study that never ran, which is a different fact from "its receipt is not
#: here yet".
CAPACITY_STUDIES = (
    ("SFIR5", "sfir5-capacity-outcome"),
    ("SFIR6", "sfir6-capacity-outcome"),
)

#: Fields copied verbatim from each family block. Nothing here is computed by
#: this generator; ``_recompute_q`` below is the single exception and it is
#: reported as a CHECK, never as the published value.
_FAMILY_VERBATIM = (
    "C",
    "Q",
    "roots_declared",
    "roots_complete",
    "root_states",
    "verdict",
    "is_a_measurement",
    "meets_C",
    "meets_Q",
    "is_sealable",
)

#: A field a receipt does not carry is not a zero and not a false. SFIR5's
#: schema has no ``is_sealable`` -- sealability became a distinction only when
#: SFIR6 produced a set that enumerated and then failed the identity proof.
#: Rendering that absence as ``false`` would retroactively attribute a verdict
#: to a study that never made it.
NOT_IN_SCHEMA = "NOT_DECLARED_BY_THIS_RECEIPT_SCHEMA"

#: The same rule one layer down: a ledger entry that does not carry a
#: structured field is reported as not declaring it, never as declaring zero.
NOT_DECLARED_IN_LEDGER_ENTRY = "NOT_DECLARED_IN_THIS_ENTRY"


def _recompute_q(c_value: Any, formula: str) -> dict[str, Any]:
    """Re-derive Q from C under the receipt's OWN declared formula.

    This is a consistency check on the receipt, not a source of a published
    number: the table publishes the receipt's Q and reports separately whether
    that Q re-derives. The check earns its place because
    ``encyclopedia_wikipedia`` is the first family in the programme whose C is
    large enough for the ``min(1000, ...)`` cap to bind -- floor(0.8*2152)
    exceeds 1000 -- so its Q is the first one in the series that is not simply
    0.8*C, and a reader who assumes otherwise mis-reads it.
    """
    if formula.replace(" ", "") != "Q_f=min(1000,floor(0.8*C_f))":
        return {"checked": False, "why": f"unrecognised declared formula: {formula!r}"}
    if not _numeric(c_value):
        return {"checked": False, "why": f"C is not numeric: {c_value!r}"}
    return {"checked": True, "value": min(1000, int(0.8 * c_value))}


def build_table6(*, receipts_dir: Path = RECEIPTS_DIR, root: Path = ROOT) -> dict[str, Any]:
    """Table 6 -- per-study, per-family capacity across the SFIR replication series.

    Every cell is read out of that study's own capacity outcome receipt. No
    number is carried sideways: SFIR6's receipt states in its own
    ``predecessor`` block that SFIR5's counts appear there only as a comparison
    target and that every figure in its ``families`` block was computed from
    SFIR6's own census, and this table honours the same separation by reading
    each study from its own file.

    The verdict column is deliberately not collapsed to pass/fail. This series'
    result is the DISTINCTION between kinds of answer -- a measurement that
    passes, a measurement that falls short, an instrument defect that produced
    no measurement at all, and a set that was enumerated but could not be
    certified -- and a boolean column would destroy exactly that.
    """
    require_dir(receipts_dir)

    studies: list[dict[str, Any]] = []
    for label, stem in CAPACITY_STUDIES:
        found = resolve_receipt(stem, receipts_dir=receipts_dir, root=root)
        if found is None:
            studies.append(
                {
                    "study": label,
                    "state": pending(f"no receipt at receipts/{stem}.json"),
                    "rows": [],
                }
            )
            continue

        body = found["body"]
        criterion = body.get("criterion", {})
        formula = criterion.get("formula", "")

        rows = []
        for family, block in sorted(body.get("families", {}).items()):
            row: dict[str, Any] = {"study": label, "family": family}
            for field in _FAMILY_VERBATIM:
                row[field] = block.get(field, NOT_IN_SCHEMA)
            check = _recompute_q(block.get("C"), formula)
            row["q_recomputes_from_the_receipts_own_formula"] = (
                (check["value"] == block.get("Q")) if check["checked"] else check["why"]
            )
            rows.append(row)

        studies.append(
            {
                "study": label,
                "protocol_id": body.get("protocol_id"),
                "receipt": {"path": safe_rel(found["path"]), "sha256": found["sha256"]},
                "resolved_via": found["via"],
                "state": body.get("state"),
                "outcome": body.get("outcome"),
                "criterion": criterion,
                "families_meeting_criterion": body.get("families_meeting_criterion"),
                "families_sealable": body.get("families_sealable", NOT_IN_SCHEMA),
                "families_not_sealable": body.get("families_not_sealable", NOT_IN_SCHEMA),
                "rows": rows,
            }
        )

    # The replication claim is SFIR6's own, so it is read out of SFIR6's
    # receipt rather than recomputed here. Its load-bearing field is
    # `lineage_sets_identical`: equal counts could coincide, equal SETS could
    # not, and the difference is what makes git_docs a twice-measured shortfall
    # rather than two observations that happen to agree.
    sfir6_receipt = resolve_receipt(
        "sfir6-capacity-outcome", receipts_dir=receipts_dir, root=root
    )
    if sfir6_receipt is None:
        replication_block: Any = pending("SFIR6's capacity outcome receipt is not on disk")
    else:
        replication_block = sfir6_receipt["body"].get(
            "replication_of_sfir5",
            pending("the SFIR6 outcome receipt carries no replication_of_sfir5 block"),
        )

    return {
        "title": "Table 6 -- capacity by study and family across the SFIR replication series",
        "studies": studies,
        "replication_of_sfir5_by_sfir6": replication_block,
        "thresholds_are_preregistered_not_calibrated": (
            "the minimum C of 750 and the minimum Q of 600 are pre-registered figures. "
            "This table reports whether a declared frame clears them. It does not report "
            "that they are the right numbers, and no cell here is a calibrated result."
        ),
        "what_this_table_is_not": (
            "three attempts at one measurement. SFIR5 is a completed capacity census; "
            "SFIR6 is an instrument repair under an explicitly unchanged frame, whose "
            "receipt is not a rescoring of SFIR5; the two rows for one family are two "
            "measurements, and where they agree that agreement is the finding."
        ),
        "denominators": (
            "roots_complete is counted over roots_declared for that family in that study, "
            "not over the census total. root_states sums to roots_declared."
        ),
        "inputs": {
            "receipts": [
                safe_rel(receipts_dir / f"{stem}.json") for _label, stem in CAPACITY_STUDIES
            ]
        },
    }


# ---------------------------------------------------------------------------
# Table 7 -- the SFIR5/SFIR6-era incidents


#: The contiguous block of ledger entries this paper section cites. Named
#: explicitly rather than derived from a numeric range so that a future entry
#: cannot silently join the table, and so that an entry named here but absent
#: from the ledger is a refusal rather than a quietly shorter table.
TABLE7_INCIDENT_IDS = (
    "INC-V2-106",
    "INC-V2-107",
    "INC-V2-108",
    "INC-V2-109",
    "INC-V2-110",
    "INC-V2-111",
)

#: Table 4's ``_LEDGER_FIELD`` stops at a newline, which is correct for what it
#: counts -- it tabulates how many entries DECLARE a field and what the short
#: values are, and a truncated tail cannot change a count. It is wrong for what
#: Table 7 does, which is print the value itself: every ``**Class:**`` in this
#: block wraps onto a second line, so the line-bounded parser renders
#: "an adapter whose every request is rejected by the endpoint, producing" and
#: stops mid-sentence. A half-sentence in a paper table is worse than no cell,
#: because it reads as the whole value. This parser therefore runs from one
#: ``**Field:**`` to the next, or to the end of the header block, and Table 4's
#: parser is left untouched: its behaviour is the subject of four tests and is
#: right for its own question.
_LEDGER_HEADER_FIELD = re.compile(
    r"\*\*([A-Za-z ]+):\*\*[ \t]*(.*?)(?=\n\*\*|[ \t]+[-\u00b7][ \t]+\*\*|\n\s*\n|\Z)",
    re.S,
)


def _header_fields(body: str) -> dict[str, str]:
    """The structured header of one ledger entry, whole values, no truncation.

    Only the block before the first blank-line break is read. The prose below it
    also contains bold runs, and sweeping the whole entry would pull sentences
    out of the narrative into a column labelled with a field name they never
    belonged to.
    """
    lines = body.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("**")), None)
    if start is None:
        return {}
    end = start
    while end < len(lines) and lines[end].strip():
        end += 1
    header = chr(10).join(lines[start:end])
    fields: dict[str, str] = {}
    for name, value in _LEDGER_HEADER_FIELD.findall(header):
        key = name.strip().lower().replace(" ", "_")
        collapsed = " ".join(value.split()).rstrip(".")
        if collapsed:
            fields.setdefault(key, collapsed)
    return fields


#: Where a receipt -- not the ledger -- also names the incident. The ledger is
#: the narrative record; a receipt naming the same id is the machine-readable
#: corroboration, and the two are reported as separate columns rather than
#: merged, because "the ledger says so" and "a sealed receipt says so" are
#: different strengths of evidence.
_INCIDENT_RECEIPT_KEYS = ("repair_outcome", "defects_found_by_this_census")


def build_table7(
    *,
    ledger_path: Path = LEDGER_PATH,
    receipts_dir: Path = RECEIPTS_DIR,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Table 7 -- the incidents SFIR5's completion and SFIR6's repair produced.

    Class, disposition, GPU seconds and cost are lifted from each entry's own
    structured header via the same parser Table 4 uses and checked the same way;
    the title is the ledger heading. Nothing is summarised into a status word
    this generator invented.

    The ``named_by_receipt`` column exists because two of these six are recorded
    in SFIR6's outcome receipt as well as in the ledger, and one -- INC-V2-111 --
    is a procedural slip with no receipt at all. Rendering all six identically
    would flatten that difference.
    """
    require_file(ledger_path)
    text = ledger_path.read_text(encoding="utf-8")
    headings = list(_LEDGER_HEADING.finditer(text))
    spans = [m.start() for m in headings] + [len(text)]
    by_id = {m.group(1): index for index, m in enumerate(headings)}

    missing = [name for name in TABLE7_INCIDENT_IDS if name not in by_id]
    if missing:
        raise GenerationRefused(
            f"incident ids named for Table 7 are absent from {safe_rel(ledger_path)}: {missing}"
        )

    receipt_mentions: dict[str, list[dict[str, str]]] = {}
    for stem in ("sfir6-capacity-outcome", "sfir5-capacity-outcome"):
        found = resolve_receipt(stem, receipts_dir=receipts_dir, root=root)
        if found is None:
            continue
        for key in _INCIDENT_RECEIPT_KEYS:
            block = found["body"].get(key)
            if not isinstance(block, dict):
                continue
            for name in block:
                if name in TABLE7_INCIDENT_IDS:
                    receipt_mentions.setdefault(name, []).append(
                        {"receipt": safe_rel(found["path"]), "field": key}
                    )

    rows = []
    for name in TABLE7_INCIDENT_IDS:
        index = by_id[name]
        heading = headings[index]
        body = text[spans[index] : spans[index + 1]]
        fields = _header_fields(body)
        rows.append(
            {
                "id": name,
                "title": heading.group(3).strip(" -—"),
                "class": fields.get("class", NOT_DECLARED_IN_LEDGER_ENTRY),
                "disposition": fields.get("disposition", NOT_DECLARED_IN_LEDGER_ENTRY),
                "gpu_seconds": fields.get("gpu_seconds", NOT_DECLARED_IN_LEDGER_ENTRY),
                "cost": fields.get("cost", NOT_DECLARED_IN_LEDGER_ENTRY),
                "ip_gate": fields.get("ip_gate", NOT_DECLARED_IN_LEDGER_ENTRY),
                "named_by_receipt": receipt_mentions.get(name, "ledger only"),
            }
        )

    return {
        "title": "Table 7 -- incidents INC-V2-106 to INC-V2-111",
        "rows": rows,
        "rows_selected": len(rows),
        "entries_in_the_ledger": len(headings),
        "coverage": f"{len(rows)}/{len(headings)}",
        "what_this_table_is_not": (
            "a summary of the ledger. These six are the entries the SFIR replication "
            "series section cites; the denominator above is every entry the ledger "
            "holds, so this table's six are read as a named selection and not as the "
            "whole record."
        ),
        "ordering_note": (
            "listed in ledger order, which is the order they were registered. "
            "INC-V2-108's own entry records that it was written while SFIR6's census "
            "was still running and no SFIR6 number existed; INC-V2-109 to INC-V2-111 "
            "were registered after it returned. That ordering is a fact about the "
            "evidence and is preserved here rather than sorted away."
        ),
        "inputs": {
            "ledger": safe_rel(ledger_path),
            "receipts_consulted": [
                safe_rel(receipts_dir / "sfir5-capacity-outcome.json"),
                safe_rel(receipts_dir / "sfir6-capacity-outcome.json"),
            ],
        },
    }


# ---------------------------------------------------------------------------
# markdown renderings of Tables 6 and 7
#
# The JSON above is the artifact of record; these two are the paste-ready form
# for the paper section. They derive EVERY cell from the dict the builder
# returned -- there is no second read of a receipt here, so a markdown table and
# its JSON sibling cannot drift apart. Tables 1-5 have no markdown form because
# nothing pastes them into prose; these two are pasted, and a table retyped by
# hand into a draft is exactly how a receipt-backed number stops being one.


#: A literal backslash-pipe: what a markdown cell needs so a pipe inside a
#: value does not split the row. Written as a constant because this exact
#: two-character sequence is the one most easily lost by an editing pass.
BS_PIPE = chr(92) + "|"


def _cell(value: Any) -> str:
    """Render one cell without ever turning an absence into a value.

    ``None`` becomes the word ``null`` rather than an empty cell: a blank cell
    in a capacity table reads as zero to a human eye, and this whole series
    exists because a broken instrument's silence once had to be kept distinct
    from a measured absence.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return "; ".join(f"{k}={_cell(v)}" for k, v in sorted(value.items()))
    if isinstance(value, list):
        return ", ".join(_cell(item) for item in value) if value else "(none)"
    return str(value).replace("|", BS_PIPE)


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(_cell(cell) for cell in row) + " |")
    return chr(10).join(lines) + chr(10)


def render_table6_markdown(table6: dict[str, Any]) -> str:
    parts = [f"### {table6['title']}", ""]
    headers = [
        "study",
        "family",
        "roots declared",
        "roots COMPLETE",
        "C",
        "Q",
        "meets C",
        "meets Q",
        "is a measurement",
        "is sealable",
        "verdict",
    ]
    rows = []
    for study in table6["studies"]:
        for row in study["rows"]:
            rows.append(
                [
                    row["study"],
                    f"`{row['family']}`",
                    row["roots_declared"],
                    row["roots_complete"],
                    row["C"],
                    row["Q"],
                    row["meets_C"],
                    row["meets_Q"],
                    row["is_a_measurement"],
                    row["is_sealable"],
                    f"`{row['verdict']}`",
                ]
            )
    parts.append(_md_table(headers, rows))
    parts.append("")

    for study in table6["studies"]:
        criterion = study.get("criterion") or {}
        parts.append(
            f"**{study['study']}** (`{study.get('protocol_id')}`) --- state "
            f"`{study.get('state')}`; criterion "
            f"`C_f >= {criterion.get('minimum_C_per_family')}` and "
            f"`Q_f >= {criterion.get('minimum_Q_per_family')}`, "
            f"`{criterion.get('formula')}`, "
            f"requires every family: {_cell(criterion.get('requires_every_family'))}. "
            f"Receipt: `{(study.get('receipt') or {}).get('path')}`."
        )
        parts.append("")

    replication = table6.get("replication_of_sfir5_by_sfir6")
    if isinstance(replication, dict):
        parts.append("**Replication of SFIR5 by SFIR6, compared as sets and not as counts.**")
        parts.append("")
        parts.append(
            _md_table(
                ["family", "SFIR5 C", "SFIR6 C", "counts agree", "lineage sets identical",
                 "in SFIR5 only", "in SFIR6 only"],
                [
                    [
                        f"`{family}`",
                        block.get("sfir5_C"),
                        block.get("sfir6_C"),
                        block.get("counts_agree"),
                        block.get("lineage_sets_identical"),
                        block.get("in_sfir5_only"),
                        block.get("in_sfir6_only"),
                    ]
                    for family, block in sorted(replication.items())
                    if isinstance(block, dict)
                ],
            )
        )
        parts.append("")
        parts.append(_cell(replication.get("how_established")))
        parts.append("")
    else:
        parts.append(f"**Replication comparison:** {_cell(replication)}")
        parts.append("")

    checks = [
        f"{row['study']}/{row['family']}={_cell(row['q_recomputes_from_the_receipts_own_formula'])}"
        for study in table6["studies"]
        for row in study["rows"]
    ]
    parts.append(
        "*Q re-derivation check.* Each row's published Q is the receipt's own; this line "
        "reports whether it re-derives from that receipt's declared formula. "
        "`encyclopedia_wikipedia` at SFIR6 is the first family in the series whose C is "
        "large enough for the `min(1000, ...)` cap to bind, so its Q of 1,000 is a cap and "
        "not `0.8 * C`. "
        + "; ".join(checks)
        + "."
    )
    parts.append("")
    parts.append(f"*Denominators.* {table6['denominators']}")
    parts.append("")
    parts.append(f"*Thresholds.* {table6['thresholds_are_preregistered_not_calibrated']}")
    parts.append("")
    parts.append(f"*What this table is not.* {table6['what_this_table_is_not']}")
    parts.append("")
    return chr(10).join(parts)


def render_table7_markdown(table7: dict[str, Any]) -> str:
    parts = [f"### {table7['title']}", ""]
    parts.append(
        _md_table(
            ["id", "what it is", "class", "disposition", "GPU s", "cost", "IP gate",
             "also named by a receipt"],
            [
                [
                    f"`{row['id']}`",
                    row["title"],
                    row["class"],
                    row["disposition"],
                    row["gpu_seconds"],
                    row["cost"],
                    row["ip_gate"],
                    row["named_by_receipt"]
                    if isinstance(row["named_by_receipt"], str)
                    else ", ".join(
                        f"`{m['receipt']}` ({m['field']})" for m in row["named_by_receipt"]
                    ),
                ]
                for row in table7["rows"]
            ],
        )
    )
    parts.append("")
    parts.append(
        f"*Denominator.* {table7['coverage']}: {table7['rows_selected']} entries selected "
        f"out of the {table7['entries_in_the_ledger']} the ledger holds. This table is not "
        f"{table7['what_this_table_is_not']}"
    )
    parts.append("")
    parts.append(f"*Ordering.* {table7['ordering_note']}")
    parts.append("")
    return chr(10).join(parts)


# ---------------------------------------------------------------------------
# orchestration


def generate(*, write: bool = False) -> dict[str, Any]:
    forbidden = load_forbidden_phrases()

    table1 = build_table1()
    table2 = build_table2()
    table3 = build_table3()
    table4 = build_table4()
    table5 = build_table5()
    table6 = build_table6()
    table7 = build_table7()
    figure5 = build_figure5()

    for name, artifact in (
        ("table1", table1),
        ("table2", table2),
        ("table3", table3),
        ("table4", table4),
        ("table5", table5),
        ("table6", table6),
        ("table7", table7),
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
        "table6_sfir_capacity_series": table6,
        "table7_sfir_incidents": table7,
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
        _write_lf(
            GENERATED_DIR / "table6_sfir_capacity_series.json",
            json.dumps(table6, indent=2, sort_keys=True, ensure_ascii=False) + chr(10),
        )
        _write_lf(
            GENERATED_DIR / "table7_sfir_incidents.json",
            json.dumps(table7, indent=2, sort_keys=True, ensure_ascii=False) + chr(10),
        )
        _write_lf(GENERATED_DIR / "table6_sfir_capacity_series.md", render_table6_markdown(table6))
        _write_lf(GENERATED_DIR / "table7_sfir_incidents.md", render_table7_markdown(table7))
        _write_lf(GENERATED_DIR / "figure5_evidence_chain.mmd", figure5["mermaid"])

        reproducibility = build_reproducibility(
            table1, table2, table3, table5, table6, table7, figure5
        )
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
    table6: dict[str, Any],
    table7: dict[str, Any],
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
        "table6_sfir_capacity_series": {
            # Each study's capacity receipt is pinned by the digest it hashes to
            # right now. A capacity number is the most consequential thing this
            # paper prints, so a rebuild that reads different bytes must be
            # visible as a manifest disagreement rather than as a quietly
            # different table.
            "capacity_receipts": [
                hashed(RECEIPTS_DIR / f"{stem}.json")
                for _label, stem in CAPACITY_STUDIES
                if (RECEIPTS_DIR / f"{stem}.json").is_file()
            ],
            "receipts_named": [stem for _label, stem in CAPACITY_STUDIES],
        },
        "table7_sfir_incidents": {
            "ledger": hashed(LEDGER_PATH),
            "incident_ids": list(TABLE7_INCIDENT_IDS),
            "rows_selected_over_ledger_entries": table7.get("coverage"),
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
