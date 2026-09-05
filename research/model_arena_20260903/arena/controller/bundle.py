"""``python -m arena.controller bundle --model <k> [--execute]`` (D21).

The canary's start command pins a bundle sha256 (11.3(1)), so the question
"which bytes is that digest?" has to have exactly one answer on disk. This
module is that answer:

    build + verify  ->  upload to R2  ->  HEAD the object and compare digests
                    ->  receipts/bundles/<model_key>.json

``canary`` reads the sha256 from that receipt. ``--bundle-sha256`` on the argv
is accepted only when it *equals* the receipt, so an operator cannot hand-type
a digest for bytes that are not in the bucket.

Two properties are load bearing:

- **The comparison is against the object, not against the upload call.** R2
  returns a SHA256 checksum for an object stored with ``ChecksumAlgorithm``;
  when the header is absent the object is re-downloaded and hashed. A
  ``put_object`` that returned 200 is not evidence that the bytes in the
  bucket are the bytes we built.
- **Bundle URLs never reach a receipt.** D21 reduces them to ``bucket/key``.
  The presigned URL exists for exactly as long as one pod needs it and is
  never written down.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from arena.constants import CAMPAIGN_ID
from arena.controller.paths import CampaignPaths
from arena.core.receipts import ReceiptError, validate
from arena.provider.r2 import BUCKET_NAME, R2Client, R2Error, UploadResult
from arena.provider.safety import read_json, sha256_file, utc_now_iso, write_json_atomic

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mypy_boto3_s3.client import S3Client

__all__ = [
    "BUNDLE_RECEIPT_SCHEMA",
    "BundleError",
    "BundlePublication",
    "build_and_verify",
    "bundle_object_key",
    "publish_bundle",
    "read_bundle_receipt",
    "resolve_bundle_sha256",
]

BUNDLE_RECEIPT_SCHEMA: Final = "tavonel.arena.bundle-publish.v1"


class BundleError(RuntimeError):
    """The bundle could not be built, uploaded, or proven to be in the bucket."""


def bundle_object_key(model_key: str, *, campaign_id: str = CAMPAIGN_ID) -> str:
    """``bundles/<campaign>/<model_key>/arena-bundle.tar.gz`` (D21)."""

    return f"bundles/{campaign_id}/{model_key}/arena-bundle.tar.gz"


@dataclass(frozen=True, slots=True)
class BundlePublication:
    model_key: str
    bundle_path: Path
    bundle_sha256: str
    size_bytes: int
    file_count: int
    manifest_sha256: str
    r2_bucket: str
    r2_key: str
    mode: str
    uploaded: bool
    verified_against: str | None
    receipt_path: Path | None = None

    @property
    def bundle_reference(self) -> str:
        """D21: bundle URLs in receipts are reduced to ``bucket/key``."""

        return f"{self.r2_bucket}/{self.r2_key}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": BUNDLE_RECEIPT_SCHEMA,
            "campaign_id": CAMPAIGN_ID,
            "model_key": self.model_key,
            "bundle_sha256": self.bundle_sha256,
            "bundle_size_bytes": self.size_bytes,
            "bundle_file_count": self.file_count,
            "bundle_manifest_sha256": self.manifest_sha256,
            "r2_bucket": self.r2_bucket,
            "r2_key": self.r2_key,
            "bundle_reference": self.bundle_reference,
            "mode": self.mode,
            "uploaded": self.uploaded,
            "object_digest_verified_against": self.verified_against,
            "uploaded_at": utc_now_iso(),
        }


def build_and_verify(model_key: str, out_path: Path, *, namespace_root: Path) -> tuple[str, int]:
    """Build the bundle through lane B2 and re-read it. Returns (sha256, files).

    The build lives in ``arena.worker.bundle`` (lane B2 owns it). This lane
    calls it and refuses to continue on a verification problem rather than
    building an archive of its own -- a bundle this lane invented would carry
    a worker nobody reviewed.
    """

    try:
        from arena.worker import bundle as worker_bundle
    except ImportError as exc:  # pragma: no cover - lane B2 owns the module
        raise BundleError(
            "arena.worker.bundle is not importable; the bundle is built by lane B2 "
            "and is never improvised here"
        ) from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    digest = worker_bundle.build_bundle(model_key, out_path, namespace_root=namespace_root)
    verification = worker_bundle.verify_bundle(out_path)
    if not verification.ok:
        raise BundleError(
            f"bundle for {model_key} does not verify: " + "; ".join(verification.problems)
        )
    if digest != sha256_file(out_path):
        raise BundleError(
            f"bundle for {model_key} hashes to {sha256_file(out_path)} on re-read, not the "
            f"{digest} the builder reported"
        )
    return digest, verification.file_count


def _manifest_sha256(model_key: str, tar_path: Path) -> str:
    from arena.worker import bundle as worker_bundle

    manifest: Mapping[str, Any] = worker_bundle.read_bundle_manifest(tar_path)
    import json

    payload = json.dumps(dict(manifest), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def publish_bundle(
    paths: CampaignPaths,
    *,
    model_key: str,
    execute: bool,
    credential_path: Path | None = None,
    namespace_root: Path | None = None,
    out_path: Path | None = None,
    r2_client: R2Client | None = None,
    s3_client: S3Client | None = None,
) -> BundlePublication:
    """Build, verify, upload, prove and receipt one model's bundle (D21)."""

    root = namespace_root or paths.root
    target = out_path or (paths.root / "bundles" / model_key / "arena-bundle.tar.gz")
    built, file_count = build_and_verify(model_key, target, namespace_root=root)
    # D35: the receipt stores bare 64-hex, because that is the spelling the
    # on-pod `sha256sum -c` line consumes. Callers that want an image digest
    # prepend `sha256:` themselves; nothing compares the two spellings raw.
    digest = _bare(built)
    manifest_sha = _manifest_sha256(model_key, target)
    key = bundle_object_key(model_key)
    size = target.stat().st_size

    if not execute:
        publication = BundlePublication(
            model_key=model_key,
            bundle_path=target,
            bundle_sha256=digest,
            size_bytes=size,
            file_count=file_count,
            manifest_sha256=manifest_sha,
            r2_bucket=BUCKET_NAME,
            r2_key=key,
            mode="dry_run",
            uploaded=False,
            verified_against=None,
        )
        return _write_receipt(paths, publication)

    client = r2_client
    if client is None:
        from arena.provider.secrets import r2_credentials

        client = R2Client(
            r2_credentials(block="account", path=credential_path),
            bucket=BUCKET_NAME,
            execute=True,
            client=s3_client,
        )
    result = client.put_file(target, key=key)
    if not isinstance(result, UploadResult):  # pragma: no cover - execute guarded above
        raise BundleError("the R2 client answered a dry-run receipt while executing")
    if _bare(result.sha256) != digest:
        raise BundleError(
            f"upload reported {result.sha256} for {key}, not the built {digest}"
        )

    stored, source = _object_digest(client, key)
    if _bare(stored) != digest:
        raise BundleError(
            f"the object at {BUCKET_NAME}/{key} hashes to {stored} ({source}), not the built "
            f"{digest}. Refusing to receipt a bundle whose bytes in the bucket are not the "
            "bytes a pod would be told to trust."
        )

    publication = BundlePublication(
        model_key=model_key,
        bundle_path=target,
        bundle_sha256=digest,
        size_bytes=size,
        file_count=file_count,
        manifest_sha256=manifest_sha,
        r2_bucket=BUCKET_NAME,
        r2_key=key,
        mode="live",
        uploaded=True,
        verified_against=source,
    )
    return _write_receipt(paths, publication)


def _object_digest(client: R2Client, key: str) -> tuple[str, str]:
    """HEAD the object for its SHA256 checksum; hash the bytes when absent."""

    try:
        head = client.head_object(key)
    except R2Error as exc:
        raise BundleError(f"cannot read back {key} from the bucket: {exc}") from exc
    checksum = head.get("checksum_sha256")
    if isinstance(checksum, str) and checksum:
        return checksum, "HEAD ChecksumSHA256 header"
    downloaded = client.object_sha256(key)
    return downloaded, "re-downloaded object bytes (no checksum header)"


def _write_receipt(paths: CampaignPaths, publication: BundlePublication) -> BundlePublication:
    path = paths.bundle_receipt(publication.model_key)
    document = publication.to_dict()
    # D21/D26: the receipt is lane A1's `BundlePublishReceipt`, validated
    # before a byte reaches disk. A canary derives its whole runtime identity
    # from `bundle_sha256`, so a receipt that does not satisfy the contract
    # must not exist to be read later.
    try:
        validate(document, "bundle-publish")
    except ReceiptError as exc:
        raise BundleError(
            f"the bundle receipt for {publication.model_key} does not satisfy "
            f"bundle-publish.schema.json and was not written: {exc}"
        ) from exc
    write_json_atomic(path, document, context="bundle publish receipt")
    return BundlePublication(
        model_key=publication.model_key,
        bundle_path=publication.bundle_path,
        bundle_sha256=publication.bundle_sha256,
        size_bytes=publication.size_bytes,
        file_count=publication.file_count,
        manifest_sha256=publication.manifest_sha256,
        r2_bucket=publication.r2_bucket,
        r2_key=publication.r2_key,
        mode=publication.mode,
        uploaded=publication.uploaded,
        verified_against=publication.verified_against,
        receipt_path=path,
    )


def read_bundle_receipt(paths: CampaignPaths, model_key: str) -> Mapping[str, Any]:
    """The D21 receipt, or a refusal naming the command that writes it."""

    path = paths.bundle_receipt(model_key)
    if not path.is_file():
        raise BundleError(
            f"receipts/bundles/{model_key}.json is absent; run "
            f"`python -m arena.controller bundle --model {model_key} --execute` first (D21)"
        )
    document = read_json(path)
    if not isinstance(document, Mapping):
        raise BundleError(f"{path.name} is not a JSON object")
    if document.get("schema") != BUNDLE_RECEIPT_SCHEMA:
        raise BundleError(
            f"{path.name} declares schema {document.get('schema')!r}, not "
            f"{BUNDLE_RECEIPT_SCHEMA!r}"
        )
    return document


def resolve_bundle_sha256(
    paths: CampaignPaths, model_key: str, *, argv_sha256: str | None = None
) -> tuple[str, Mapping[str, Any]]:
    """The bundle digest a canary may pin (D21).

    The receipt is the source. ``argv_sha256`` is accepted only when it equals
    the receipt: an operator who wants a different bundle publishes it, rather
    than pointing a pod at a digest nothing on disk vouches for.
    """

    receipt = read_bundle_receipt(paths, model_key)
    recorded = receipt.get("bundle_sha256")
    if not isinstance(recorded, str) or not recorded:
        raise BundleError(
            f"receipts/bundles/{model_key}.json carries no bundle_sha256"
        )
    if not receipt.get("uploaded"):
        raise BundleError(
            f"receipts/bundles/{model_key}.json records a dry run; the bundle is not in the "
            "bucket, so a pod pointed at it would fail its sha256 check after paying for a GPU"
        )
    if argv_sha256 and _bare(argv_sha256) != _bare(recorded):
        raise BundleError(
            f"--bundle-sha256 {argv_sha256} does not equal the published "
            f"{recorded} in receipts/bundles/{model_key}.json (D21)"
        )
    return recorded, receipt


def _bare(value: str) -> str:
    return value[len("sha256:") :] if value.startswith("sha256:") else value
