"""The tokenization contract, pinned and probed. Frozen before any model call.

`INC-V2-017` recorded a mismatch that did not cause its failure and was not
allowed to hide behind that: the `tokenizer.json` digest was byte-identical to
the W6 attestation and the single 20-token probe matched, yet the library
reported `Qwen2TokenizerFast` / vocab 248044 against the attestation's
`Qwen2Tokenizer` / 248320.

A digest proves which bytes were loaded. It does not prove that two libraries
loading those bytes segment text the same way. That is what this battery is
for, and it is why one probe was never enough: a single ASCII-ish string
exercises none of the places tokenizers actually diverge.

Four probe classes, each chosen because it is a known divergence point:

* **unicode** — accents, CJK, NBSP and combining marks, where normalization
  differences between a fast and a slow implementation surface first;
* **number and version** — thousands separators, decimals and dotted chains,
  which is exactly what this study's endpoint is made of. A tokenizer that
  splits `42.50` differently changes what the model sees of the answer;
* **special tokens** — the chat template's turn markers, which must round-trip
  or the prompt the CPU measured is not the prompt the GPU receives;
* **long-context boundary** — a sequence at and just over the 4,096 budget,
  where an off-by-a-few disagreement decides whether the target evidence was
  truncated away.

The same frozen battery runs on the CPU materializer and on the GPU runtime.
Identical results are the evidence that both used one contract; any divergence
stops the run.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

#: Probe texts, frozen. Deterministic and content-independent of any cohort.
PROBES: tuple[dict[str, str], ...] = (
    {
        "name": "attested_probe",
        "class": "regression",
        "text": "TAVONEL 1,450 — café ü 42.50 USD",
        "guards": "the exact string the W6 attestation recorded; it must not drift",
    },
    {
        "name": "unicode_accents_and_cjk",
        "class": "unicode",
        "text": "café ü ß Ω 東京 서울 — naïve résumé",
        "guards": "NFKC handling and multi-byte segmentation",
    },
    {
        "name": "unicode_nbsp_and_combining",
        "class": "unicode",
        "text": "1 450 étude ​zero-width",
        "guards": "non-breaking space, combining acute and zero-width joiner",
    },
    {
        "name": "numbers_thousands_and_decimals",
        "class": "number_and_version",
        "text": "1,450 and 1450 and 42.50 and 42.05 and 0.0001",
        "guards": "the shapes the endpoint's value markers are made of",
    },
    {
        "name": "versions_and_dates",
        "class": "number_and_version",
        "text": "v2.15.0 2.14.1 2026-04-01 15d 5m 99.98%",
        "guards": "dotted chains, ISO dates and unit-suffixed quantities",
    },
    {
        "name": "identifiers_and_flags",
        "class": "number_and_version",
        "text": "--query.lookback-delta CIK0000320193 §  50.2 (3)#1",
        "guards": "flag and identifier shapes that carry property labels",
    },
    {
        "name": "markup_residue",
        "class": "unicode",
        "text": "| Flag | Default |\n| --- | --- |\n| --retention | 15 |",
        "guards": "pipe tables reach the prompt as text and must segment stably",
    },
)

#: Applied through the chat template, so the turn markers are exercised too.
SPECIAL_TOKEN_PROBE = {
    "name": "chat_template_round_trip",
    "class": "special_tokens",
    "system": "You answer only from the numbered sources provided.",
    "user": "Question: what value do the sources state for: Default of --retention",
    "guards": "the template's turn markers must survive encode and decode",
}

#: At and just over the context budget. The boundary decides truncation.
BOUNDARY_PROBE = {
    "name": "long_context_boundary",
    "class": "long_context_boundary",
    "unit": "source line 42 holds the value 15 for the retention setting. ",
    "targets": (4090, 4096, 4102),
    "guards": "an off-by-a-few disagreement here silently changes what was truncated",
}

PROBE_CLASSES = ("regression", "unicode", "number_and_version", "special_tokens", "long_context_boundary")


def battery_digest() -> str:
    """The battery is frozen; this is how a later run proves it ran the same one."""
    blob = json.dumps(
        {
            "probes": list(PROBES),
            "special": SPECIAL_TOKEN_PROBE,
            "boundary": {**BOUNDARY_PROBE, "targets": list(BOUNDARY_PROBE["targets"])},
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def run_battery(
    encode: Callable[[str], list[int]],
    encode_chat: Callable[[str, str], list[int]],
) -> dict[str, Any]:
    """Token ids, not just counts.

    Counts are a weaker claim than they look: two segmentations can agree on how
    many pieces there are and disagree on where the boundaries fall. The
    recorded evidence is the id sequence digest, and the count beside it is for
    reading, not for comparing.
    """
    results: list[dict[str, Any]] = []
    for probe in PROBES:
        ids = encode(probe["text"])
        results.append(
            {
                "name": probe["name"],
                "class": probe["class"],
                "guards": probe["guards"],
                "token_count": len(ids),
                "ids_sha256": "sha256:"
                + hashlib.sha256(json.dumps(ids).encode("utf-8")).hexdigest(),
            }
        )

    ids = encode_chat(SPECIAL_TOKEN_PROBE["system"], SPECIAL_TOKEN_PROBE["user"])
    results.append(
        {
            "name": SPECIAL_TOKEN_PROBE["name"],
            "class": SPECIAL_TOKEN_PROBE["class"],
            "guards": SPECIAL_TOKEN_PROBE["guards"],
            "token_count": len(ids),
            "ids_sha256": "sha256:" + hashlib.sha256(json.dumps(ids).encode("utf-8")).hexdigest(),
        }
    )

    unit = BOUNDARY_PROBE["unit"]
    for target in BOUNDARY_PROBE["targets"]:
        # grown one unit at a time to the largest sequence that still fits, then
        # one unit past it. A fixed repeat count would let two targets collapse
        # onto the same text and probe nothing at the boundary that matters.
        text = ""
        repeats = 0
        while True:
            candidate = text + unit
            if len(encode(candidate)) > target:
                break
            text, repeats = candidate, repeats + 1
        for side, body in (("under", text), ("over", text + unit)):
            ids = encode(body)
            results.append(
                {
                    "name": "%s_%d_%s" % (BOUNDARY_PROBE["name"], target, side),
                    "class": BOUNDARY_PROBE["class"],
                    "guards": BOUNDARY_PROBE["guards"],
                    "target": target,
                    "repeats": repeats + (1 if side == "over" else 0),
                    "token_count": len(ids),
                    "straddles": len(ids) <= target if side == "under" else len(ids) > target,
                    "ids_sha256": "sha256:"
                    + hashlib.sha256(json.dumps(ids).encode("utf-8")).hexdigest(),
                }
            )

    by_class = {name: [r for r in results if r["class"] == name] for name in PROBE_CLASSES}
    return {
        "battery_digest": battery_digest(),
        "results": results,
        "classes_covered": sorted(name for name, rows in by_class.items() if rows),
        "all_classes_covered": all(by_class[name] for name in PROBE_CLASSES),
        "boundary_straddled": all(
            row.get("straddles", True)
            for row in results
            if row["class"] == "long_context_boundary"
        ),
        "signature": "sha256:"
        + hashlib.sha256(
            json.dumps(
                [[r["name"], r["ids_sha256"]] for r in results], sort_keys=True
            ).encode("utf-8")
        ).hexdigest(),
    }


def compare(cpu: dict[str, Any], gpu: dict[str, Any]) -> dict[str, Any]:
    """Parity is identity of the id sequences, probe by probe."""
    cpu_by_name = {row["name"]: row for row in cpu["results"]}
    gpu_by_name = {row["name"]: row for row in gpu["results"]}
    names = sorted(set(cpu_by_name) | set(gpu_by_name))
    divergent = [
        name
        for name in names
        if name not in cpu_by_name
        or name not in gpu_by_name
        or cpu_by_name[name]["ids_sha256"] != gpu_by_name[name]["ids_sha256"]
    ]
    return {
        "same_battery": cpu.get("battery_digest") == gpu.get("battery_digest"),
        "signatures_match": cpu.get("signature") == gpu.get("signature"),
        "divergent_probes": divergent,
        "parity": not divergent and cpu.get("battery_digest") == gpu.get("battery_digest"),
    }


def pinned_environment(tokenizer: Any) -> dict[str, Any]:
    """Every field INC-V2-017 asked to be pinned, recorded whether or not it agrees."""
    import tokenizers  # noqa: PLC0415
    import transformers  # noqa: PLC0415

    return {
        "transformers_version": transformers.__version__,
        "tokenizers_version": tokenizers.__version__,
        "tokenizer_class": type(tokenizer).__name__,
        "is_fast": bool(getattr(tokenizer, "is_fast", False)),
        "vocab_size_reported": getattr(tokenizer, "vocab_size", None),
        "len_tokenizer": len(tokenizer),
        "added_tokens": len(getattr(tokenizer, "get_added_vocab", dict)() or {}),
        "special_tokens_map": getattr(tokenizer, "special_tokens_map", {}),
        "special_tokens_map_sha256": "sha256:"
        + hashlib.sha256(
            json.dumps(getattr(tokenizer, "special_tokens_map", {}), sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "chat_template_sha256": "sha256:"
        + hashlib.sha256((getattr(tokenizer, "chat_template", "") or "").encode("utf-8")).hexdigest(),
    }
