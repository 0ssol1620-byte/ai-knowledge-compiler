"""End to end, no network: gate -> provider create -> pod ledger (D2, D6, D7).

The provider is a fake transport; nothing is created, nothing is paid. What is
being proved is the *order*: the authorization and licence gates decide before
a create request is ever built, and the create that follows carries the shape
D2 specifies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import pytest
from arena.controller import cli as cli_module
from arena.controller.cli import EXIT_BLOCKED, EXIT_OK, main
from arena.controller.gpu_pools import latest_price_snapshot_path, load_price_snapshot
from arena.controller.paths import CampaignPaths
from arena.controller.plan import ModelPlanEntry
from arena.controller.provision import RUNPOD_CUDA_VERSIONS
from arena.controller.queue import CampaignQueue
from arena.provider import runpod_v1
from arena.provider.runpod_pods import PodSpec, ProviderReceipt
from arena.provider.runpod_v1 import PodV1, RunPodV1Client
from arena.provider.secrets import Secret
from tests.controller.conftest import (
    MODEL_KEY,
    make_sample,
    sample_bytes,
    write_authorization,
    write_bundle_receipt,
    write_catalog_snapshot,
    write_model_registry,
    write_prompt_registry,
    write_runtime_json,
    write_source_manifest,
)
from tests.controller.fake_worker import FakeWorkerTransport, fake_worker_client

BUNDLE_SHA = "f" * 64
SIGNED_URL = (
    "https://fakeaccount.eu.r2.cloudflarestorage.com/tavonel-arena-20260903/"
    "bundles/paddleocr_vl_1_6/arena-bundle.tar.gz"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=deadbeefdeadbeefdeadbeef"
)


def _start_cmd(model_key: str, bundle_sha256: str) -> str:
    return (
        "set -euo pipefail; mkdir -p /opt/arena; "
        'curl -fsSL --retry 5 --max-time 900 "$ARENA_BUNDLE_URL" -o /tmp/arena-bundle.tar.gz; '
        f'echo "{bundle_sha256}  /tmp/arena-bundle.tar.gz" | sha256sum -c -; '
        f"tar -xzf /tmp/arena-bundle.tar.gz -C /opt/arena; exec bash /opt/arena/bootstrap.sh"
        f"  # {model_key}"
    )


class FakeV1Client:
    """Records the spec it was handed and answers like a live create would."""

    created: ClassVar[list[PodSpec]] = []
    stopped: ClassVar[list[str]] = []
    deleted: ClassVar[list[str]] = []
    live: ClassVar[set[str]] = set()
    # D48: when true the first pool entry is refused for capacity and the
    # second one answers, which is the walk the real client performs inside a
    # single ``create_pod`` call.
    refuse_first: ClassVar[bool] = False

    def __init__(self, *, execute: bool) -> None:
        self.execute = execute
        # The real client receipts every create attempt and the pod ledger
        # reads the walk back out of `receipts`; a double without it would
        # let a missing attempt trail pass unnoticed.
        self._receipts: list[ProviderReceipt] = []

    @property
    def receipts(self) -> tuple[ProviderReceipt, ...]:
        return tuple(self._receipts)

    def create_pod(self, spec: PodSpec, *, price_snapshot: Any = None) -> Any:
        FakeV1Client.created.append(spec)
        if not self.execute:
            return ProviderReceipt(
                action="create_pod",
                method="POST",
                url="https://rest.runpod.io/v1/pods",
                mode="dry_run",
                request_sha256="0" * 64,
                ts="2026-09-03T13:00:00Z",
                summary={"provider_api_version": "v1"},
            )
        FakeV1Client.live.add("podfakelive1")
        index = 0
        if FakeV1Client.refuse_first:
            self._receipts.append(
                ProviderReceipt(
                    action="create_pod",
                    method="POST",
                    url="https://rest.runpod.io/v1/pods",
                    mode="live",
                    request_sha256="2" * 64,
                    ts="2026-09-03T13:00:00Z",
                    status_code=400,
                    summary={
                        "created": False,
                        "attempt": 1,
                        "gpu_type_ids": [spec.gpu_type_ids[0]],
                        "allowed_cuda_versions": list(spec.allowed_cuda_versions),
                        "refused": "no instances available for the requested GPU",
                    },
                )
            )
            index = 1
        self._receipts.append(
            ProviderReceipt(
                action="create_pod",
                method="POST",
                url="https://rest.runpod.io/v1/pods",
                mode="live",
                request_sha256="1" * 64,
                ts="2026-09-03T13:00:00Z",
                status_code=201,
                summary={
                    "created": True,
                    "attempt": index + 1,
                    "gpu_type_ids": [spec.gpu_type_ids[index]],
                    "allowed_cuda_versions": list(spec.allowed_cuda_versions),
                },
            )
        )
        return PodV1(
            pod_id="podfakelive1",
            name=spec.name,
            desired_status="RUNNING",
            image=spec.image_name,
            cost_usd_per_hour=0.69,
            data_center_id="EU-RO-1",
            gpu_type_id=spec.gpu_type_ids[index],
            gpu_count=spec.gpu_count,
            cuda_version="12.9",
            machine_id="s194cr8pls2z",
            last_started_at="2026-09-03T13:00:00Z",
            container_disk_gb=spec.container_disk_gb,
            volume_gb=spec.volume_gb,
            docker_entrypoint=("/bin/bash", "-c"),
            docker_start_cmd_element_count=1,
            env={"ARENA_MODEL_KEY": spec.model_key},
        )

    # ---- teardown. D20's `finally` calls all three of these.

    def stop_pod(self, pod_id: str) -> object:
        FakeV1Client.stopped.append(pod_id)
        return {"id": pod_id, "desiredStatus": "EXITED"}

    def delete_pod(self, pod_id: str) -> object:
        FakeV1Client.deleted.append(pod_id)
        FakeV1Client.live.discard(pod_id)
        return {"id": pod_id, "deleted": True}

    def list_pods(self) -> list[Any]:
        return [pod for pod in () if pod] if not FakeV1Client.live else [_LivePod(
            pod_id=next(iter(FakeV1Client.live))
        )]

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class _LivePod:
    """Just enough of a pod for `_absent` to recognise an id in a listing."""

    pod_id: str


class FakeV2Client:
    """The baked-mode API, plus the catalog D23 refreshes under --execute.

    Without this, an ``--execute`` test really did reach
    ``api.runpod.io/v2/catalog/gpus`` -- a live network call, and a price no
    fixture controls. The catalog here is the snapshot the fixture wrote.
    """

    snapshot_dir: ClassVar[Path]

    def __init__(self, *, execute: bool) -> None:
        self.execute = execute
        self._receipts: list[ProviderReceipt] = []

    @property
    def receipts(self) -> tuple[ProviderReceipt, ...]:
        return tuple(self._receipts)

    def catalog_gpus(self, *, cloud: str | None = None) -> Any:
        path = latest_price_snapshot_path(FakeV2Client.snapshot_dir)
        assert path is not None, "the fixture must write a catalog snapshot first"
        return load_price_snapshot(path)

    def list_pods(self) -> list[Any]:
        return [_LivePod(pod_id=pod) for pod in sorted(FakeV1Client.live)]

    def stop_pod(self, pod_id: str) -> object:
        return {"id": pod_id}

    def delete_pod(self, pod_id: str) -> object:
        FakeV1Client.live.discard(pod_id)
        return {"id": pod_id}

    def close(self) -> None:
        return None


@pytest.fixture
def bootstrap_campaign(
    paths: CampaignPaths,
    entry: ModelPlanEntry,
    credential_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> CampaignPaths:
    """A campaign whose every input for a canary exists except the money."""

    # Four pages, not one: the first is cold by definition, so a single-page
    # canary has no warm sample and nothing section 18 can project from.
    selected = [make_sample(index) for index in range(1, 5)]
    paths.canary_selection.write_text(
        json.dumps({"case_keys": [sample.case_key for sample in selected]}),
        encoding="utf-8",
    )
    write_model_registry(paths.model_registry, entry)
    write_runtime_json(paths, runtime_mode_allowed=["bootstrap"])
    write_catalog_snapshot(paths)
    FakeV2Client.snapshot_dir = paths.provider_receipts_dir
    # D21: a bootstrap canary learns its bundle digest from the publish
    # receipt; `--bundle-sha256` is only ever a cross-check against it.
    write_bundle_receipt(paths, bundle_sha256=BUNDLE_SHA)
    # D17: the prompt the pod will be told to use, and the hash of the bytes.
    write_prompt_registry(paths, text="")
    # D14: the manifest row the selected case key names, and the page bytes
    # on disk under a staged root this test owns.
    write_source_manifest(paths.source_manifest, selected)
    for sample in selected:
        page = paths.root / "staged-public-core" / sample.image_path
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_bytes(sample_bytes(sample))

    FakeV1Client.created = []
    FakeV1Client.stopped = []
    FakeV1Client.deleted = []
    FakeV1Client.live = set()
    FakeV1Client.refuse_first = False
    FakeWorker.transport = FakeWorkerTransport(
        stages=["IMAGE_READY", "MODEL_LOADING", "WARMING", "READY"],
        run_override=lambda job_id: _worker_body(job_id),
    )
    monkeypatch.setattr(
        cli_module,
        "make_worker_client",
        lambda pod_id, *, bearer: fake_worker_client(
            FakeWorker.transport, pod_id=pod_id
        ),
    )
    monkeypatch.setattr(runpod_v1, "render_start_cmd", _start_cmd, raising=False)
    monkeypatch.setattr(
        cli_module,
        "make_v1_client",
        lambda *, key, execute, receipts_dir: FakeV1Client(execute=execute),
    )
    monkeypatch.setattr(
        cli_module,
        "make_v2_client",
        lambda *, key, execute, receipts_dir: FakeV2Client(execute=execute),
    )
    monkeypatch.setattr(
        cli_module,
        "_bundle_url",
        lambda paths, *, key, execute, args: Secret(SIGNED_URL, label="ARENA_BUNDLE_URL"),
    )
    monkeypatch.setenv("ARENA_WORKER_TOKEN", "arena-fake-campaign-worker-token-0")
    return paths


class FakeWorker:
    """Holder for the transport the CLI seam hands back, per test."""

    transport: ClassVar[FakeWorkerTransport]


def _worker_body(job_id: str) -> dict[str, object]:
    """A SUCCESS response that agrees with the digest we provisioned (D15)."""

    from tests.controller.fake_worker import worker_response_body

    return worker_response_body(
        job_id,
        runtime_mode="bootstrap",
        runtime_image_digest=f"bootstrap:sha256:{BUNDLE_SHA}",
    )


def _canary_argv_without_digest(paths: CampaignPaths, *extra: str) -> list[str]:
    """The same argv, minus ``--bundle-sha256``: D21 makes the flag optional."""

    return [
        "canary",
        "--model",
        MODEL_KEY,
        "--root",
        str(paths.root),
        "--staged-root",
        str(paths.root / "staged-public-core"),
        "--ready-poll-seconds",
        "0",
        *extra,
    ]


def _canary_argv(paths: CampaignPaths, *extra: str) -> list[str]:
    return [
        "canary",
        "--model",
        MODEL_KEY,
        "--root",
        str(paths.root),
        "--staged-root",
        str(paths.root / "staged-public-core"),
        "--ready-poll-seconds",
        "0",
        "--bundle-sha256",
        BUNDLE_SHA,
        *extra,
    ]


# --------------------------------------------------------------- authorized


def test_authorized_canary_execute_reaches_the_v1_create(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0)
    code = main(_canary_argv(paths, "--execute"))
    out = capsys.readouterr()
    out = out.out + out.err
    print(out)
    assert code == EXIT_OK
    assert "authorization: GRANTED" in out
    assert "provider API: REST v1 (live)" in out

    assert len(FakeV1Client.created) == 1
    spec = FakeV1Client.created[0]
    assert spec.runtime_mode == "bootstrap"
    assert spec.bundle_sha256 == BUNDLE_SHA
    assert spec.max_lifetime_hours == 2  # D10
    assert spec.gpu_count == 1  # D5, from runtime.json

    payload = runpod_v1.v1_create_payload(
        spec, gpu_type_ids=spec.gpu_type_ids, start_command=_start_cmd(MODEL_KEY, BUNDLE_SHA)
    )
    assert payload["dockerEntrypoint"] == ["/bin/bash", "-c"]  # D29
    start = payload["dockerStartCmd"]
    assert isinstance(start, list) and len(start) == 1
    assert BUNDLE_SHA in start[0]


def test_the_pod_ledger_records_the_api_version_and_the_authorization(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = bootstrap_campaign
    receipt_path = write_authorization(paths, max_usd=25.0)
    assert main(_canary_argv(paths, "--execute")) == EXIT_OK
    capsys.readouterr()

    lines = paths.pod_provisioning_ledger.read_text(encoding="utf-8").strip().splitlines()
    # D24: a provisional line names the pod *before* the POST, so an ambiguous
    # create still leaves a record. The settled line follows it.
    assert len(lines) == 2
    provisional = json.loads(lines[0])
    assert provisional["schema"].endswith("pod_provisioning_intent.v1") or provisional.get(
        "provisional"
    )
    record = json.loads(lines[1])
    assert record["provider_api_version"] == "v1"
    assert record["pod_id"] == "podfakelive1"
    assert record["authorization_receipt_path"] == str(receipt_path)
    assert len(record["authorization_receipt_sha256"]) == 64
    assert record["max_pod_lifetime_hours"] == 2
    env = record["create_payload_redacted"]["env"]
    assert env["ARENA_WORKER_TOKEN"] == "<redacted>"  # noqa: S105 - the marker
    assert env["ARENA_BUNDLE_URL"].endswith("arena-bundle.tar.gz")
    assert "X-Amz-Signature" not in json.dumps(record)

    with CampaignQueue(paths.queue_db) as queue:
        pods = queue.pods()
    assert len(pods) == 1
    assert pods[0].provider_api_version == "v1"
    assert pods[0].authorization_receipt_path == str(receipt_path)


def test_the_dry_run_prints_the_redacted_payload_and_creates_nothing(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0)
    assert main(_canary_argv(paths)) == EXIT_OK
    out = capsys.readouterr().out
    assert "provider API: REST v1 (dry_run)" in out
    assert "redacted create payload:" in out
    assert '"dockerStartCmd"' in out
    # The dry run is what the founder reads before writing an authorization
    # receipt, so the host CUDA filter has to be visible in it too.
    assert '"allowedCudaVersions"' in out
    assert "host CUDA: >= 12.8 -> allowedCudaVersions ['12.8', '12.9', '13.0']" in out
    assert "X-Amz-Signature" not in out
    with CampaignQueue(paths.queue_db) as queue:
        assert queue.pods() == ()


# ------------------------------------------------------------------ blocked


def test_a_missing_authorization_blocks_before_any_create(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = bootstrap_campaign
    assert main(_canary_argv(paths, "--execute")) == EXIT_BLOCKED
    out = capsys.readouterr().out
    assert "authorization: BLOCKED" in out
    assert "holds no authorization receipt" in out
    assert FakeV1Client.created == []
    gate = json.loads(paths.canary_provision_receipt(MODEL_KEY).read_text(encoding="utf-8"))
    assert gate["authorization"]["allowed"] is False
    assert gate["provisioning"] is None


def test_an_expired_authorization_blocks(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0, expires_at="2026-09-03T00:00:01Z")
    assert main(_canary_argv(paths, "--execute")) == EXIT_BLOCKED
    assert "expired" in capsys.readouterr().out
    assert FakeV1Client.created == []


def test_an_insufficient_authorization_blocks(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = bootstrap_campaign
    write_authorization(paths, max_usd=0.01)
    assert main(_canary_argv(paths, "--execute")) == EXIT_BLOCKED
    out = capsys.readouterr().out
    assert "authorization: BLOCKED" in out
    assert "max_usd=0.01" in out
    assert FakeV1Client.created == []


def test_a_blocked_licence_without_a_waiver_blocks(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0)
    write_runtime_json(
        paths,
        runtime_mode_allowed=["bootstrap"],
        license={"id": "Apache-2.0", "url": "https://example.invalid", "status": "blocked"},
    )
    assert main(_canary_argv(paths, "--execute")) == EXIT_BLOCKED
    assert "no founder waiver" in capsys.readouterr().out
    assert FakeV1Client.created == []


def test_a_licence_waiver_lets_the_blocked_model_through(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0)
    write_runtime_json(
        paths,
        runtime_mode_allowed=["bootstrap"],
        license={"id": "Apache-2.0", "url": "https://example.invalid", "status": "blocked"},
    )
    paths.license_waiver(MODEL_KEY).write_text(
        json.dumps({"model_key": MODEL_KEY, "decided_by": "founder"}), encoding="utf-8"
    )
    assert main(_canary_argv(paths, "--execute")) == EXIT_OK
    assert "founder licence waiver on file" in capsys.readouterr().out
    assert len(FakeV1Client.created) == 1


def test_an_unknown_gpu_pool_name_blocks(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0)
    write_runtime_json(
        paths,
        runtime_mode_allowed=["bootstrap"],
        gpu_pool_priority=["NVIDIA A4O"],
    )
    assert main(_canary_argv(paths, "--execute")) == EXIT_BLOCKED
    err = capsys.readouterr().err
    assert "does not carry" in err
    assert "NVIDIA A40" in err  # the near match is named
    assert FakeV1Client.created == []


def test_bootstrap_without_a_publish_receipt_is_refused(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """D21: no publish receipt, no canary -- and the fix is named."""

    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0)
    paths.bundle_receipt(MODEL_KEY).unlink()
    code = main(_canary_argv_without_digest(paths, "--execute"))
    assert code == EXIT_BLOCKED
    combined = capsys.readouterr()
    message = combined.out + combined.err
    assert "receipts/bundles/paddleocr_vl_1_6.json is absent" in message
    assert "arena.controller bundle --model paddleocr_vl_1_6 --execute" in message
    assert FakeV1Client.created == []


def test_bootstrap_reads_the_digest_from_the_receipt_without_an_argv_flag(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """D21 moves the digest into the receipt; the flag becomes optional."""

    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0)
    code = main(_canary_argv_without_digest(paths, "--execute"))
    capsys.readouterr()
    assert code == EXIT_OK
    assert len(FakeV1Client.created) == 1
    assert FakeV1Client.created[0].bundle_sha256 == BUNDLE_SHA


def test_an_argv_digest_that_disagrees_with_the_receipt_is_refused(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """An operator cannot hand-type a digest for bytes nothing vouches for."""

    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0)
    code = main(
        _canary_argv_without_digest(paths, "--bundle-sha256", "a" * 64, "--execute")
    )
    message = "".join(capsys.readouterr())
    assert code == EXIT_BLOCKED
    assert "does not equal the published" in message
    assert FakeV1Client.created == []


def test_a_dry_run_publish_receipt_is_not_good_enough_to_rent_a_gpu(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """A bundle that was never uploaded would fail sha256sum after the bill."""

    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0)
    write_bundle_receipt(paths, bundle_sha256=BUNDLE_SHA, uploaded=False)
    code = main(_canary_argv(paths, "--execute"))
    message = "".join(capsys.readouterr())
    assert code == EXIT_BLOCKED
    assert "records a dry run" in message
    assert FakeV1Client.created == []


def test_the_seam_really_builds_a_v1_client() -> None:
    """The fake stands in for a real client; keep the seam honest."""

    client = cli_module.make_v1_client(
        key=Secret("runpodfake000000000000000000000000000000000000000", label="Runpod_B"),
        execute=False,
        receipts_dir=None,
    )
    try:
        assert isinstance(client, RunPodV1Client)
        assert client.base_url == "https://rest.runpod.io/v1"
    finally:
        client.close()


# ------------------------------------------------------- the host CUDA floor


def test_a_runtime_without_a_cuda_floor_is_refused_naming_the_file(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pod 3xag0y00rgoj4n's failure mode, refused before the pod is billing."""

    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0)
    write_runtime_json(paths, runtime_mode_allowed=["bootstrap"], min_cuda_version=None)
    code = main(_canary_argv(paths, "--execute"))
    message = "".join(capsys.readouterr())
    assert code == EXIT_BLOCKED
    assert f"runtimes/{MODEL_KEY}/runtime.json" in message
    assert "min_cuda_version" in message
    # Refused *before* any create: nothing reached the provider or the ledger.
    assert FakeV1Client.created == []
    assert not paths.pod_provisioning_ledger.exists()


def test_the_ledger_and_the_gate_receipt_record_the_cuda_constraint(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0)
    assert main(_canary_argv(paths, "--execute")) == EXIT_OK
    capsys.readouterr()

    # The fixture's runtime declares 12.8, so every version RunPod lists at or
    # above it is acceptable -- a newer host driver runs an older-CUDA image.
    expected = ["12.8", "12.9", "13.0"]

    lines = paths.pod_provisioning_ledger.read_text(encoding="utf-8").strip().splitlines()
    intent = json.loads(lines[0])
    record = json.loads(lines[1])
    assert intent["allowed_cuda_versions"] == expected
    assert record["allowed_cuda_versions"] == expected
    assert record["create_payload_redacted"]["allowedCudaVersions"] == expected
    # Which pool entry answered, and what the host reported once it did.
    assert record["gpu_type_id_created"] == "NVIDIA GeForce RTX 4090"
    assert record["host_cuda_version"] == "12.9"
    assert [attempt["attempt"] for attempt in record["provider_attempts"]] == [1]

    gate = json.loads(
        paths.canary_provision_receipt(MODEL_KEY).read_text(encoding="utf-8")
    )
    assert gate["cuda"] == {
        "model_key": MODEL_KEY,
        "runtime_json": f"runtimes/{MODEL_KEY}/runtime.json",
        "min_cuda_version": "12.8",
        "allowed_cuda_versions": expected,
        "provider_field": "allowedCudaVersions",
    }


def test_a_floor_of_11_8_allows_every_version_runpod_lists(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """The oldest floor constrains nothing, and still says so explicitly."""

    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0)
    write_runtime_json(paths, runtime_mode_allowed=["bootstrap"], min_cuda_version="11.8")
    assert main(_canary_argv(paths, "--execute")) == EXIT_OK
    capsys.readouterr()
    record = json.loads(
        paths.pod_provisioning_ledger.read_text(encoding="utf-8").strip().splitlines()[1]
    )
    assert record["allowed_cuda_versions"] == list(RUNPOD_CUDA_VERSIONS)
    assert record["create_payload_redacted"]["allowedCudaVersions"][0] == "11.8"


# ------------------------------------------------------ D48: the walked GPU


def test_the_pod_ledger_names_the_gpu_the_pool_walk_actually_created(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """The 2026-09-03 GLM-OCR row named a GPU that was never rented.

    ``cost/pod_ledger.jsonl`` said ``NVIDIA L40S`` while the pod that ran was a
    GeForce RTX 4090 at $0.74/h: the estimate names the *most expensive* pool
    entry as a ceiling to authorize against, and nothing downstream replaced it
    with the entry the walk actually rented. Here the first pool entry is
    refused for capacity and the second answers, so the ledger must name the
    second and price it from that GPU's own snapshot row.
    """

    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0)
    FakeV1Client.refuse_first = True
    assert main(_canary_argv(paths, "--execute")) == EXIT_OK
    out = capsys.readouterr()
    printed = out.out + out.err

    # The quote priced the ceiling: the 4090 at $0.69/h, the dearer of the two.
    provisioning = [
        json.loads(line)
        for line in paths.pod_provisioning_ledger.read_text(encoding="utf-8")
        .strip()
        .splitlines()
    ]
    assert provisioning[-1]["listed_rate_usd_per_hour"] == 0.69
    assert provisioning[-1]["gpu_type_id_created"] == "NVIDIA A40"
    assert [attempt["created"] for attempt in provisioning[-1]["provider_attempts"]] == [
        False,
        True,
    ]

    ledger = paths.root / "cost" / "pod_ledger.jsonl"
    row = json.loads(ledger.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["gpu_type"] == "NVIDIA A40"
    assert row["listed_rate_usd_per_hour"] == 0.44
    assert "the pool walk created a NVIDIA A40" in printed


def test_a_walk_that_never_falls_back_leaves_the_quoted_gpu_alone(
    bootstrap_campaign: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = bootstrap_campaign
    write_authorization(paths, max_usd=25.0)
    assert main(_canary_argv(paths, "--execute")) == EXIT_OK
    capsys.readouterr()

    ledger = paths.root / "cost" / "pod_ledger.jsonl"
    row = json.loads(ledger.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["gpu_type"] == "NVIDIA GeForce RTX 4090"
    assert row["listed_rate_usd_per_hour"] == 0.69


def test_a_created_gpu_the_snapshot_does_not_price_leaves_the_rate_empty() -> None:
    """Naming the wrong GPU is worse than an empty rate, so the rate goes.

    ``_write_ledger`` then falls back to the provider's own ``costPerHr``,
    which is the only figure anyone was actually charged.
    """

    from arena.controller.driver import _price_created_gpu
    from arena.provider.runpod_pods import GpuPriceRow, PriceSnapshot

    snapshot = PriceSnapshot(
        captured_at="2026-09-03T12:00:00Z",
        rows=(
            GpuPriceRow(
                gpu_type_id="NVIDIA L40S",
                display_name="L40S",
                memory_gb=48,
                secure_available=True,
                community_available=False,
                price_secure_usd_per_hour=1.14,
                price_community_usd_per_hour=None,
            ),
        ),
    )
    notes: list[str] = []
    gpu, rate, row_sha = _price_created_gpu(
        {"gpu_type_id_created": "NVIDIA GeForce RTX 4090"},
        snapshot=snapshot,
        cloud="SECURE",
        quoted_gpu_type="NVIDIA L40S",
        quoted_rate_usd=1.14,
        quoted_row_sha256="a" * 64,
        notes=notes,
        say=lambda line: None,
    )
    assert gpu == "NVIDIA GeForce RTX 4090"
    assert rate is None
    assert row_sha is None
    assert "the price snapshot does not carry" in notes[0]


def test_the_created_gpu_falls_back_to_the_winning_create_attempt() -> None:
    """A v1 pod record that has not scheduled yet reports no GPU type at all."""

    from arena.controller.provision import ProvisionResult

    result = ProvisionResult(
        provider_api_version="v1",
        mode="live",
        pod_id="podfakelive1",
        redacted_payload={},
        summary={"gpu_type_id": None},
        attempts=(
            {"attempt": 1, "created": False, "gpu_type_ids": ["NVIDIA L40S"]},
            {"attempt": 2, "created": True, "gpu_type_ids": ["NVIDIA A40"]},
        ),
    )
    assert result.gpu_type_id_created == "NVIDIA A40"
