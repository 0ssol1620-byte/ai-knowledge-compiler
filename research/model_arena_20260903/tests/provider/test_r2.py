"""R2 transport: read-only preflight, gated writes, credential hygiene."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from arena.provider.r2 import BUCKET_NAME, R2Client, R2Error, _classify_bucket_error
from arena.provider.secrets import r2_credentials
from tests.provider.conftest import FAKE_R2_ACCESS, FAKE_R2_SECRET


class FakeS3:
    """Stands in for a boto3 S3 client. Records calls, raises what it is told."""

    def __init__(self, head_error: Exception | None = None) -> None:
        self.head_error = head_error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def head_bucket(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("head_bucket", kwargs))
        if self.head_error is not None:
            raise self.head_error
        return {}

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("put_object", kwargs))
        return {}

    def create_bucket(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_bucket", kwargs))
        return {}

    def generate_presigned_url(self, operation: str, **kwargs: Any) -> str:
        self.calls.append((f"presign:{operation}", kwargs))
        return "https://fake.r2.example/object?X-Amz-Signature=aaaabbbbccccdddd"


class BotoLikeError(Exception):
    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}


@pytest.fixture
def client(credential_file: Path) -> R2Client:
    return R2Client(r2_credentials(path=credential_file), execute=False)


def test_dry_run_preflight_touches_nothing(client: R2Client) -> None:
    receipt = client.preflight_access()
    assert receipt.mode == "dry_run"
    assert receipt.detail["bucket_state"] is None
    assert receipt.bucket == BUCKET_NAME


def test_live_preflight_reports_exists(credential_file: Path) -> None:
    fake = FakeS3()
    live = R2Client(r2_credentials(path=credential_file), execute=True, client=fake)
    receipt = live.preflight_access()
    assert receipt.detail["bucket_state"] == "exists"
    assert fake.calls == [("head_bucket", {"Bucket": BUCKET_NAME})]


@pytest.mark.parametrize(
    ("code", "status", "expected"),
    [
        ("404", 404, "missing"),
        ("NoSuchBucket", 404, "missing"),
        ("AccessDenied", 403, "forbidden"),
        ("InvalidAccessKeyId", 401, "forbidden"),
        ("EndpointConnectionError", 0, "unreachable"),
    ],
)
def test_bucket_error_classification(code: str, status: int, expected: str) -> None:
    state, reported = _classify_bucket_error(BotoLikeError(code, status))
    assert state == expected
    assert reported == code


def test_live_preflight_never_raises_on_a_missing_bucket(credential_file: Path) -> None:
    fake = FakeS3(head_error=BotoLikeError("404", 404))
    live = R2Client(r2_credentials(path=credential_file), execute=True, client=fake)
    receipt = live.preflight_access()
    assert receipt.detail["bucket_state"] == "missing"
    assert receipt.detail["error_code"] == "404"


def test_put_file_is_a_dry_run_without_execute(client: R2Client, tmp_path: Path) -> None:
    payload = tmp_path / "bundle.tgz"
    payload.write_bytes(b"fake bundle bytes")
    result = client.put_file(payload)
    assert not hasattr(result, "size_bytes")  # a receipt, not an UploadResult


def test_put_file_uploads_and_hashes_when_executing(credential_file: Path, tmp_path: Path) -> None:
    payload = tmp_path / "bundle.tgz"
    payload.write_bytes(b"fake bundle bytes")
    fake = FakeS3()
    live = R2Client(r2_credentials(path=credential_file), execute=True, client=fake)
    result = live.put_file(payload)
    assert hasattr(result, "sha256")
    assert result.sha256.startswith("sha256:")  # type: ignore[union-attr]
    assert fake.calls[0][0] == "put_object"


def test_presign_is_refused_in_a_dry_run(client: R2Client) -> None:
    with pytest.raises(R2Error, match="requires execute"):
        client.presign_get("bundles/x/bundle.tgz", 3600)


def test_presign_expiry_is_bounded(credential_file: Path) -> None:
    live = R2Client(r2_credentials(path=credential_file), execute=True, client=FakeS3())
    with pytest.raises(R2Error, match="between 60 seconds"):
        live.presign_get("key", 10)
    with pytest.raises(R2Error, match="between 60 seconds"):
        live.presign_get("key", 10**7)


def test_presigned_url_never_reaches_a_receipt(credential_file: Path) -> None:
    live = R2Client(r2_credentials(path=credential_file), execute=True, client=FakeS3())
    url = live.presign_get("bundles/x/bundle.tgz", 3600)
    assert "X-Amz-Signature" in url
    for receipt in live.receipts:
        assert "X-Amz-Signature" not in str(receipt.to_dict())
        assert receipt.detail.get("url") is None


def test_create_bucket_needs_execute_and_an_explicit_confirmation(
    credential_file: Path,
) -> None:
    fake = FakeS3()
    dry = R2Client(r2_credentials(path=credential_file), execute=False, client=fake)
    receipt = dry.create_bucket()
    assert receipt.mode == "dry_run"
    assert fake.calls == []

    live = R2Client(r2_credentials(path=credential_file), execute=True, client=fake)
    with pytest.raises(R2Error, match="confirm=True"):
        live.create_bucket()
    assert fake.calls == []


def test_receipts_carry_no_credential(credential_file: Path) -> None:
    live = R2Client(r2_credentials(path=credential_file), execute=True, client=FakeS3())
    live.preflight_access()
    for receipt in live.receipts:
        rendered = str(receipt.to_dict())
        assert FAKE_R2_ACCESS not in rendered
        assert FAKE_R2_SECRET not in rendered
        assert receipt.to_dict()["credentials_withheld"] is True
