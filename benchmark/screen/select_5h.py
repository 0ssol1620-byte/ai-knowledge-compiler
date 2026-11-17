"""Section 5H selection as one offline module (WO-D08-7): S1, S2, S3 and the recipe digest.

USD 0, no model call. Inputs are the S0 ``run_screen`` records, the raw outputs they point
at, the dev gold and the frozen manifest behind a ``HoldoutGuard``.

* H (hard) = pages whose manifest ``page_origin`` is ``synthetic_degradation``
  (synthetically degraded prints, never real scans); R (representative) = every other page.
* S1 reuses ``paired_report.build_report`` cells, never its routes. Leader L = best on H by
  the report's rank key (baseline first on a tie, then id). A clear loser has its Wilson upper
  bound below L's Wilson lower bound on H and on R. McNemar (page all-exact against L) is
  reported, not a gate. The top five non-losers by rank are kept, plus the baseline
  when it is itself a clear loser (at most six); fewer than four are topped up.
* S2 reads every kept candidate's value per critical field with reader v1 (a failed page is
  all wrong) and gives the rescue matrix on H, R and pooled with its denominators, then picks
  the second and third member by rescued fields on H per measured USD per page. A candidate
  adding fewer than MIN_MARGINAL_FIELDS of the fields the chosen members all miss is not a
  member; the pick stops when no candidate remains.
* S3 raises its signals from the anchor alone (the field's question: id, kind, anchor); the
  gold value is read only afterwards, to score them.
* The recipe carries one digest over everything section 5H freezes before the holdout.

Every stage reads its pages through ``HoldoutGuard.load``; a record of a page outside what
the guard returned is refused. Outputs are plain dicts whose bytes come from
``canonical_json_bytes``, so a second run on the same inputs is byte-identical.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from benchmark.screen import critical_fields
from benchmark.screen.critical_fields import gold_value, value_after_anchor
from benchmark.screen.jev_calibration import auroc
from benchmark.screen.manifest import HoldoutGuard, HoldoutSealedError
from benchmark.screen.paired_report import INSUFFICIENT, _rank_key, build_report
from benchmark.v6.contracts import (
    ContractError,
    canonical_json_bytes,
    canonical_sha256,
    require_commit,
    require_sha256,
)
from benchmark.w6.v2.grading import wilson_interval

READER_V1_SHA256 = "sha256:ad0426213092ae4ce1e00796c07204524442db2f1310995ea4c01ed52d98d8e3"
DEGRADED = "synthetic_degradation"
H, R, POOLED = "H", "R", "pooled"
KEEP_MAX, KEEP_MIN = 5, 4
MIN_MARGINAL_FIELDS = 3  # (A) section 5H
MAX_MEMBERS = 3
SIGNALS = {
    "disagreement": "a peer reads a value after the field's anchor that differs from P's",
    "no_value": "P's page failed or P's output has no parseable value after the anchor",
    "reread_differs": "P read a second time gives a different value after the anchor",
}
_Key = tuple[str, str]  # (page_id, field_id)


def dump(obj: Any) -> bytes:
    """The bytes a stage output is written as; identical inputs give identical bytes."""
    return canonical_json_bytes(obj)


def _reader_digest() -> str:
    got = "sha256:" + hashlib.sha256(Path(critical_fields.__file__).read_bytes()).hexdigest()
    if got != READER_V1_SHA256:
        raise ContractError(f"critical_fields.py is {got}, not reader v1 {READER_V1_SHA256}")
    return got


def _scope(
    guard: HoldoutGuard, split: str, purpose: str, recipe: str | None = None
) -> tuple[dict[str, str], set[str], str]:
    """Page id -> subset for the pages the guard opens (the guard enforces the holdout rule)."""
    docs = guard.load(split, purpose, recipe)
    subset: dict[str, str] = {}
    for doc in docs:
        origin = doc.get("page_origin")
        if not isinstance(origin, str) or not origin:
            raise ContractError(f"{doc['doc_id']}: page_origin is required to place it in H or R")
        for p in range(doc["page_count"]):
            subset[f"{doc['doc_id']}#{p}"] = H if origin == DEGRADED else R
    return subset, {d["doc_id"] for d in docs}, split


def _check(
    records: Sequence[dict[str, Any]], scope: tuple[dict[str, str], set[str], str]
) -> dict[str, dict[str, dict[str, Any]]]:
    """candidate -> page_id -> record; out-of-scope, duplicate or missing pages refuse."""
    subset, doc_ids, split = scope
    by: dict[str, dict[str, dict[str, Any]]] = {}
    for r in records:
        if r["doc_id"] not in doc_ids or r["page_id"] not in subset or r.get("split") != split:
            raise HoldoutSealedError(f"{r['page_id']}: not a {split} page this stage may read")
        pages = by.setdefault(r["candidate_id"], {})
        if r["page_id"] in pages:
            raise ValueError(f"duplicate record for {r['candidate_id']} {r['page_id']}")
        pages[r["page_id"]] = r
    for cand, pages in by.items():
        if set(pages) != set(subset):
            missing = sorted(set(subset) - set(pages))
            raise ValueError(
                f"{cand}: no terminal record for {len(missing)} page(s), {missing[:1]}"
            )
    return by


def _records_sha(records: Iterable[dict[str, Any]]) -> str:
    return canonical_sha256(sorted(records, key=lambda r: (r["candidate_id"], r["page_id"])))


def _order(cells: Mapping[str, dict[str, Any]], baseline: str) -> list[str]:
    for c, cell in cells.items():
        if cell["critical_exact_rate"] == INSUFFICIENT:
            raise ValueError(f"{c}: no gold critical field in a subset; cannot rank")
    return sorted(cells, key=lambda c: (_rank_key(cells[c]), c != baseline, c))


def select_s1(
    records: Sequence[dict[str, Any]], *, guard: HoldoutGuard, baseline: str
) -> dict[str, Any]:
    """S1: leader on H, clear losers on H and R, keep rules, McNemar against the leader."""
    scope = _scope(guard, "dev", "tune")
    by = _check(records, scope)
    if baseline not in by:
        raise ValueError(f"baseline {baseline!r} has no records")
    if len(by) < 2:
        raise ValueError("fewer than 2 candidates: stop and report (5H stop rule)")
    relabelled = [{**r, "stratum": scope[0][r["page_id"]]} for r in records]
    first = build_report(relabelled, incumbent=baseline)
    if set(first["strata"]) != {H, R}:
        raise ValueError(f"dev pages must cover H and R, got {sorted(first['strata'])}")
    cells = {s: first["strata"][s]["cells"] for s in (H, R)}
    order = {s: _order(cells[s], baseline) for s in (H, R)}
    leader = order[H][0]
    paired = build_report(relabelled, incumbent=leader)["strata"]
    losers = {
        c
        for c in by
        if c != leader
        and all(
            cells[s][c]["critical_exact_ci"][1] < cells[s][leader]["critical_exact_ci"][0]
            for s in (H, R)
        )
    }
    survivors = [c for c in order[H] if c not in losers]
    best_r = next(c for c in order[R] if c not in losers)
    # Up to five non-losers by rank; the reference is added when it is itself a clear loser.
    keep = set(survivors[:KEEP_MAX])
    if baseline in losers:
        keep.add(baseline)
    if len(keep) < KEEP_MIN:
        keep |= set([c for c in order[H] if c not in keep][: KEEP_MIN - len(keep)])
    return {
        "stage": "S1",
        "inputs": {
            "records_sha256": _records_sha(records),
            "manifest_sha256": guard._manifest["manifest_sha256"],
            "baseline": baseline,
        },
        "leader": leader,
        "order": order,
        "best_on_R": best_r,
        "clear_losers": sorted(losers),
        "kept": [c for c in order[H] if c in keep],
        "dropped": [c for c in order[H] if c not in keep],
        "cells": cells,
        "mcnemar_vs_leader": {s: paired[s]["paired_vs_incumbent"] for s in (H, R)},
    }


def load_texts(records: Sequence[dict[str, Any]], raw_dir: Path) -> dict[str, str]:
    """raw_sha256 -> output text, read from run_screen's raw files; a changed byte refuses."""
    out: dict[str, str] = {}
    for r in records:
        if r["raw_sha256"] is None:
            continue
        data = (Path(raw_dir) / (r["record_key"].removeprefix("sha256:") + ".json")).read_bytes()
        if "sha256:" + hashlib.sha256(data).hexdigest() != r["raw_sha256"]:
            raise ContractError(f"{r['page_id']}: raw output differs from its record")
        out[r["raw_sha256"]] = str(json.loads(data).get("text") or "")
    return out


def _question(field: Mapping[str, Any]) -> dict[str, Any]:
    """What a signal may see of a gold field: the question, never the answer."""
    return {"field_id": field["field_id"], "kind": field["kind"], "anchor": field["anchor"]}


def _reads(
    by: Mapping[str, Mapping[str, dict[str, Any]]],
    texts: Mapping[str, str],
    gold: Mapping[str, dict[str, Any]],
    cands: Iterable[str],
) -> tuple[dict[str, dict[_Key, Any]], dict[str, dict[_Key, bool]]]:
    """Per candidate and field: the value read (None = failed or none) and whether it is right."""
    read: dict[str, dict[_Key, Any]] = {}
    right: dict[str, dict[_Key, bool]] = {}
    for c in cands:
        read[c], right[c] = {}, {}
        for page_id, r in sorted(by[c].items()):
            fields = gold[page_id].get("critical_fields") or []
            if len(fields) != r["critical"]["n"] or len({f["field_id"] for f in fields}) != len(
                fields
            ):
                raise ValueError(f"{page_id}: gold fields do not match the record's critical n")
            failed = bool(r["hard_failures"])
            text = None if failed else texts[r["raw_sha256"]]
            for f in fields:
                key = (page_id, str(f["field_id"]))
                v = None if text is None else value_after_anchor(_question(f), text)
                read[c][key] = v
                right[c][key] = not failed and v is not None and v == gold_value(f)
            exact = sum(right[c][(page_id, str(f["field_id"]))] for f in fields)
            if not failed and exact != r["critical"]["exact"]:
                raise ValueError(
                    f"{c} {page_id}: text gives {exact} exact, record says {r['critical']['exact']}"
                )
    return read, right


def _keys(right: Mapping[_Key, bool], subset: Mapping[str, str], part: str) -> list[_Key]:
    return sorted(k for k in right if part == POOLED or subset[k[0]] == part)


def _rescue(
    right: Mapping[str, Mapping[_Key, bool]], keys: list[_Key], a: str, b: str
) -> dict[str, Any]:
    """One directed row in the shape of akc_router.complementarity.RescueMeasurement; the
    ``*_pages`` names are kept for the shape, the unit is the critical field."""
    wrong = [k for k in keys if not right[a][k]]
    rescued = sum(right[b][k] for k in wrong)
    both = len(wrong) - rescued
    return {
        "element": "critical_field",
        "unit": "critical_field",
        "baseline": a,
        "peer": b,
        "rescue_rate": rescued / len(wrong) if wrong else None,
        "baseline_wrong_pages": len(wrong),
        "scored_pages": len(keys),
        "both_wrong_rate": both / len(keys) if keys else None,
        "rescued_fields": rescued,
        "both_wrong_fields": both,
        "denominator": f"{len(wrong)} fields {a} got wrong, of {len(keys)} scored",
    }


MAX_UNKNOWN_COST_SHARE = 0.2  # the share S0 tolerates for provider failures (5H-7)


def _cost_per_page(pages: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Mean of the known page costs, with both counts; unknown only above a fifth of pages."""
    costs = [r["provider_cost_usd"] for r in pages]
    known = [c for c in costs if c is not None]
    unknown = not known or (len(costs) - len(known)) / len(costs) > MAX_UNKNOWN_COST_SHARE
    return {
        "usd": None if unknown else sum(known) / len(known),
        "known": len(known),
        "total": len(costs),
    }


def _gold_sha(gold: Mapping[str, Any], pages: Iterable[str]) -> str:
    return canonical_sha256({p: gold[p] for p in pages})


def _texts_sha(texts: Mapping[str, str], records: Iterable[dict[str, Any]]) -> str:
    used = {r["raw_sha256"] for r in records if r["raw_sha256"] is not None}
    return canonical_sha256({k: texts[k] for k in sorted(used) if k in texts})


def complementarity_s2(
    records: Sequence[dict[str, Any]],
    texts: Mapping[str, str],
    gold: Mapping[str, dict[str, Any]],
    *,
    guard: HoldoutGuard,
    s1: Mapping[str, Any],
) -> dict[str, Any]:
    """S2: field rescue matrix on H / R / pooled; second and third member per rescued USD."""
    scope = _scope(guard, "dev", "calibrate")
    by = _check(records, scope)
    if (
        s1["inputs"]["records_sha256"] != _records_sha(records)
        or s1["inputs"]["manifest_sha256"] != guard._manifest["manifest_sha256"]
    ):
        raise ContractError("S1 was computed from other records or another manifest than S2's")
    kept, leader = list(s1["kept"]), s1["leader"]
    _, right = _reads(by, texts, gold, kept)
    matrix = {
        part: [
            _rescue(right, _keys(right[leader], scope[0], part), a, b)
            for a in kept
            for b in kept
            if a != b
        ]
        for part in (H, R, POOLED)
    }
    hard = _keys(right[leader], scope[0], H)
    cost = {c: _cost_per_page(by[c][p] for p in sorted(scope[0]) if scope[0][p] == H) for c in kept}
    members, steps = [leader], []
    while len(members) < MAX_MEMBERS:
        missed = [k for k in hard if not any(right[m][k] for m in members)]
        options = []
        for c in kept:
            if c in members:
                continue
            marginal = sum(right[c][k] for k in missed)
            usd = cost[c]["usd"]
            reason = (
                "marginal_below_minimum"
                if marginal < MIN_MARGINAL_FIELDS
                else "cost_unknown"
                if usd is None
                else None
            )
            options.append(
                {
                    "candidate": c,
                    "marginal_fields": marginal,
                    "cost_per_page_usd": usd,
                    "cost_pages_known": cost[c]["known"],
                    "cost_pages_total": cost[c]["total"],
                    "rescued_per_usd": marginal / usd if usd else None,
                    "excluded": reason,
                }
            )
        live = [o for o in options if o["excluded"] is None]
        # Zero measured cost ranks first; then rescued per USD, rescued fields, id.
        live.sort(
            key=lambda o: (
                o["cost_per_page_usd"] != 0,
                -(o["rescued_per_usd"] or 0),
                -o["marginal_fields"],
                o["candidate"],
            )
        )
        chosen = live[0]["candidate"] if live else None
        steps.append(
            {
                "position": len(members) + 1,
                "fields_missed_by_members": len(missed),
                "options": options,
                "chosen": chosen,
            }
        )
        if chosen is None:
            break
        members.append(chosen)
    return {
        "stage": "S2",
        "inputs": {
            "records_sha256": _records_sha(records),
            "texts_sha256": _texts_sha(texts, records),
            "gold_sha256": _gold_sha(gold, sorted(scope[0])),
            "manifest_sha256": guard._manifest["manifest_sha256"],
            "s1_sha256": canonical_sha256(s1),
            "reader_v1_sha256": _reader_digest(),
        },
        "primary": leader,
        "members": members,
        "pick_steps": steps,
        "min_marginal_fields": MIN_MARGINAL_FIELDS,
        "matrix": matrix,
        "cited_not_reused": "akc_router.complementarity MEASURED_RESCUES (page edit distance, "
        "another benchmark)",
    }


def _signals(p: Any, peers: Sequence[Any], reread: Any, measured: bool) -> dict[str, Any]:
    """Raised from values read after the anchor only; no gold reaches this function."""
    n = sum(v is not None and v != p for v in peers)
    return {
        "disagreement": n,
        "no_value": p is None,
        "reread_differs": (reread != p) if measured else None,
    }


def _score(rows: list[tuple[dict[str, Any], bool]], name: str) -> dict[str, Any]:
    flagged = [ok for s, ok in rows if s[name]]
    unflagged = [ok for s, ok in rows if not s[name]]
    fa = sum(not ok for ok in unflagged)
    return {
        "fields": len(rows),
        "flagged": len(flagged),
        "share_flagged": len(flagged) / len(rows) if rows else None,
        "unflagged": len(unflagged),
        "false_accepts": fa,
        "false_accept_rate": fa / len(unflagged) if unflagged else None,
        "false_accept_wilson_95": wilson_interval(fa, len(unflagged)) if unflagged else None,
        "wasted_escalations": sum(flagged),
    }


def _check_recipe(
    recipe: Mapping[str, Any] | None,
    digest: str,
    members: Sequence[str],
    escalate_on: Sequence[str],
    records: Sequence[dict[str, Any]],
) -> None:
    """The run must be the frozen recipe: same digest, same body, same members and signals,
    and every record carries the pins (revision, image digest, config digest) the recipe froze."""
    if recipe is None:
        raise ContractError("a frozen recipe digest needs the recipe body it names")
    body = {k: v for k, v in recipe.items() if k != "recipe_sha256"}
    if not (canonical_sha256(body) == recipe.get("recipe_sha256") == digest):
        raise ContractError("the recipe body does not hash to the frozen recipe digest")
    if list(members) != recipe["member_order"] or [
        m["candidate_id"] for m in recipe["members"]
    ] != list(members):
        raise ContractError("members differ from the frozen recipe")
    if sorted(escalate_on) != recipe["escalate_on"]:
        raise ContractError("escalation signals differ from the frozen recipe")
    frozen = {
        m["candidate_id"]: (m["revision"], m["image_digest"], m["config_sha256"])
        for m in recipe["members"]
    }
    for r in records:
        if r["candidate_id"] in frozen and frozen[r["candidate_id"]] != (
            r["revision"],
            r["image_digest"],
            r["config_sha256"],
        ):
            raise ContractError(
                f"{r['candidate_id']} {r['page_id']}: pins differ from the frozen recipe"
            )


def signals_s3(
    records: Sequence[dict[str, Any]],
    texts: Mapping[str, str],
    gold: Mapping[str, dict[str, Any]],
    *,
    guard: HoldoutGuard,
    members: Sequence[str],
    escalate_on: Sequence[str],
    reread_texts: Mapping[str, str | None] | None = None,
    split: str = "dev",
    frozen_recipe_sha256: str | None = None,
    recipe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """S3: the signals per field, scored per subset. ``reread_texts`` maps page_id to P's
    second output (None = failed); without it ``reread_differs`` is not measured. A holdout
    split opens only through the guard with the frozen recipe digest, and ``recipe`` (its body)
    must carry that digest, these members in this order and these escalation signals."""
    if len(members) < 2:
        raise ValueError("signals need P and at least one peer")
    if len(set(members)) != len(members):
        raise ContractError(f"duplicate member in {list(members)}")
    unknown = set(escalate_on) - set(SIGNALS)
    if unknown or not escalate_on or (reread_texts is None and "reread_differs" in escalate_on):
        raise ValueError(f"escalate_on must name measured signals of {sorted(SIGNALS)}")
    purpose = "calibrate" if split == "dev" else "evaluate_frozen"
    if frozen_recipe_sha256 is not None:
        _check_recipe(recipe, frozen_recipe_sha256, members, escalate_on, records)
    scope = _scope(guard, split, purpose, frozen_recipe_sha256)
    mine = [r for r in records if r["candidate_id"] in members]
    by = _check(mine, scope)
    if set(by) != set(members):
        raise ValueError(f"members without records: {sorted(set(members) - set(by))}")
    p, peers = members[0], list(members[1:])
    read, right = _reads(by, texts, gold, members)
    reread: dict[_Key, Any] = {}
    if reread_texts is not None:
        for page_id, page_gold in gold.items():
            if page_id not in scope[0]:
                continue
            text = reread_texts[page_id]
            for f in page_gold.get("critical_fields") or []:
                q = _question(f)
                reread[(page_id, str(f["field_id"]))] = (
                    None if text is None else value_after_anchor(q, text)
                )
    rows = {
        k: _signals(
            read[p][k], [read[c][k] for c in peers], reread.get(k), reread_texts is not None
        )
        for k in sorted(read[p])
    }
    for s in rows.values():
        s["escalate"] = any(bool(s[name]) for name in escalate_on)
    out: dict[str, Any] = {}
    for part in (H, R):
        scored = [(rows[k], right[p][k]) for k in _keys(right[p], scope[0], part)]
        names = (
            [*SIGNALS, "escalate"]
            if reread_texts is not None
            else ["disagreement", "no_value", "escalate"]
        )
        out[part] = {name: _score(scored, name) for name in names}
        out[part]["disagreement"]["auroc_wrong_by_disagreeing_peers"] = auroc(
            [(float(s["disagreement"]), not ok) for s, ok in scored]
        )
    return {
        "stage": "S3",
        "split": split,
        "frozen_recipe_sha256": frozen_recipe_sha256,
        "inputs": {
            "records_sha256": _records_sha(mine),
            "texts_sha256": _texts_sha(texts, mine),
            "reread_sha256": canonical_sha256(dict(reread_texts)) if reread_texts else None,
            "gold_sha256": _gold_sha(gold, sorted(scope[0])),
            "manifest_sha256": guard._manifest["manifest_sha256"],
            "reader_v1_sha256": _reader_digest(),
        },
        "primary": p,
        "peers": peers,
        "signals": {k: SIGNALS[k] for k in SIGNALS if k in out[H]},
        "escalate_on": sorted(escalate_on),
        "scores": out,
    }


def build_recipe(
    *,
    records: Sequence[dict[str, Any]],
    s1: Mapping[str, Any],
    s2: Mapping[str, Any],
    escalate_on: Sequence[str],
    degradation: Mapping[str, Any],
    scoring_commit: str,
    section_sha256: str,
) -> dict[str, Any]:
    """Everything 5H freezes before the holdout, under one digest for ``HoldoutGuard``."""
    if set(escalate_on) - set(SIGNALS) or not escalate_on:
        raise ValueError(f"escalate_on must name signals of {sorted(SIGNALS)}")
    if not {"seed", "parameters"} <= set(degradation):
        raise ContractError("degradation must record its seed and parameters")
    names = list(s2["members"])
    if len(set(names)) != len(names):
        raise ContractError(f"duplicate member in {names}")
    if set(names) - set(s1["kept"]):
        raise ContractError(f"members {sorted(set(names) - set(s1['kept']))} are not in S1's kept")
    if s2["inputs"]["records_sha256"] != _records_sha(records) or s2["inputs"][
        "s1_sha256"
    ] != canonical_sha256(s1):
        raise ContractError("lineage: S2 was not computed from these records and this S1")
    members = []
    for c in names:
        pins = {
            (r["revision"], r["image_digest"], r["config_sha256"])
            for r in records
            if r["candidate_id"] == c
        }
        if len(pins) != 1:
            raise ContractError(f"{c}: records carry {len(pins)} different pins, need exactly 1")
        rev, image, config = pins.pop()
        members.append(
            {"candidate_id": c, "revision": rev, "image_digest": image, "config_sha256": config}
        )
    body = {
        "members": members,
        "member_order": list(s2["members"]),
        "signals": {k: SIGNALS[k] for k in sorted(escalate_on)},
        "escalation_rule": "escalate a field iff any signal in escalate_on is raised; "
        "disagreement is raised at one or more disagreeing peers",
        "escalate_on": sorted(escalate_on),
        "degradation": dict(degradation),
        "reader_v1_sha256": _reader_digest(),
        "scoring_code_commit": require_commit(scoring_commit, "scoring_commit"),
        "s1_report_sha256": canonical_sha256(s1),
        "s2_matrix_sha256": canonical_sha256(s2),
        "section_5h_sha256": require_sha256(section_sha256, "section_sha256"),
    }
    return {**body, "recipe_sha256": canonical_sha256(body)}
