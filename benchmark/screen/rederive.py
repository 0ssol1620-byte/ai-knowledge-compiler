"""Re-derive one candidate's S0 records with normaliser v2, offline (WO-D10-0V).

``python -m benchmark.screen.rederive --s0 DIR --provider KEY --manifest M --corpus-root C
--gold G --out OUT``. S0 ran on v1 and its records stay as they are; S1 reads these instead.

Every final record of ``DIR`` is checked before anything is written: its pins are the run's
(``s0-run.json``, which must name normaliser v1), and its stored raw file has the record's
``raw_sha256`` (a mismatch or a missing file is exit 4, nothing written). A page whose answer
went through the normaliser (the driver's own test: an object with a str ``text``, a dict
``metrics`` and no ``failure`` object) must carry v1's ``metrics.normaliser`` block, and v1 run
on its ``text_before`` must give the stored text and residual again (else exit 4). That text is
normalised with v2 and the record is produced by ``run_screen`` itself, its call replaying the
stored answer with the new text, so validation and scoring are the driver's, reader v1
untouched. ``metrics.normaliser`` then names v2's digest, with ``residual_v1`` beside the v2
``residual``. Any other record (no output, or an answer that was never normalised) is passed
through unchanged and its raw file copied. Only ``raw_sha256``, ``metrics``, ``critical``,
``hard_failures`` and ``accepted`` may differ from the stored record; anything else that differs
is exit 4. ``latency_ms`` is the stored record's: S0 measured it; a replay measures nothing.

``OUT`` must not exist or be empty (exit 2 otherwise): the run is staged beside it and renamed
into place only when complete, so a refused run writes nothing. It holds ``raw/``,
``final-records.jsonl``, ``rederive-summary.json`` (counts and markup names only) and
``rederive-receipt.json`` (its inputs, and input record digest -> output record digest per
record). Nothing printed or summarised carries page text, a gold value or a field value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, TypeGuard

from benchmark.runners.base import RunnerUnavailable
from benchmark.screen import critical_fields
from benchmark.screen import normalise_v1 as v1
from benchmark.screen import normalise_v2 as v2
from benchmark.screen.manifest import HoldoutGuard, verify
from benchmark.screen.run_screen import Candidate, run_screen
from benchmark.screen.s0 import (
    EXIT_CRASH,
    EXIT_INTEGRITY,
    EXIT_OK,
    EXIT_REFUSED,
    MAX_TEXT_CHARS,
    Driver,
    Exit,
)
from benchmark.screen.select_5h import READER_V1_SHA256
from benchmark.v6.contracts import ContractError, canonical_sha256

MODULE_SHA256 = "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
PINS = ("candidate_id", "revision", "image_digest", "config_sha256")  # record key order
SCORED = frozenset({"raw_sha256", "metrics", "critical", "hard_failures", "accepted"})
_KEY = re.compile(r"sha256:[0-9a-f]{64}")
_NAME = re.compile(r"<\s*/?\s*([A-Za-z0-9_]+)|\\([A-Za-z]+)")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m benchmark.screen.rederive")
    p.add_argument("--provider", required=True)
    for name in ("s0", "manifest", "corpus-root", "gold", "out"):
        p.add_argument(f"--{name}", required=True, type=Path)
    return p.parse_args(argv)


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _line(record: dict[str, Any]) -> str:
    """A record as the S0 driver writes it into final-records.jsonl."""
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


def kinds(text: str) -> Counter[str]:
    """The markup left in ``text`` by tag or command name only (the residual's tokens)."""
    out: Counter[str] = Counter()
    for tok in v1._RESIDUAL.findall(text):
        m = _NAME.match(tok)
        if m is None:
            out["other"] += 1
        else:
            out[f"<{m[1].lower()}>" if m[1] else "\\" + m[2]] += 1
    return out


def _normalised(raw: Any) -> TypeGuard[dict[str, Any]]:
    """The S0 driver normalised this answer: the same test as ``Driver._page``/``_finish``."""
    return (
        isinstance(raw, dict)
        and not isinstance(raw.get("failure"), dict)
        and isinstance(raw.get("text"), str)
        and isinstance(raw.get("metrics"), dict)
    )


def _load(
    s0_dir: Path, provider: str
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, bytes | None], str]:
    """(pins, final records, record_key -> stored raw bytes or None, final records digest);
    every check before any write."""
    try:
        pins = json.loads((s0_dir / "s0-run.json").read_text(encoding="utf-8"))
        body = (s0_dir / "final-records.jsonl").read_bytes()
        records = [json.loads(x) for x in body.decode("utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        raise Exit(
            EXIT_REFUSED, "the S0 directory has no readable s0-run.json and final records"
        ) from None
    if not isinstance(pins, dict) or pins.get("provider") != provider:
        raise Exit(EXIT_REFUSED, "--provider is not the provider the S0 run pinned")
    if pins.get("normaliser_sha256") != v1.MODULE_SHA256:
        raise Exit(EXIT_INTEGRITY, "the S0 run does not pin normaliser v1")
    if not records:
        raise Exit(EXIT_REFUSED, "the S0 run has no final records")
    stored: dict[str, bytes | None] = {}
    for r in records:
        if not isinstance(r, dict) or any(r.get(k) != pins.get(k) for k in PINS):
            raise Exit(EXIT_INTEGRITY, "a final record does not carry the run's pins")
        key = r.get("record_key")
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise Exit(EXIT_INTEGRITY, "a final record has no record key")
        if key in stored:
            raise Exit(EXIT_INTEGRITY, "two final records share a record key")
        stored[key] = None
        if r.get("raw_sha256") is None:
            continue
        try:
            data = (s0_dir / "raw" / (key.removeprefix("sha256:") + ".json")).read_bytes()
        except OSError:
            raise Exit(EXIT_INTEGRITY, "a stored raw output is missing") from None
        if _sha(data) != r["raw_sha256"]:
            raise Exit(EXIT_INTEGRITY, "a stored raw output differs from its record")
        stored[key] = data
    return pins, records, stored, _sha(body)


def _replay(provider: str, raw: dict[str, Any]) -> dict[str, Any]:
    """The stored answer with v2's text: v1's block is checked against v1 first."""
    norm = raw["metrics"].get("normaliser")
    if not (
        isinstance(norm, dict)
        and norm.get("module_sha256") == v1.MODULE_SHA256
        and norm.get("profile") == v2.profile_of(provider)
        and isinstance(norm.get("text_before"), str)
        and len(norm["text_before"]) <= MAX_TEXT_CHARS  # the driver normalised no longer text
        and type(norm.get("residual")) is int
    ):
        raise Exit(EXIT_INTEGRITY, "a normalised answer does not carry v1's normaliser block")
    before = norm["text_before"]
    if v1.normalise(provider, before) != (raw["text"], norm["residual"]):
        raise Exit(EXIT_INTEGRITY, "v1 on the stored text_before does not give the stored text")
    text, residual = v2.normalise(provider, before)
    block = {
        "profile": v2.profile_of(provider),
        "module_sha256": v2.MODULE_SHA256,
        "text_before": before,
        "residual": residual,
        "residual_v1": norm["residual"],
    }
    return {**raw, "text": text, "metrics": {**raw["metrics"], "normaliser": block}}


def rederive(args: argparse.Namespace) -> dict[str, Any]:
    provider, out = str(args.provider), Path(args.out)
    try:
        v2.profile_of(provider)
    except ValueError:
        raise Exit(EXIT_REFUSED, "no normaliser profile for this provider") from None
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Exit(EXIT_REFUSED, "--out is not empty; re-derived records are written once")
    if _sha(Path(critical_fields.__file__).read_bytes()) != READER_V1_SHA256:
        raise Exit(EXIT_REFUSED, "critical_fields.py is not reader v1")
    pins, records, stored, records_sha = _load(Path(args.s0), provider)
    by_key = {r["record_key"]: r for r in records}
    replays: dict[str, dict[str, Any]] = {}  # record_key -> the answer to replay
    for key, data in stored.items():
        raw = None if data is None else json.loads(data)
        if _normalised(raw):
            replays[key] = _replay(provider, raw)
    passed = set(stored) - set(replays)  # record keys passed through unchanged
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        verify(manifest, Path(args.corpus_root))
    except Exception as exc:  # the message may name a document: the type only
        raise Exit(EXIT_REFUSED, f"manifest verify failed ({type(exc).__name__})") from None
    gold = Driver._gold(Path(args.gold))
    inputs = {
        "s0_run_pins": pins,
        "s0_final_records_sha256": records_sha,
        "manifest_sha256": manifest["manifest_sha256"],
        "gold_file_sha256": _sha(Path(args.gold).read_bytes()),
    }
    candidate = Candidate(
        candidate_id=pins["candidate_id"],
        provider=provider,
        revision=pins["revision"],
        image_digest=pins["image_digest"],
        config_sha256=pins["config_sha256"],
    )

    def call(c: Candidate, case: dict[str, Any], _: Path) -> dict[str, Any]:
        page_id = f"{case['source']['path']}#{case['page_index']}"
        answer = replays.get(canonical_sha256([page_id, *(getattr(c, k) for k in PINS)]))
        if answer is None:  # a page stored without output: its stored record is passed through
            raise RunnerUnavailable("no stored answer to replay")
        return answer

    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=out.name + ".partial-", dir=out.parent))
    try:
        (stage / "raw").mkdir()
        for key in passed:
            data = stored[key]
            if data is not None:
                (stage / "raw" / (key.removeprefix("sha256:") + ".json")).write_bytes(data)
        with tempfile.TemporaryDirectory() as ledger:
            try:
                fresh = run_screen(
                    guard=HoldoutGuard(manifest, stage / "holdout-access.jsonl"),
                    split="dev",
                    purpose="tune",
                    candidate=candidate,
                    corpus_root=Path(args.corpus_root),
                    gold=gold,
                    raw_dir=stage / "raw",
                    records_path=Path(ledger) / "records.jsonl",
                    call=call,
                )
            except ContractError as exc:  # the message may name a document: the type only
                raise Exit(EXIT_REFUSED, f"run_screen refused ({type(exc).__name__})") from None
        if sorted(r["record_key"] for r in fresh) != sorted(by_key):
            raise Exit(EXIT_INTEGRITY, "the final records are not one per page of the split")
        result = _finish(provider, fresh, by_key, stored, passed, stage, inputs)
        if out.exists():
            out.rmdir()  # empty, checked above
        stage.rename(out)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return result


def _finish(
    provider: str,
    fresh: list[dict[str, Any]],
    by_key: dict[str, dict[str, Any]],
    stored: dict[str, bytes | None],
    passed: set[str],
    stage: Path,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    final: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    left: Counter[str] = Counter()
    res_v1 = res_v2 = changed = 0
    for r in fresh:
        key = r["record_key"]
        old = by_key[key]
        if key in passed:
            r = old
        else:
            raw = json.loads(stored[key] or b"")
            # the S0 measurement: a replay measures nothing (run_screen takes its own clock
            # where the answer carries no latency or is a contract failure)
            r = {**r, "latency_ms": old["latency_ms"]}
            differ = {k for k in (set(r) | set(old)) - SCORED if r.get(k) != old.get(k)}
            if differ:  # run_screen's field names only, never a value
                named = sorted({k if k in r else "other" for k in differ})
                raise Exit(EXIT_INTEGRITY, f"a re-derived record differs in {named}")
            new = json.loads((stage / "raw" / (key.removeprefix("sha256:") + ".json")).read_bytes())
            norm = new["metrics"]["normaliser"]
            res_v1 += norm["residual_v1"]
            res_v2 += norm["residual"]
            changed += new["text"] != raw["text"]
            left.update(kinds(new["text"]))
        final.append(r)
        bindings.append(
            {
                "record_key": key,
                "input_record_sha256": _sha(_line(old).encode()),
                "output_record_sha256": _sha(_line(r).encode()),
                "passed_through": key in passed,
            }
        )
    body = "".join(_line(r) + "\n" for r in final).encode("utf-8")
    (stage / "final-records.jsonl").write_bytes(body)
    summary = {
        "provider": provider,
        "profile": v2.profile_of(provider),
        "pages": len(final),
        "pages_rederived": len(final) - len(passed),
        "pages_passed_through": len(passed),
        "pages_text_changed": changed,
        "residual": {"v1_sum": res_v1, "v2_sum": res_v2},
        "kinds_left": dict(sorted(left.items())),
    }
    receipt = {
        "inputs": inputs,
        "normaliser_v1_sha256": v1.MODULE_SHA256,
        "normaliser_v2_sha256": v2.MODULE_SHA256,
        "reader_sha256": READER_V1_SHA256,
        "rederive_sha256": MODULE_SHA256,
        "final_records_sha256": _sha(body),
        "records": bindings,
    }
    for name, doc in (("rederive-summary.json", summary), ("rederive-receipt.json", receipt)):
        (stage / name).write_bytes((json.dumps(doc, indent=2, sort_keys=True) + "\n").encode())
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        s = rederive(args)
    except Exit as stop:
        print(f"rederive exit {stop.code}: {stop}", flush=True)
        return stop.code
    except Exception as exc:  # the message may quote a document: the type only
        print(f"rederive exit {EXIT_CRASH}: crash {type(exc).__name__}", flush=True)
        return EXIT_CRASH
    print(
        f"rederive done pages={s['pages']} rederived={s['pages_rederived']} "
        f"residual {s['residual']['v1_sum']} -> {s['residual']['v2_sum']}",
        flush=True,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
