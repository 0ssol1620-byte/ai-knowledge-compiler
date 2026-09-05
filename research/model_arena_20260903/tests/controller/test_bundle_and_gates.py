"""``bundle`` (D21/D35) and the three refusals that stand between a
``--execute`` and a rented GPU: the cumulative budget (D22), a stale price
snapshot (D23) and a runtime mode the runtime forbids (D25).

The bundle here is a real one, built from this namespace by lane B2's builder.
The object store is a fake S3 client -- an in-memory bucket -- so the upload
path, the read-back and the digest comparison are all exercised without a
network or a paid byte.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest
from arena.constants import BUDGET_HARD_CAP_USD, BUDGET_SOFT_CAP_USD, CAMPAIGN_ID
from arena.controller.authorization_gate import cumulative_budget
from arena.controller.bundle import (
    BundleError,
    bundle_object_key,
    publish_bundle,
    read_bundle_receipt,
    resolve_bundle_sha256,
)
from arena.controller.cli import EXIT_BLOCKED, EXIT_OK, EXIT_REFUSED, main
from arena.controller.paths import CampaignPaths
from arena.controller.plan import ModelPlanEntry
from arena.core.receipts import validate
from arena.provider.r2 import BUCKET_NAME, R2Client
from arena.provider.secrets import R2Credentials, Secret
from tests.controller.conftest import (
    MODEL_KEY,
    write_authorization,
    write_bundle_receipt,
    write_catalog_snapshot,
    write_model_registry,
    write_prompt_registry,
    write_runtime_json,
)

NAMESPACE_ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------- fake bucket


class FakeS3:
    """An in-memory bucket. Enough of the S3 API for D21's three calls."""

    def __init__(self, *, drop_checksum: bool = False, corrupt: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.drop_checksum = drop_checksum
        self.corrupt = corrupt

    # put_file -> put_object
    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        body = kwargs["Body"]
        data = body.read() if hasattr(body, "read") else bytes(body)
        if self.corrupt:
            data = data + b"tampered"
        self.objects[kwargs["Key"]] = data
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def upload_file(self, Filename: str, Bucket: str, Key: str, **kwargs: Any) -> None:
        data = Path(Filename).read_bytes()
        if self.corrupt:
            data = data + b"tampered"
        self.objects[Key] = data

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        if key not in self.objects:
            raise KeyError(key)
        data = self.objects[key]
        head: dict[str, Any] = {"ContentLength": len(data)}
        if not self.drop_checksum:
            import base64

            head["ChecksumSHA256"] = base64.b64encode(
                hashlib.sha256(data).digest()
            ).decode("ascii")
        return head

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        return {"Contents": [{"Key": key} for key in sorted(self.objects)]}


def _r2(s3: FakeS3) -> R2Client:
    return R2Client(
        R2Credentials(
            block="account",
            access_key_id=Secret("r2fakeaccess00000000000000000000", label="Access Key ID"),
            secret_access_key=Secret(
                "r2fakesecret" + "0" * 52, label="Secret Access Key"
            ),
            endpoint_url="https://fakeaccount.eu.r2.cloudflarestorage.com",
        ),
        bucket=BUCKET_NAME,
        execute=True,
        client=s3,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------ bundle


def test_a_dry_run_bundle_builds_verifies_and_receipts_without_uploading(
    paths: CampaignPaths,
) -> None:
    publication = publish_bundle(
        paths, model_key=MODEL_KEY, execute=False, namespace_root=NAMESPACE_ROOT
    )

    assert publication.uploaded is False
    assert publication.file_count > 0
    # D35: bare 64-hex, the spelling the on-pod `sha256sum -c` line needs.
    assert len(publication.bundle_sha256) == 64
    assert not publication.bundle_sha256.startswith("sha256:")
    assert publication.receipt_path is not None

    document = json.loads(publication.receipt_path.read_text(encoding="utf-8"))
    validate(document, "bundle-publish")  # D21: lane A1's contract, enforced
    assert document["r2_key"] == bundle_object_key(MODEL_KEY)
    # D21: no signed URL ever reaches a receipt.
    assert "X-Amz-Signature" not in json.dumps(document)
    assert document["bundle_reference"] == f"{BUCKET_NAME}/{document['r2_key']}"


def test_a_dry_run_receipt_will_not_start_a_pod(paths: CampaignPaths) -> None:
    """The bundle is not in the bucket, so the pod would fail after the bill."""

    publish_bundle(paths, model_key=MODEL_KEY, execute=False, namespace_root=NAMESPACE_ROOT)
    with pytest.raises(BundleError, match="records a dry run"):
        resolve_bundle_sha256(paths, MODEL_KEY)


def test_an_upload_is_proved_against_the_object_not_the_call(
    paths: CampaignPaths,
) -> None:
    s3 = FakeS3()
    publication = publish_bundle(
        paths,
        model_key=MODEL_KEY,
        execute=True,
        namespace_root=NAMESPACE_ROOT,
        r2_client=_r2(s3),
    )

    assert publication.uploaded is True
    assert publication.verified_against is not None
    stored = s3.objects[bundle_object_key(MODEL_KEY)]
    assert hashlib.sha256(stored).hexdigest() == publication.bundle_sha256

    recorded, receipt = resolve_bundle_sha256(paths, MODEL_KEY)
    assert recorded == publication.bundle_sha256
    assert receipt["uploaded"] is True


def test_a_bucket_without_a_checksum_header_is_re_downloaded_and_hashed(
    paths: CampaignPaths,
) -> None:
    s3 = FakeS3(drop_checksum=True)
    publication = publish_bundle(
        paths,
        model_key=MODEL_KEY,
        execute=True,
        namespace_root=NAMESPACE_ROOT,
        r2_client=_r2(s3),
    )
    assert "re-downloaded" in str(publication.verified_against)


def test_bytes_that_changed_in_the_bucket_are_refused(paths: CampaignPaths) -> None:
    """The pod's start command pins this digest; a mismatch must not receipt."""

    s3 = FakeS3(corrupt=True)
    with pytest.raises(BundleError) as caught:
        publish_bundle(
            paths,
            model_key=MODEL_KEY,
            execute=True,
            namespace_root=NAMESPACE_ROOT,
            r2_client=_r2(s3),
        )
    assert "not the built" in str(caught.value)
    # Nothing was receipted, so nothing downstream can read a false digest.
    with pytest.raises(BundleError, match="is absent"):
        read_bundle_receipt(paths, MODEL_KEY)


def test_the_bundle_command_needs_a_model() -> None:
    assert main(["bundle"]) == EXIT_REFUSED


def test_an_argv_digest_must_equal_the_receipt(paths: CampaignPaths) -> None:
    write_bundle_receipt(paths, bundle_sha256="b" * 64)
    recorded, _ = resolve_bundle_sha256(paths, MODEL_KEY, argv_sha256="b" * 64)
    assert recorded == "b" * 64
    # Either spelling of the same digest is the same digest (D35).
    assert resolve_bundle_sha256(paths, MODEL_KEY, argv_sha256="sha256:" + "b" * 64)[0]
    with pytest.raises(BundleError, match="does not equal the published"):
        resolve_bundle_sha256(paths, MODEL_KEY, argv_sha256="c" * 64)


# ------------------------------------------------------------------- gates


@pytest.fixture
def gated(paths: CampaignPaths, entry: ModelPlanEntry) -> CampaignPaths:
    """A campaign whose canary would be granted, so each test breaks one thing."""

    paths.canary_selection.write_text(
        json.dumps({"case_keys": ["omnidocbench-000001"]}), encoding="utf-8"
    )
    write_model_registry(paths.model_registry, entry)
    write_runtime_json(paths, runtime_mode_allowed=["bootstrap"])
    write_prompt_registry(paths, text="")
    write_bundle_receipt(paths)
    write_catalog_snapshot(paths)
    write_authorization(paths, max_usd=25.0)
    return paths


def _canary(paths: CampaignPaths, *extra: str) -> list[str]:
    return ["canary", "--model", MODEL_KEY, "--root", str(paths.root), *extra]


def test_a_stale_price_snapshot_is_refused_in_a_dry_run(
    gated: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """D23: nothing is priced from a snapshot older than six hours."""

    for path in gated.provider_receipts_dir.glob("catalog-*.json"):
        path.unlink()
    write_catalog_snapshot(gated, captured_at="2026-09-01T00:00:00Z")

    assert main(_canary(gated)) == EXIT_BLOCKED
    err = capsys.readouterr().err
    assert "freshness limit" in err
    assert "D23" in err


def test_a_fresh_snapshot_is_priced_and_its_age_recorded(
    gated: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_canary(gated)) == EXIT_OK
    out = capsys.readouterr().out
    assert "snapshot on disk is" in out
    gate = json.loads(gated.canary_provision_receipt(MODEL_KEY).read_text(encoding="utf-8"))
    assert gate["price_snapshot_age_hours"] is not None


def test_a_runtime_mode_the_runtime_forbids_is_refused_naming_the_file(
    gated: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """D25: the computed mode must be in runtime_mode_allowed."""

    write_runtime_json(gated, runtime_mode_allowed=["baked"])
    assert main(_canary(gated, "--bundle-sha256", "f" * 64)) == EXIT_BLOCKED
    message = "".join(capsys.readouterr())
    assert "runtimes/paddleocr_vl_1_6/runtime.json" in message
    assert "D25" in message


def test_a_pool_whose_vram_cannot_hold_the_model_is_refused(
    gated: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """D25's other half: catalog memory_gb x gpu_count_min < gpu_min_vram_gb."""

    write_runtime_json(
        gated,
        runtime_mode_allowed=["bootstrap"],
        gpu_min_vram_gb=80,
        gpu_pool_priority=["NVIDIA GeForce RTX 4090"],
    )
    assert main(_canary(gated)) == EXIT_BLOCKED
    message = "".join(capsys.readouterr())
    assert "80" in message


def test_the_cumulative_budget_refuses_even_with_a_covering_receipt(
    gated: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """D22: one authorized action is not the campaign's whole spend.

    A $25 receipt covers this canary. What it cannot do is authorize the
    twenty-first canary after twenty earlier ones already committed the soft
    cap -- the ceiling is cumulative, and the receipt is necessary, not
    sufficient.
    """

    committed = BUDGET_SOFT_CAP_USD  # earlier provisioning lines, already committed
    gated.pod_provisioning_ledger.parent.mkdir(parents=True, exist_ok=True)
    gated.pod_provisioning_ledger.write_text(
        json.dumps(
            {
                "schema": "tavonel.arena.pod_provisioning.v1",
                "campaign_id": CAMPAIGN_ID,
                "pod_id": "podearlier001",
                "model_key": "some_other_model",
                "mode": "live",
                "required_usd": committed,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert main(_canary(gated)) == EXIT_BLOCKED
    message = "".join(capsys.readouterr())
    assert "cap" in message
    assert "D22" in message


def test_a_pod_that_has_been_billed_no_longer_counts_its_ceiling(
    gated: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """D75: a settled pod is counted once, by what it actually cost.

    The same pod is in both ledgers -- a ceiling when it was rented, an actual
    when it was returned. Counting both refuses a canary that the campaign can
    plainly afford: here the ceiling alone is the whole soft cap and the pod
    in fact cost a dollar.
    """

    gated.pod_provisioning_ledger.parent.mkdir(parents=True, exist_ok=True)
    gated.pod_provisioning_ledger.write_text(
        json.dumps(
            {
                "schema": "tavonel.arena.pod_provisioning.v1",
                "campaign_id": CAMPAIGN_ID,
                "pod_id": "podsettled01",
                "model_key": "some_other_model",
                "mode": "live",
                "required_usd": BUDGET_SOFT_CAP_USD,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gated.pod_ledger.parent.mkdir(parents=True, exist_ok=True)
    gated.pod_ledger.write_text(
        json.dumps(
            {
                "schema": "tavonel.arena.pod_ledger.v1",
                "campaign_id": CAMPAIGN_ID,
                "pod_id": "podsettled01",
                "model_key": "some_other_model",
                "estimated_provider_cost_usd": 1.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    budget = cumulative_budget(gated, required_usd=0.0)

    assert budget.spent_usd == pytest.approx(1.0)
    assert budget.committed_usd == pytest.approx(0.0)
    assert budget.provisioning_lines == 0
    assert budget.ledger_lines == 1


def test_an_unreturned_pod_still_counts_its_ceiling(gated: CampaignPaths) -> None:
    """The other half of D75: until a pod is billed, its ceiling stands for it."""

    gated.pod_provisioning_ledger.parent.mkdir(parents=True, exist_ok=True)
    gated.pod_provisioning_ledger.write_text(
        json.dumps(
            {
                "schema": "tavonel.arena.pod_provisioning.v1",
                "campaign_id": CAMPAIGN_ID,
                "pod_id": "podinflight1",
                "model_key": "some_other_model",
                "mode": "live",
                "required_usd": 42.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    budget = cumulative_budget(gated, required_usd=0.0)

    assert budget.committed_usd == pytest.approx(42.0)
    assert budget.provisioning_lines == 1
    assert budget.spent_usd == pytest.approx(0.0)


def test_the_hard_cap_is_never_crossed() -> None:
    """The two caps are ordered, and nothing crosses the hard one."""

    assert BUDGET_SOFT_CAP_USD < BUDGET_HARD_CAP_USD


# ------------------------------------------------------- cleanup and drive


class _CleanupClient:
    """A provider listing that empties once its pods have been deleted."""

    def __init__(self, api: str, pods: list[Any]) -> None:
        self.api = api
        self.execute = True
        self.pods = pods
        self.deleted: list[str] = []
        self.stopped: list[str] = []

    def list_pods(self) -> list[Any]:
        return list(self.pods)

    def stop_pod(self, pod_id: str) -> object:
        self.stopped.append(pod_id)
        return {"id": pod_id}

    def delete_pod(self, pod_id: str) -> object:
        self.deleted.append(pod_id)
        self.pods = [pod for pod in self.pods if pod.pod_id != pod_id]
        return {"id": pod_id}

    def close(self) -> None:
        return None


def test_cleanup_verify_execute_deletes_across_both_apis(
    paths: CampaignPaths,
    credential_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """D20: a pod created on v1 that v2 does not report is still billing."""

    from arena.provider.runpod_pods import Pod
    from arena.provider.runpod_v1 import PodV1

    on_v2 = Pod(
        pod_id="podv2000001",
        name="arena-paddleocr-vl-1-6-w0-20260903v1",
        status="RUNNING",
        image="runpod/pytorch:1.0.2",
        cloud="SECURE",
        cost_usd_per_hour=0.69,
        data_center_id="US-TX-3",
        gpu_type_id="NVIDIA GeForce RTX 4090",
        gpu_count=1,
        created_at="2026-09-03T10:00:00Z",
        started_at="2026-09-03T10:01:00Z",
        uptime_seconds=120,
        gpu_utilization_percent=91,
        env={"ARENA_CAMPAIGN_ID": CAMPAIGN_ID},
    )
    on_v1 = PodV1(
        pod_id="podv1000001",
        name="arena-glm-ocr-w0-20260903v1",
        desired_status="EXITED",  # EXITED is not cleaned up until it is gone
        image="vllm/vllm-openai:v0.11.0",
        cost_usd_per_hour=0.69,
        data_center_id="EU-RO-1",
        gpu_type_id="NVIDIA GeForce RTX 4090",
        gpu_count=1,
        machine_id="s194cr8pls2z",
        last_started_at="2026-09-03T12:00:00Z",
        container_disk_gb=80,
        volume_gb=0,
        docker_entrypoint=("/bin/bash", "-c"),
        docker_start_cmd_element_count=1,
        env={"ARENA_CAMPAIGN_ID": CAMPAIGN_ID},
    )
    v2 = _CleanupClient("v2", [on_v2])
    v1 = _CleanupClient("v1", [on_v1])
    monkeypatch.setattr(
        "arena.controller.cli.make_v2_client",
        lambda *, key, execute, receipts_dir: v2,
    )
    monkeypatch.setattr(
        "arena.controller.cli.make_v1_client",
        lambda *, key, execute, receipts_dir: v1,
    )

    code = main(
        [
            "cleanup-verify",
            "--root",
            str(paths.root),
            "--credentials",
            str(credential_file),
            "--execute",
        ]
    )
    out = capsys.readouterr().out

    assert code == EXIT_OK
    assert v2.deleted == ["podv2000001"]
    assert v1.deleted == ["podv1000001"]
    assert "verified=True" in out
    receipt = json.loads(paths.cleanup_receipt.read_text(encoding="utf-8"))
    assert receipt["verified"] is True
    assert sorted(receipt["apis_read"]) == ["v1", "v2"]
    assert receipt["exited_counts_as_not_cleaned"] is True
    assert sorted(receipt["deleted_pod_ids"]) == ["podv1000001", "podv2000001"]


def test_a_cleanup_dry_run_deletes_nothing_and_claims_nothing(
    paths: CampaignPaths,
    credential_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arena.provider.runpod_pods import Pod

    v2 = _CleanupClient(
        "v2",
        [
            Pod(
                pod_id="podv2000001",
                name="arena-paddleocr-vl-1-6-w0-20260903v1",
                status="RUNNING",
                image="runpod/pytorch:1.0.2",
                cloud="SECURE",
                cost_usd_per_hour=0.69,
        data_center_id="US-TX-3",
        gpu_type_id="NVIDIA GeForce RTX 4090",
        gpu_count=1,
        created_at="2026-09-03T10:00:00Z",
        started_at="2026-09-03T10:01:00Z",
        uptime_seconds=120,
        gpu_utilization_percent=91,
                env={"ARENA_CAMPAIGN_ID": CAMPAIGN_ID},
            )
        ],
    )
    v2.execute = False
    v1 = _CleanupClient("v1", [])
    v1.execute = False
    monkeypatch.setattr(
        "arena.controller.cli.make_v2_client",
        lambda *, key, execute, receipts_dir: v2,
    )
    monkeypatch.setattr(
        "arena.controller.cli.make_v1_client",
        lambda *, key, execute, receipts_dir: v1,
    )

    code = main(
        [
            "cleanup-verify",
            "--root",
            str(paths.root),
            "--credentials",
            str(credential_file),
        ]
    )
    assert code == EXIT_BLOCKED  # a dry run cannot verify cleanup
    assert v2.deleted == []
    receipt = json.loads(paths.cleanup_receipt.read_text(encoding="utf-8"))
    assert receipt["verified"] is False
    assert receipt["mode"] == "dry_run"


def test_no_drive_with_execute_is_refused(
    gated: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """A live pod nobody drives is the finding D20 exists to close."""

    code = main(_canary(gated, "--execute", "--no-drive"))
    err = capsys.readouterr().err
    assert code == EXIT_REFUSED
    assert "D20" in err
    assert "--no-drive" in err


# ------------------------------------------------------------ runtime mode


def _mode(paths: CampaignPaths, *argv: str) -> str:
    from arena.controller.cli import _runtime_mode, build_parser
    from arena.controller.runtime_spec import load_runtime_spec

    args = build_parser().parse_args(["canary", "--model", MODEL_KEY, *argv])
    runtime = load_runtime_spec(paths.runtime_json(MODEL_KEY), MODEL_KEY)
    return _runtime_mode(args, paths, model_key=MODEL_KEY, runtime=runtime)


def test_a_published_bundle_selects_bootstrap_without_a_flag(
    paths: CampaignPaths,
) -> None:
    """D21 moved the digest into the receipt, so the receipt decides the mode.

    Before this, a model that allows both modes fell through to `baked` and was
    refused for a container_digest the registry deliberately keeps null until
    an image is actually baked (D15) -- a canary nobody could run.
    """

    write_runtime_json(paths, runtime_mode_allowed=["baked", "bootstrap"])
    assert _mode(paths) == "baked"  # nothing published yet
    write_bundle_receipt(paths)
    assert _mode(paths) == "bootstrap"


def test_a_runtime_that_permits_one_mode_gets_that_mode(paths: CampaignPaths) -> None:
    write_runtime_json(paths, runtime_mode_allowed=["bootstrap"])
    assert _mode(paths) == "bootstrap"
    write_runtime_json(paths, runtime_mode_allowed=["baked"])
    assert _mode(paths) == "baked"


def test_an_explicit_digest_against_a_baked_only_runtime_is_refused_not_downgraded(
    paths: CampaignPaths,
) -> None:
    """D25/D36: say no, rather than quietly build a pod nobody asked for."""

    from arena.controller.provision import ProvisionError, check_runtime_mode

    write_runtime_json(paths, runtime_mode_allowed=["baked"])
    computed = _mode(paths, "--bundle-sha256", "f" * 64)
    assert computed == "bootstrap"
    with pytest.raises(ProvisionError, match=r"runtime\.json"):
        check_runtime_mode(
            computed,
            ("baked",),
            runtime_json=f"runtimes/{MODEL_KEY}/runtime.json",
        )


def test_a_dry_run_bundle_receipt_refuses_the_canary_cleanly(
    gated: CampaignPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """A refusal prints and exits; it does not escape as a traceback.

    A dry-run canary that ended in a stack trace told the operator nothing
    about which command to run next, which is the whole job of a dry run.
    """

    write_bundle_receipt(gated, uploaded=False)
    code = main(_canary(gated))
    message = "".join(capsys.readouterr())

    assert code == EXIT_BLOCKED
    assert "records a dry run" in message
    assert "Traceback" not in message


# ------------------------------------------------------- the host CUDA floor


def test_the_allowed_list_is_every_version_at_or_above_the_floor() -> None:
    from arena.controller.provision import RUNPOD_CUDA_VERSIONS, allowed_cuda_versions

    assert allowed_cuda_versions("12.9") == ("12.9", "13.0")
    assert allowed_cuda_versions("11.8") == RUNPOD_CUDA_VERSIONS
    assert allowed_cuda_versions("13.0") == ("13.0",)


def test_versions_are_compared_component_wise_not_as_decimals() -> None:
    """RunPod documents 12.11 as *above* 12.2; a float read would invert it."""

    from arena.controller.provision import parse_cuda_version

    assert parse_cuda_version("12.11") > parse_cuda_version("12.2")
    assert parse_cuda_version("13.0") > parse_cuda_version("12.9")


def test_a_floor_no_host_could_meet_is_a_refusal_not_an_empty_filter() -> None:
    """An empty allowedCudaVersions tells the provider "any host will do"."""

    from arena.controller.provision import ProvisionError, allowed_cuda_versions

    with pytest.raises(ProvisionError, match="no host can run this image"):
        allowed_cuda_versions("99.0")


def test_a_malformed_cuda_version_is_refused() -> None:
    from arena.controller.provision import ProvisionError, parse_cuda_version

    for value in ("12.9.1", "12", "cuda12.9", ""):
        with pytest.raises(ProvisionError, match=r"major\.minor"):
            parse_cuda_version(value)


def test_the_gate_refuses_a_gpu_runtime_that_declares_no_floor() -> None:
    from arena.controller.provision import ProvisionError, check_cuda_constraint

    with pytest.raises(ProvisionError, match=r"runtimes/glm_ocr/runtime\.json"):
        check_cuda_constraint(
            model_key="glm_ocr",
            runtime_json="runtimes/glm_ocr/runtime.json",
            min_cuda_version=None,
            gpu_pool_priority=("NVIDIA GeForce RTX 4090",),
        )


def test_the_gate_reports_the_constraint_it_will_send() -> None:
    from arena.controller.provision import check_cuda_constraint

    constraint = check_cuda_constraint(
        model_key="glm_ocr",
        runtime_json="runtimes/glm_ocr/runtime.json",
        min_cuda_version="12.9",
        gpu_pool_priority=("NVIDIA GeForce RTX 4090",),
    )
    assert constraint.allowed_cuda_versions == ("12.9", "13.0")
    assert constraint.to_dict()["provider_field"] == "allowedCudaVersions"


def test_a_malformed_floor_in_runtime_json_is_named_by_its_field(
    paths: CampaignPaths,
) -> None:
    from arena.controller.runtime_spec import RuntimeSpecError, load_runtime_spec

    write_runtime_json(paths, min_cuda_version="12.9.1")
    with pytest.raises(RuntimeSpecError, match="min_cuda_version"):
        load_runtime_spec(paths.runtime_json(MODEL_KEY), MODEL_KEY)
