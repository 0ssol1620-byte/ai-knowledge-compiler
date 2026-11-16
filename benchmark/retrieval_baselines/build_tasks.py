"""Generate retrieval / temporal / ACL-negative task sets from the frozen revision-pair corpus.

    py -3.13 -m benchmark.retrieval_baselines.build_tasks --cache-dir <outside repo> --out <dir>

Everything written is ``provenance="generated"``: not blind gold, not annotated. Queries are
verbatim tokens of the source (title + first words of a part), never paraphrased. Dates come
only from the manifest's recorded upstream fields; a stratum that needs a date the source does
not carry is skipped and counted, never filled. Output: tasks.jsonl, corpus.jsonl (the rows the
tasks' evidence ids refer to, in run_baselines.Corpus format) and tasks_manifest.json.
Exit 1 when a floor is not met (the shortfall is reported, never padded).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from benchmark.retrieval_baselines.run_baselines import Corpus as HarnessCorpus
from benchmark.revision_pairs.to_product_core import (
    DEFAULT_MANIFEST,
    CorpusError,
    FamilyDocs,
    docs_from_catalog,
    docs_from_ecfr_xml,
    read_verified,
    sha256_hex,
)

GENERATOR = "benchmark.retrieval_baselines.build_tasks/1"
FLOORS = {"retrieval": 200, "temporal": 200, "acl_base": 50, "acl_variant": 1000}
ACL_VARIANTS = (
    "{t}",  # base template: the bare term
    "what does the policy say about {t}",
    "{t} requirements",
    "find documents mentioning {t}",
    "{t} definition",
    "summarize {t}",
    "who is responsible for {t}",
    "{t} and related controls",
    "latest guidance on {t}",
    "list every reference to {t}",
    "explain {t} in detail",
)
_TOKEN = re.compile(r"[a-z][a-z0-9-]{3,}")
Key = tuple[str, str]  # (source, family)


def _moment(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _order(seed: int, *parts: object) -> str:
    return hashlib.sha256(f"{seed}:{':'.join(map(str, parts))}".encode()).hexdigest()


def _iso(m: datetime) -> str:
    return m.isoformat()


def _phrase(text: str) -> str:
    return " ".join(text.split()[:6])


def _load(manifest: dict[str, Any], cache: Path) -> dict[tuple[str, str], dict[str, FamilyDocs]]:
    """(source, snapshot key) -> family -> docs; every upstream byte is hash-verified."""
    out: dict[tuple[str, str], dict[str, FamilyDocs]] = {}
    for pair in manifest["pairs"]:
        for side in ("before", "after"):
            source, key = pair["source"], pair[side]["snapshot"]
            if (source, key) in out:
                continue
            if source == "nist-oscal":
                snap = next(s for s in manifest["snapshots"] if s["commit_sha"] == key)
                raw = read_verified(cache / key / "catalog.json", snap["sha256"])
                out[source, key] = docs_from_catalog(json.loads(raw))
            else:
                snap = next(s for s in manifest["ecfr_snapshots"] if s["date"] == key)
                raw = read_verified(cache / "ecfr" / f"{key}.xml", snap["sha256"])
                out[source, key] = docs_from_ecfr_xml(raw, key)
    for pair in manifest["pairs"]:
        for side in ("before", "after"):
            docs = out[pair["source"], pair[side]["snapshot"]][pair["family"]][0]
            if {k: d.content_sha256 for k, d in docs.items()} != pair[side]["docs"]:
                raise CorpusError(f"{pair['pair_id']} {side}: document hashes differ from manifest")
    return out


def _snapshot_meta(manifest: dict[str, Any], source: str, key: str) -> dict[str, Any]:
    """label, moment, available_at - only fields the upstream recorded."""
    if source == "nist-oscal":
        s = next(s for s in manifest["snapshots"] if s["commit_sha"] == key)
        return {
            "label": s["version"],
            "moment": _moment(s["last_modified"]),
            "available_at": s["published"],
        }
    s = next(s for s in manifest["ecfr_snapshots"] if s["date"] == key)
    return {
        "label": key,
        "moment": _moment(f"{key}T00:00:00+00:00"),  # date-only upstream value, UTC midnight
        "available_at": s.get("available_at"),
    }


class Corpus:
    """Versioned rows per tenant: a row is one part text, valid from the snapshot that
    introduced it until the first later snapshot that changed or dropped it."""

    def __init__(self, manifest: dict[str, Any], cache: Path) -> None:
        loaded = _load(manifest, cache)
        chains: dict[Key, set[str]] = defaultdict(set)
        for p in manifest["pairs"]:
            chains[p["source"], p["family"]] |= {p["before"]["snapshot"], p["after"]["snapshot"]}
        self.meta = {k: _snapshot_meta(manifest, *k) for k in loaded}
        self.skipped_snapshots = Counter[str]()
        self.docs = loaded
        self.chain: dict[Key, list[str]] = {}
        for fam, keys in sorted(chains.items()):
            usable = [k for k in keys if self.meta[fam[0], k]["moment"] is not None]
            self.skipped_snapshots["no upstream date"] += len(keys) - len(usable)
            usable.sort(key=lambda k: self.meta[fam[0], k]["moment"])
            moments = [self.meta[fam[0], k]["moment"] for k in usable]
            if len(set(moments)) != len(moments):
                raise CorpusError(f"{fam}: two snapshots share one upstream date")
            self.chain[fam] = usable
        self.tenant = {fam: f"tenant-{'ab'[i % 2]}" for i, fam in enumerate(self.chain)}
        self.rows: list[dict[str, Any]] = []
        self.by_control: dict[tuple[Key, str], list[dict[str, Any]]] = defaultdict(list)
        for fam in self.chain:
            self._family_rows(fam)
        self.rows.sort(key=lambda r: r["logical_id"])
        # Gold may only name evidence the harness can retrieve: parts that compile to no claim
        # (e.g. a withdrawn stub that is not a sentence) cannot be found by any retriever.
        compiled = HarnessCorpus(self.rows)
        self.known = {e for ids in compiled.evidence_of.values() for e in ids}

    def _family_rows(self, fam: Key) -> None:
        source, family = fam
        open_rows: dict[tuple[str, str], dict[str, Any]] = {}
        for key in self.chain[fam]:
            info = self.meta[source, key]
            moment = info["moment"].isoformat()
            current: dict[tuple[str, str], tuple[str, str]] = {}
            for cid, doc in self.docs[source, key][family][0].items():
                for r in doc.regions:
                    current[cid, r.native_object_id or r.region_id] = (r.text, doc.title)
            for k in [
                k
                for k, row in open_rows.items()
                if k not in current or row["text"] != current[k][0]
            ]:
                open_rows.pop(k)["metadata"]["valid_to"] = moment
            for k, (text, title) in sorted(current.items()):
                if k in open_rows:
                    continue
                cid, pid = k
                lid = f"{self.tenant[fam]}/{family}/{cid}/{pid}@{info['label']}"
                row = {
                    "tenant": self.tenant[fam],
                    "logical_id": lid,
                    "source_id": f"{source}-{cid}",
                    "source_version_id": re.sub(r"[^A-Za-z0-9._:-]", "-", info["label"]),
                    "evidence_id": f"ev:{lid}",
                    "text": text,
                    "authority": "official",
                    "metadata": {
                        "valid_from": moment,
                        "valid_to": None,
                        "recorded_at": moment,
                        "available_at": info["available_at"],
                    },
                    "_title": title,
                }
                open_rows[k] = row
                self.rows.append(row)
                self.by_control[fam, cid].append(row)

    def evidence_at(self, fam: Key, cid: str, at: datetime) -> list[str]:
        out = []
        for r in self.by_control[fam, cid]:
            m = r["metadata"]
            if (
                r["evidence_id"] in self.known
                and datetime.fromisoformat(m["valid_from"]) <= at
                and (m["valid_to"] is None or datetime.fromisoformat(m["valid_to"]) > at)
            ):
                out.append(r["evidence_id"])
        return sorted(out)


def _query(doc: Any, pick: Any = None) -> str:
    regions = doc.regions
    region = next((r for r in regions if len(r.text.split()) >= 6), regions[0])
    return f"{doc.title} {_phrase((pick or region).text)}"


def _tokens(rows: list[dict[str, Any]]) -> set[str]:
    return {t for r in rows for t in _TOKEN.findall(f"{r['_title']} {r['text']}".lower())}


def build(
    manifest: dict[str, Any], cache: Path, seed: int, per_stratum: int = 60
) -> dict[str, Any]:
    corpus = Corpus(manifest, cache)
    tasks: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    seen: set[tuple[Any, ...]] = set()

    def add(
        kind: str,
        stratum: str,
        fam: Key,
        cid: str,
        query: str,
        cut: dict[str, str] | None,
        gold: list[str],
    ) -> None:
        tid = f"{stratum}-{hashlib.sha256(f'{fam}{cid}{query}{cut}'.encode()).hexdigest()[:12]}"
        if tid in {t["task_id"] for t in tasks}:  # same control + cut reached from two pairs
            return
        tasks.append(
            {
                "task_id": tid, "kind": kind, "stratum": stratum, "tenant": corpus.tenant[fam],
                "family": fam[1], "control_id": cid, "query": query, "cut": cut,
                "gold_evidence_ids": gold, "answerable": bool(gold), "provenance": "generated",
                "generator": GENERATOR, "seed": seed,
            }
        )  # fmt: skip

    # --- temporal candidates, per pair ---------------------------------------------
    cands: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    for pair in manifest["pairs"]:
        fam: Key = (pair["source"], pair["family"])
        ka, kb = pair["before"]["snapshot"], pair["after"]["snapshot"]
        ma, mb = corpus.meta[fam[0], ka], corpus.meta[fam[0], kb]
        ta, tb = ma["moment"], mb["moment"]
        if ta is None or tb is None or ta >= tb:
            skipped["pair without strictly ordered upstream dates"] += 1
            continue
        da, wa = corpus.docs[fam[0], ka][fam[1]]
        db, wb = corpus.docs[fam[0], kb][fam[1]]
        both = sorted(set(da) & set(db))
        withdrawn = [c for c in both if c in wb and c not in wa]
        modified = [
            c for c in both if c not in withdrawn and da[c].content_sha256 != db[c].content_sha256
        ]
        for c in sorted(set(db) - set(da)):
            cands["added_later"].append((fam, c, db[c], ta))
        for c in withdrawn:
            cands["withdrawn"].append((fam, c, da[c], tb))
        for c in modified:
            cands["modified"].append((fam, c, da[c], ta, tb))
            changed = [r for r in db[c].regions if r.text not in {x.text for x in da[c].regions}]
            cands["late_recorded"].append((fam, c, db[c], ta, changed[0] if changed else None))
        if mb["available_at"] is None:
            for c in sorted(db):
                cands["unknown_availability"].append((fam, c, db[c], tb))
        skipped["backdated: source carries no recorded_at later than valid_from"] += 1

    def pick(stratum: str) -> list[tuple[Any, ...]]:
        rows = sorted(cands[stratum], key=lambda c: _order(seed, stratum, c[0], c[1], c[3]))
        return rows[: per_stratum * 3]  # over-draw: dedupe/skips below shrink it

    quota: Counter[str] = Counter()

    def take(stratum: str, key: tuple[Any, ...]) -> bool:
        if key in seen or quota[stratum] >= per_stratum:
            return False
        seen.add(key)
        quota[stratum] += 1
        return True

    for fam, c, doc, ta in pick("added_later"):
        if take("added_later", ("al", fam, c, ta)):
            cut = {"valid_at": _iso(ta), "known_at": _iso(ta)}
            add("temporal", "added_later", fam, c, _query(doc), cut, [])
    for fam, c, doc, tb in pick("withdrawn"):
        gold = corpus.evidence_at(fam, c, tb)
        if not gold:
            skipped["withdrawn: no stub row at the cut"] += 1
        elif take("withdrawn", ("wd", fam, c, tb)):
            add("temporal", "withdrawn", fam, c, _query(doc), {"valid_at": _iso(tb)}, gold)
    for fam, c, doc, ta, tb in pick("modified"):
        golds = [corpus.evidence_at(fam, c, t) for t in (ta, tb)]
        if not all(golds) or golds[0] == golds[1]:
            skipped["modified: gold missing or identical at both releases"] += 1
        elif take("modified", ("md", fam, c, ta, tb)):
            for t, g in zip((ta, tb), golds, strict=True):
                add("temporal", "modified", fam, c, _query(doc), {"valid_at": _iso(t)}, g)
    for fam, c, doc, ta, changed in pick("late_recorded"):
        gold = corpus.evidence_at(fam, c, ta)
        if not gold:
            skipped["late_recorded: control absent at the cut"] += 1
        elif take("late_recorded", ("lr", fam, c, ta)):
            add(
                "temporal",
                "late_recorded",
                fam,
                c,
                _query(doc, changed),
                {"known_at": _iso(ta)},
                gold,
            )
    for fam, c, doc, tb in pick("unknown_availability"):
        if any(r["metadata"]["available_at"] for r in corpus.by_control[fam, c]):
            skipped["unknown_availability: control has a stated availability date"] += 1
        elif take("unknown_availability", ("ua", fam, c, tb)):
            add(
                "temporal",
                "unknown_availability",
                fam,
                c,
                _query(doc),
                {"available_at": _iso(tb)},
                [],
            )

    # --- retrieval: latest release of each control ----------------------------------
    latest: list[tuple[Key, str, Any, datetime]] = []
    for fam, chain in corpus.chain.items():
        last = chain[-1]
        for c, doc in corpus.docs[fam[0], last][fam[1]][0].items():
            latest.append((fam, c, doc, corpus.meta[fam[0], last]["moment"]))
    latest.sort(key=lambda x: _order(seed, "retrieval", x[0], x[1]))
    n_retrieval = 0
    for fam, c, doc, t in latest:
        if n_retrieval == FLOORS["retrieval"]:
            break
        if gold := corpus.evidence_at(fam, c, t):
            add("retrieval", "retrieval", fam, c, _query(doc), None, gold)
            n_retrieval += 1
        else:
            skipped["retrieval: no compilable gold part"] += 1

    # --- ACL negatives: another tenant's unique terms -------------------------------
    by_tenant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in corpus.rows:
        by_tenant[r["tenant"]].append(r)
    vocab = {t: _tokens(rows) for t, rows in by_tenant.items()}
    pool = sorted(
        (asker, term)
        for asker in vocab
        for other in vocab
        if other != asker
        for term in vocab[other] - vocab[asker]
    )
    combos = sorted(
        ((a, t, i) for a, t in pool for i in range(len(ACL_VARIANTS))),
        key=lambda x: _order(seed, "acl", *x),
    )
    base = [x for x in combos if x[2] == 0][: FLOORS["acl_base"]]
    variants = [x for x in combos if x[2] != 0][: FLOORS["acl_variant"]]
    for stratum, group in (("acl_base", base), ("acl_variant", variants)):
        for asker, term, i in group:
            tid = f"{stratum}-{hashlib.sha256(f'{asker}{term}{i}'.encode()).hexdigest()[:12]}"
            tasks.append(
                {
                    "task_id": tid, "kind": "acl_negative", "stratum": stratum, "tenant": asker,
                    "query": ACL_VARIANTS[i].format(t=term), "cut": None, "gold_evidence_ids": [],
                    "answerable": False, "provenance": "generated", "generator": GENERATOR,
                    "seed": seed,
                }
            )  # fmt: skip

    tasks.sort(key=lambda t: t["task_id"])
    ids = [t["task_id"] for t in tasks]
    if len(set(ids)) != len(ids):
        raise CorpusError("duplicate task ids")
    skipped["corpus parts that compile to no claim (never used as gold)"] = len(corpus.rows) - len(
        corpus.known
    )
    rows = [{k: v for k, v in r.items() if k != "_title"} for r in corpus.rows]
    return {
        "tasks": tasks,
        "corpus": rows,
        "skipped": dict(skipped),
        "snapshot_skips": dict(corpus.skipped_snapshots),
    }


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()


def write(result: dict[str, Any], out: Path, manifest_path: Path, seed: int) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    tasks_raw, corpus_raw = _jsonl(result["tasks"]), _jsonl(result["corpus"])
    (out / "tasks.jsonl").write_bytes(tasks_raw)
    (out / "corpus.jsonl").write_bytes(corpus_raw)
    strata = Counter(t["stratum"] for t in result["tasks"])
    kinds = Counter(t["kind"] for t in result["tasks"])
    shortfall = {
        name: floor - (kinds[name] if name in kinds else strata[name])
        for name, floor in FLOORS.items()
        if (kinds[name] if name in kinds else strata[name]) < floor
    }
    summary = {
        "schema": "tavonel.retrieval_tasks.manifest.v1",
        "provenance": "generated",
        "generator": GENERATOR,
        "seed": seed,
        "note": "generated tasks, not blind gold; ACL base tasks are not hand-checked yet",
        "corpus_manifest_sha256": sha256_hex(manifest_path.read_bytes()),
        "tasks_sha256": sha256_hex(tasks_raw),
        "corpus_sha256": sha256_hex(corpus_raw),
        "counts_by_kind": dict(sorted(kinds.items())),
        "counts_by_stratum": dict(sorted(strata.items())),
        "floors": FLOORS,
        "shortfall": shortfall,
        "skipped": result["skipped"],
        "snapshot_skips": result["snapshot_skips"],
    }
    (out / "tasks_manifest.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=20261116)
    ap.add_argument("--per-stratum", type=int, default=60)
    args = ap.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    summary = write(
        build(manifest, args.cache_dir, args.seed, args.per_stratum),
        args.out,
        args.manifest,
        args.seed,
    )
    print(json.dumps({k: summary[k] for k in ("counts_by_kind", "counts_by_stratum", "shortfall")}))
    return 1 if summary["shortfall"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
