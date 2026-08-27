"""Offline tests for the exact-token GPU successor V2 materializer."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for sub in ("tools", "endpoint", "source_fact_ir"):
    sys.path.insert(0, str(NS / sub))

import gpu_successor_v2_prompt_schema as sps  # noqa: E402
import materialize_gpu_successor_v2_inputs as v2  # noqa: E402


def _write_json(path: Path, body: Any) -> Path:
    path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    return path


def _make_tokenizer(root: Path) -> None:
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import PreTrainedTokenizerFast

    vocab = {"[UNK]": 0, "<bos>": 1, "<eos>": 2}
    for word in (  # noqa: SIM905 - readable synthetic vocabulary
        "system user assistant You answer only from the numbered sources provided Give a direct "
        "to question and nothing else If do not state it or cannot determine exactly stated What "
        "language is declared for this content Sources English French current old Answer with value"
    ).split():
        vocab.setdefault(word, len(vocab))
    backend = Tokenizer(WordLevel(vocab=vocab, unk_token="[UNK]"))  # noqa: S106
    backend.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=backend,
        unk_token="[UNK]",  # noqa: S106
        bos_token="<bos>",  # noqa: S106
        eos_token="<eos>",  # noqa: S106
    )
    tokenizer.chat_template = (
        "{% for message in messages %}{{ message['role'] }}: {{ message['content'] }}\n{% endfor %}"
        "{% if add_generation_prompt %}assistant:{% endif %}"
    )
    tokenizer.save_pretrained(root)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    acceptance = {
        "schema": "fixture.sfir4.acceptance.v1",
        "protocol_id": v2.SFIR4_PROTOCOL_ID,
        "verdict": "PASS",
    }
    acceptance_path = _write_json(tmp_path / "sfir4-acceptance.json", acceptance)
    facts = [
        {
            "fact_id": f"fact-{index:03d}",
            "kind": "LANGUAGE",
            "lineage_id": f"lineage-{index:03d}",
            "representation": {"iso": "en"},
        }
        for index in range(450)
    ]
    selection = [
        {
            "lineage_id": fact["lineage_id"],
            "fact_id": fact["fact_id"],
            "selection_sha256": v2.cohort_v2.canonical_sha(
                {
                    "rule": v2.cohort_v2.QUESTION_SELECTION_RULE,
                    "lineage_id": fact["lineage_id"],
                    "fact_id": fact["fact_id"],
                    "kind": fact["kind"],
                }
            ),
        }
        for fact in facts
    ]
    manifest = {
        "schema": v2.cohort_v2.MANIFEST_SCHEMA,
        "study_id": "GPU_SUCCESSOR_STUDY_V2",
        "feasible": True,
        "eligible_count": 450,
        "facts": facts,
        "facts_digest": v2._canonical_digest(facts),
        "question_selection": selection,
        "question_selection_digest": v2._canonical_digest(selection),
        "prompt_schema_digest": sps.schema_digest(),
        "source_sfir4_acceptance": {
            "path": str(acceptance_path),
            "sha256": v2.sha_file(acceptance_path),
            "protocol_id": v2.SFIR4_PROTOCOL_ID,
            "verdict": "PASS",
        },
    }
    manifest_path = _write_json(tmp_path / "manifest.json", manifest)

    def atom(atom_id: str, text: str) -> dict[str, str]:
        return {
            "atom_id": atom_id,
            "path": f"docs/{atom_id}.md",
            "text": text,
            "text_sha256": v2.sha_bytes(text.encode("utf-8")),
        }

    contexts = {
        fact["fact_id"]: {
            sps.ARMS[0]: [atom(f"cur-{index}", "English")],
            sps.ARMS[1]: [atom(f"old-{index}", "French")],
            sps.ARMS[2]: [atom(f"text-{index}", "English")],
        }
        for index, fact in enumerate(facts)
    }
    context = {
        "schema": v2.CONTEXT_SCHEMA,
        "successor_manifest_sha256": v2.sha_file(manifest_path),
        "sfir4_acceptance_sha256": v2.sha_file(acceptance_path),
        "facts_digest": manifest["facts_digest"],
        "context_by_fact": contexts,
        "contexts_digest": v2._canonical_digest(contexts),
    }
    context_path = _write_json(tmp_path / "context.json", context)

    tokenizer_root = tmp_path / "tokenizer"
    tokenizer_root.mkdir()
    _make_tokenizer(tokenizer_root)
    files = [
        {"path": path.relative_to(tokenizer_root).as_posix(), "sha256": v2.sha_file(path)}
        for path in sorted(tokenizer_root.rglob("*"))
        if path.is_file()
    ]
    token_manifest = {
        "schema": v2.TOKENIZER_MANIFEST_SCHEMA,
        "repository": sps.MODEL_REPOSITORY,
        "revision": sps.MODEL_REVISION,
        "files": files,
        "files_digest": v2._canonical_digest(files),
    }
    token_manifest_path = _write_json(tmp_path / "tokenizer-manifest.json", token_manifest)
    return manifest_path, context_path, tokenizer_root, token_manifest_path


def test_materializes_all_arms_with_exact_offline_token_counts_deterministically(tmp_path):
    paths = _fixture(tmp_path)
    first = v2.materialize_from_paths(*paths)
    second = v2.materialize_from_paths(*paths)
    assert first == second
    assert first["set_digest"].startswith("sha256:")
    assert first["tokenizer"]["offline_local_files_only"] is True
    item = first["items"][0]
    assert set(item["arms"]) == set(sps.ARMS)
    for arm in sps.ARMS:
        body = item["arms"][arm]
        assert body["input_token_count"] > 0
        assert body["input_token_ids_sha256"].startswith("sha256:")
        assert "no approximation" in body["token_count_method"]


def test_refuses_context_bound_to_other_manifest(tmp_path):
    manifest, context, tokenizer_root, token_manifest = _fixture(tmp_path)
    body = json.loads(context.read_text(encoding="utf-8"))
    body["successor_manifest_sha256"] = "sha256:" + "0" * 64
    _write_json(context, body)
    with pytest.raises(v2.MaterializationV2Refused, match="different successor manifest"):
        v2.materialize_from_paths(manifest, context, tokenizer_root, token_manifest)


def test_refuses_manifest_facts_digest_drift(tmp_path):
    manifest, context, tokenizer_root, token_manifest = _fixture(tmp_path)
    body = json.loads(manifest.read_text(encoding="utf-8"))
    body["facts"][0]["lineage_id"] = "changed-after-freeze"
    _write_json(manifest, body)
    with pytest.raises(v2.MaterializationV2Refused, match="facts_digest"):
        v2.materialize_from_paths(manifest, context, tokenizer_root, token_manifest)


def test_refuses_tampered_sfir4_acceptance_bytes(tmp_path):
    manifest, context, tokenizer_root, token_manifest = _fixture(tmp_path)
    body = json.loads(manifest.read_text(encoding="utf-8"))
    acceptance = Path(body["source_sfir4_acceptance"]["path"])
    acceptance.write_text('{"protocol_id":"other","verdict":"PASS"}', encoding="utf-8")
    with pytest.raises(v2.MaterializationV2Refused, match="acceptance bytes"):
        v2.materialize_from_paths(manifest, context, tokenizer_root, token_manifest)


def test_refuses_tampered_context_atom_even_if_outer_digest_is_recomputed(tmp_path):
    manifest, context, tokenizer_root, token_manifest = _fixture(tmp_path)
    body = json.loads(context.read_text(encoding="utf-8"))
    body["context_by_fact"]["fact-000"][sps.ARMS[0]][0]["text"] = "tampered"
    body["contexts_digest"] = v2._canonical_digest(body["context_by_fact"])
    _write_json(context, body)
    with pytest.raises(v2.MaterializationV2Refused, match="text_sha256 mismatch"):
        v2.materialize_from_paths(manifest, context, tokenizer_root, token_manifest)


def test_refuses_unlisted_tokenizer_file(tmp_path):
    paths = _fixture(tmp_path)
    (paths[2] / "unlisted.json").write_text("{}", encoding="utf-8")
    with pytest.raises(v2.MaterializationV2Refused, match="enumerate every regular file"):
        v2.materialize_from_paths(*paths)


def test_refuses_tokenizer_revision_drift(tmp_path):
    manifest, context, tokenizer_root, token_manifest = _fixture(tmp_path)
    body = json.loads(token_manifest.read_text(encoding="utf-8"))
    body["revision"] = "mutable-main"
    _write_json(token_manifest, body)
    with pytest.raises(v2.MaterializationV2Refused, match="exact pinned model revision"):
        v2.materialize_from_paths(manifest, context, tokenizer_root, token_manifest)


def test_refuses_missing_chat_template_instead_of_approximating(tmp_path, monkeypatch):
    paths = _fixture(tmp_path)

    class NoTemplate:
        pass

    monkeypatch.setattr(v2, "_load_real_tokenizer", lambda *_: NoTemplate())
    with pytest.raises(v2.MaterializationV2Refused, match="chat-template application failed"):
        v2.materialize_from_paths(*paths)


def test_cli_writes_only_explicit_export_and_refuses_overwrite(tmp_path):
    paths = _fixture(tmp_path)
    out = tmp_path / "explicit-export.json"
    argv = [*(str(path) for path in paths), "--output", str(out)]
    assert v2.main(argv) == 0
    assert out.is_file()
    assert v2.main(argv) == 4
    assert not (tmp_path / "receipts").exists()
