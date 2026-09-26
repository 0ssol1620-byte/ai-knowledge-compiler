"""Preflight's integration-pass sections: D9 GPU pools, D11 billing line."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from arena.controller.paths import CampaignPaths
from arena.controller.plan import ModelPlanEntry
from arena.controller.preflight import _billing_section, _gpu_pool_section
from arena.provider.runpod_pods import BillingWindow, RunPodClientError, RunPodPodsClient
from arena.provider.secrets import Secret
from tests.controller.conftest import (
    MODEL_KEY,
    make_sample,
    write_catalog_snapshot,
    write_model_registry,
    write_runtime_json,
    write_source_manifest,
)

KEY = Secret("runpodfake000000000000000000000000000000000000000", label="Runpod_B")


class _AngryClient(RunPodPodsClient):
    """A client whose billing endpoint is down. D11 says: report, do not gate."""

    def billing_pods(self, window: BillingWindow) -> object:
        raise RunPodClientError("RunPod returned HTTP 503 for GET /v2/billing/pods")


# ------------------------------------------------------------------ D11


def test_billing_failure_is_information_not_a_gate() -> None:
    client = _AngryClient(key=KEY, execute=False)
    try:
        section = _billing_section(client, BillingWindow(bucket_size="hour", last_n=24))
    finally:
        client.close()
    assert section.ok is True  # never a gate
    assert section.detail["account_wide_last_24h"] == "billing unavailable: RunPodClientError"
    assert "informational" in str(section.detail["gate"])


# ------------------------------------------------------------------- D9


def test_without_a_snapshot_the_pools_are_reported_unvalidated(
    paths: CampaignPaths,
) -> None:
    section = _gpu_pool_section(paths, None)
    assert section.ok is True
    assert section.detail["validated"] is False
    assert "preflight --execute" in str(section.detail["reason"])


def test_an_unknown_pool_name_fails_preflight_for_that_model(
    paths: CampaignPaths,
) -> None:
    write_catalog_snapshot(paths)
    write_runtime_json(paths, gpu_pool_priority=["NVIDIA A4O"])
    section = _gpu_pool_section(paths, None)
    assert section.ok is False
    failures = section.detail["failures"]
    assert isinstance(failures, list)
    assert any("NVIDIA A40" in line for line in failures)  # the near match is named


def test_a_valid_pool_passes(paths: CampaignPaths) -> None:
    write_catalog_snapshot(paths)
    write_runtime_json(paths)
    section = _gpu_pool_section(paths, None)
    # Every other model's runtime.json is absent in this fixture, so the section
    # still fails -- but it fails by *naming* what it could not read.
    assert section.detail["models_checked"] == 1
    unreadable = section.detail["unreadable_runtimes"]
    assert isinstance(unreadable, dict)
    assert MODEL_KEY not in unreadable
    assert section.detail["models_failing"] == []


# --------------------------------------------------------------- plan time


def test_plan_refuses_a_model_whose_pool_is_not_in_the_catalog(
    paths: CampaignPaths, entry: ModelPlanEntry, capsys: pytest.CaptureFixture[str]
) -> None:
    from arena.controller.cli import EXIT_BLOCKED, main

    write_source_manifest(paths.source_manifest, [make_sample(i) for i in range(3)])
    write_model_registry(
        paths.model_registry, entry, gpu_pool_priority=["NVIDIA GeForce RTX 40900"]
    )
    write_catalog_snapshot(paths)
    code = main(["plan", "--model", MODEL_KEY, "--root", str(paths.root)])
    assert code == EXIT_BLOCKED
    assert "does not carry" in capsys.readouterr().err


def test_plan_still_works_when_the_pool_is_known(
    paths: CampaignPaths, entry: ModelPlanEntry, capsys: pytest.CaptureFixture[str]
) -> None:
    from arena.controller.cli import EXIT_OK, main

    write_source_manifest(paths.source_manifest, [make_sample(i) for i in range(3)])
    write_model_registry(paths.model_registry, entry)
    write_catalog_snapshot(paths)
    assert main(["plan", "--model", MODEL_KEY, "--root", str(paths.root)]) == EXIT_OK
    assert "3 job(s)" in capsys.readouterr().out
    receipt = json.loads(
        (paths.receipts_dir / f"plan-{MODEL_KEY}.json").read_text(encoding="utf-8")
    )
    assert receipt["job_count"] == 3


# ------------------------------------------------------------------ D16


def test_the_registry_agreement_section_defers_to_lane_r() -> None:
    """D16: one implementation of "are these the same?", and it is lane R's.

    The controller must refuse to spend on a model whose two descriptions of
    which weights to load disagree, but it must not grow a second comparison
    that can drift from the one that does the regenerating.
    """

    from pathlib import Path

    from arena.controller.preflight import _registry_agreement_section

    namespace = Path(__file__).resolve().parents[2]
    section = _registry_agreement_section(CampaignPaths(root=namespace))

    assert section.detail["compared_by"] == "arena.registry.runtimes.overlay_disagreements"
    assert section.detail["models_compared"] == 11
    # The real files, as they stand: lane R regenerated the registry from the
    # runtime.json files, so nothing disagrees.
    assert section.ok is True, section.detail["disagreements"]


def test_a_d16_check_that_cannot_run_is_a_failure_not_a_pass(
    paths: CampaignPaths, entry: ModelPlanEntry
) -> None:
    """No silent fallback: an unanswered check blocks and says why."""

    from arena.controller.preflight import _registry_agreement_section

    write_runtime_json(paths)
    write_model_registry(paths.model_registry, entry)
    # No prompt_registry/, so lane R's helper cannot resolve the D17 hashes.
    section = _registry_agreement_section(paths)

    assert section.ok is False
    assert section.error is not None
    assert "not a pass" in section.error
    assert "lane R" in str(section.detail["owner_of_the_fix"])


def test_a_missing_registry_blocks_and_names_its_owner(paths: CampaignPaths) -> None:
    from arena.controller.preflight import _registry_agreement_section

    section = _registry_agreement_section(paths)
    assert section.ok is False
    assert section.error is not None and "lane R writes it" in section.error


# ------------------------------------- the three hashes a run request carries


def test_the_run_config_section_agrees_across_the_real_namespace() -> None:
    """The values the controller would send are the ones the worker recomputes.

    Pod 27f6f6dif3jcp6 rented an RTX 4090 on 2026-09-03, reached READY and
    answered HTTP 422 CONFIG_MISMATCH to all 13 pages it was given, because the
    controller had been filling ``inference_config_sha256`` from the registry's
    ``official_inference_config_sha256`` -- the model card's documented serve
    command -- while the worker hashes runtime.json's operational
    ``inference_config``. This section is that comparison, done for free.
    """

    from pathlib import Path

    from arena.controller.preflight import _run_config_section

    namespace = Path(__file__).resolve().parents[2]
    section = _run_config_section(CampaignPaths(root=namespace))

    assert section.detail["models_checked"] == 11
    assert section.detail["unreadable"] == []
    assert section.ok is True, section.detail["disagreements"]


def test_the_registry_carries_the_hash_the_worker_computes() -> None:
    """Directly, without the section around it: one function, one object."""

    import json
    from pathlib import Path

    from arena.worker.util import config_sha256

    namespace = Path(__file__).resolve().parents[2]
    registry = json.loads((namespace / "model_registry.json").read_text(encoding="utf-8"))
    checked = 0
    for model_key, record in sorted(registry["models"].items()):
        runtime_path = namespace / "runtimes" / model_key / "runtime.json"
        if not runtime_path.is_file():  # the Opus lane has none (section 7)
            assert "inference_config_sha256" not in record, model_key
            continue
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        assert record["inference_config_sha256"] == config_sha256(runtime["inference_config"])
        # And it is genuinely a different value from the model-card hash, so a
        # future resolver cannot satisfy this by writing the old one twice.
        assert record["inference_config_sha256"] != record["official_inference_config_sha256"]
        checked += 1
    assert checked == 11


def test_a_registry_that_disagrees_with_its_runtime_is_a_disagreement(
    paths: CampaignPaths, entry: ModelPlanEntry
) -> None:
    """The exact 2026-09-03 shape, rebuilt: a registry hash of something else."""

    import json

    from arena.controller.preflight import check_run_config
    from arena.worker.util import config_sha256
    from tests.controller.conftest import PROMPT_ID, write_prompt_registry

    inference_config = {"max_new_tokens": 4096, "temperature": 0.0}
    write_runtime_json(paths, inference_config=inference_config, prompt_kind="none")
    index = write_prompt_registry(paths, prompt_id=PROMPT_ID, text="")
    prompt_sha = json.loads(index.read_text(encoding="utf-8"))[PROMPT_ID]

    agreed = replace(
        entry,
        prompt_id=PROMPT_ID,
        prompt_sha256=prompt_sha,
        inference_config_sha256=config_sha256(inference_config),
    )
    write_model_registry(paths.model_registry, agreed)
    assert check_run_config(paths, MODEL_KEY).ok is True

    # Now the field the canary actually carried: a hash of the model card.
    write_model_registry(
        paths.model_registry,
        replace(agreed, inference_config_sha256="sha256:" + "f" * 64),
    )
    result = check_run_config(paths, MODEL_KEY)
    assert result.unreadable == ()
    assert len(result.disagreements) == 1
    assert "inference_config_sha256" in result.disagreements[0]
    assert "CONFIG_MISMATCH" in result.disagreements[0]


def test_a_prompt_file_that_does_not_hash_to_the_registry_is_caught(
    paths: CampaignPaths, entry: ModelPlanEntry
) -> None:
    import json

    from arena.controller.preflight import check_run_config
    from arena.worker.util import config_sha256
    from tests.controller.conftest import PROMPT_ID, write_prompt_registry

    inference_config = {"max_new_tokens": 4096}
    write_runtime_json(paths, inference_config=inference_config, prompt_kind="text")
    index = write_prompt_registry(paths, prompt_id=PROMPT_ID, text="Transcribe this page.\n")
    prompt_sha = json.loads(index.read_text(encoding="utf-8"))[PROMPT_ID]
    write_model_registry(
        paths.model_registry,
        replace(
            entry,
            prompt_id=PROMPT_ID,
            prompt_sha256=prompt_sha,
            inference_config_sha256=config_sha256(inference_config),
        ),
    )
    assert check_run_config(paths, MODEL_KEY).ok is True

    # The file is edited without regenerating anything, exactly as a hand fix
    # to a prompt would leave it.
    (paths.prompt_registry_dir / f"{PROMPT_ID}.txt").write_bytes(b"Transcribe the page.\n")
    result = check_run_config(paths, MODEL_KEY)
    assert any("PROMPT_MISMATCH" in line for line in result.disagreements)


def test_missing_files_are_unreadable_not_a_disagreement(paths: CampaignPaths) -> None:
    """The provisioning gate names the missing file; this check must not shout first."""

    from arena.controller.preflight import check_run_config

    result = check_run_config(paths, MODEL_KEY)
    assert result.disagreements == ()
    assert result.unreadable and "model_registry.json is not usable" in result.unreadable[0]
    assert result.ok is False
