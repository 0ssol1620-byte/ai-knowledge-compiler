"""Produce a secret-free, read-only Cloudflare R2 production evidence receipt.

The verifier intentionally performs no PUT, POST, PATCH, or DELETE requests. It
can therefore show the currently observable bucket, CORS, lifecycle, and S3
read surface without changing production state. Credential values and object
keys never enter the receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import boto3
import requests
from botocore.config import Config
from botocore.exceptions import ClientError

_URL_PATTERN = re.compile(r"https://[^\s]+")
_PROFILE_HEADERS = {
    "account api token": "account_api_token",
    "user api tokens": "user_api_token",
}


@dataclass(frozen=True)
class CredentialProfile:
    name: str
    token: str
    access_key_id: str
    secret_access_key: str

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.access_key_id.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class CredentialBundle:
    account_id: str
    endpoint_url: str
    profiles: tuple[CredentialProfile, ...]


def parse_credentials_file(path: Path) -> CredentialBundle:
    """Parse the user-managed credential note without returning unrelated keys."""

    text = path.read_text(encoding="utf-8-sig")
    endpoint_matches = _URL_PATTERN.findall(text)
    if not endpoint_matches:
        raise ValueError("R2 endpoint URL is missing")
    endpoint_url = endpoint_matches[0].rstrip(".,)")
    host = urlsplit(endpoint_url).hostname or ""
    suffix = ".r2.cloudflarestorage.com"
    if not host.endswith(suffix):
        raise ValueError("R2 endpoint host is invalid")
    account_id = host.removesuffix(suffix)
    if not re.fullmatch(r"[a-f0-9]{32}", account_id):
        raise ValueError("R2 account id is invalid")

    values: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        label, separator, value = line.partition(":")
        if not separator:
            label, separator, value = line.partition("=")
        normalized = label.strip().casefold()
        if normalized in _PROFILE_HEADERS:
            current = _PROFILE_HEADERS[normalized]
            values.setdefault(current, {})
            continue
        if current is None or not separator:
            continue
        key = normalized.replace(" ", "_")
        if key in {"token_value", "access_key_id", "secret_access_key"}:
            values[current][key] = value.strip()

    profiles: list[CredentialProfile] = []
    for name in ("account_api_token", "user_api_token"):
        row = values.get(name, {})
        missing = {
            key
            for key in ("token_value", "access_key_id", "secret_access_key")
            if not row.get(key)
        }
        if missing:
            raise ValueError(f"R2 credential profile {name} is incomplete: {sorted(missing)}")
        profiles.append(
            CredentialProfile(
                name=name,
                token=row["token_value"],
                access_key_id=row["access_key_id"],
                secret_access_key=row["secret_access_key"],
            )
        )
    return CredentialBundle(
        account_id=account_id,
        endpoint_url=endpoint_url,
        profiles=tuple(profiles),
    )


def _error_code(error: Exception) -> str:
    if isinstance(error, ClientError):
        return str(error.response.get("Error", {}).get("Code", "ClientError"))
    return type(error).__name__


def _cloudflare_get(
    session: requests.Session,
    *,
    token: str,
    path: str,
) -> dict[str, Any]:
    response = session.get(
        f"https://api.cloudflare.com/client/v4/{path.lstrip('/')}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    try:
        payload = response.json()
    except requests.JSONDecodeError:
        payload = {}
    errors = payload.get("errors", []) if isinstance(payload, dict) else []
    error_codes = sorted(
        {
            str(item.get("code", "unknown"))
            for item in errors
            if isinstance(item, dict)
        }
    )
    return {
        "http_status": response.status_code,
        "success": bool(response.ok and isinstance(payload, dict) and payload.get("success")),
        "error_codes": error_codes,
        "result": payload.get("result") if isinstance(payload, dict) else None,
    }


def _cors_assessment(result: Any) -> dict[str, Any]:
    rules = result.get("rules", []) if isinstance(result, dict) else []
    wildcard_origin = False
    exposes_etag = False
    methods: set[str] = set()
    origin_count = 0
    for rule in rules if isinstance(rules, list) else []:
        if not isinstance(rule, dict):
            continue
        allowed = rule.get("allowed", {})
        origins = allowed.get("origins", []) if isinstance(allowed, dict) else []
        rule_methods = allowed.get("methods", []) if isinstance(allowed, dict) else []
        exposed = rule.get("exposeHeaders", [])
        wildcard_origin = wildcard_origin or "*" in origins
        origin_count += len(origins) if isinstance(origins, list) else 0
        if isinstance(rule_methods, list):
            methods.update(str(method).upper() for method in rule_methods)
        if isinstance(exposed, list):
            exposes_etag = exposes_etag or any(
                str(header).casefold() == "etag" for header in exposed
            )
    return {
        "rule_count": len(rules) if isinstance(rules, list) else 0,
        "origin_count": origin_count,
        "wildcard_origin": wildcard_origin,
        "methods": sorted(methods),
        "etag_exposed": exposes_etag,
    }


def _lifecycle_assessment(result: Any) -> dict[str, Any]:
    rules = result.get("rules", []) if isinstance(result, dict) else []
    enabled_count = 0
    abort_multipart = False
    for rule in rules if isinstance(rules, list) else []:
        if not isinstance(rule, dict) or not rule.get("enabled"):
            continue
        enabled_count += 1
        abort_multipart = abort_multipart or bool(rule.get("abortMultipartUploadsTransition"))
    return {
        "enabled_rule_count": enabled_count,
        "abort_incomplete_multipart": abort_multipart,
    }


def _profile_receipt(
    bundle: CredentialBundle,
    profile: CredentialProfile,
    *,
    session: requests.Session,
) -> dict[str, Any]:
    token_verify_path = (
        f"accounts/{bundle.account_id}/tokens/verify"
        if profile.name == "account_api_token"
        else "user/tokens/verify"
    )
    token_verify = _cloudflare_get(session, token=profile.token, path=token_verify_path)
    token_verify.pop("result", None)
    bucket_api = _cloudflare_get(
        session,
        token=profile.token,
        path=f"accounts/{bundle.account_id}/r2/buckets",
    )
    bucket_rows = []
    result = bucket_api.pop("result", None)
    if isinstance(result, dict):
        candidate_rows = result.get("buckets", [])
    else:
        candidate_rows = result if isinstance(result, list) else []
    if isinstance(candidate_rows, list):
        bucket_rows = [row for row in candidate_rows if isinstance(row, dict)]
    bucket_names = sorted(
        str(row["name"])
        for row in bucket_rows
        if isinstance(row.get("name"), str)
    )

    s3 = boto3.client(
        "s3",
        endpoint_url=bundle.endpoint_url,
        region_name="auto",
        aws_access_key_id=profile.access_key_id,
        aws_secret_access_key=profile.secret_access_key,
        config=Config(
            signature_version="s3v4",
            connect_timeout=10,
            read_timeout=20,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )
    try:
        listed = s3.list_buckets().get("Buckets", [])
        s3_names = sorted(
            str(row["Name"])
            for row in listed
            if isinstance(row, dict) and isinstance(row.get("Name"), str)
        )
        s3_list = {"allowed": True, "error_code": None, "bucket_names": s3_names}
    except Exception as error:
        s3_names = []
        s3_list = {"allowed": False, "error_code": _error_code(error), "bucket_names": []}

    observed_names = sorted(set(bucket_names) | set(s3_names))
    buckets: list[dict[str, Any]] = []
    for name in observed_names:
        cors_api = _cloudflare_get(
            session,
            token=profile.token,
            path=f"accounts/{bundle.account_id}/r2/buckets/{name}/cors",
        )
        cors_result = cors_api.pop("result", None)
        lifecycle_api = _cloudflare_get(
            session,
            token=profile.token,
            path=f"accounts/{bundle.account_id}/r2/buckets/{name}/lifecycle",
        )
        lifecycle_result = lifecycle_api.pop("result", None)
        try:
            s3.list_objects_v2(Bucket=name, MaxKeys=1)
            object_list = {"allowed": True, "error_code": None}
        except Exception as error:
            object_list = {"allowed": False, "error_code": _error_code(error)}
        try:
            uploads = s3.list_multipart_uploads(Bucket=name, MaxUploads=1)
            incomplete = len(uploads.get("Uploads", []))
            multipart_list = {
                "allowed": True,
                "error_code": None,
                "incomplete_uploads_observed_at_least": incomplete,
            }
        except Exception as error:
            multipart_list = {
                "allowed": False,
                "error_code": _error_code(error),
                "incomplete_uploads_observed_at_least": None,
            }
        buckets.append(
            {
                "name": name,
                "cors_api": cors_api,
                "cors": _cors_assessment(cors_result),
                "lifecycle_api": lifecycle_api,
                "lifecycle": _lifecycle_assessment(lifecycle_result),
                "s3_object_list": object_list,
                "s3_multipart_list": multipart_list,
            }
        )

    readable_buckets = [
        bucket["name"] for bucket in buckets if bucket["s3_object_list"]["allowed"]
    ]
    return {
        "profile": profile.name,
        "access_key_fingerprint": profile.fingerprint,
        "token_verify": token_verify,
        "bucket_api": {**bucket_api, "bucket_names": bucket_names},
        "s3_list_buckets": s3_list,
        "readable_bucket_count": len(readable_buckets),
        "buckets": buckets,
    }


def assess_gate(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = [bucket for profile in profiles for bucket in profile.get("buckets", [])]
    findings: list[str] = []
    if not buckets:
        findings.append("no_bucket_configuration_was_observable")
    if any(bucket["cors"]["wildcard_origin"] for bucket in buckets):
        findings.append("wildcard_cors_origin")
    if any(
        bucket["cors"]["rule_count"] > 0 and not bucket["cors"]["etag_exposed"]
        for bucket in buckets
    ):
        findings.append("cors_etag_not_exposed")
    if buckets and not any(
        bucket["lifecycle"]["abort_incomplete_multipart"] for bucket in buckets
    ):
        findings.append("no_observed_abort_incomplete_multipart_rule")
    if any(profile.get("readable_bucket_count", 0) > 1 for profile in profiles):
        findings.append("credential_can_list_objects_across_multiple_buckets")
    if any(not profile["token_verify"]["success"] for profile in profiles):
        findings.append("api_token_verification_failed")
    if findings:
        status = "FAIL" if "wildcard_cors_origin" in findings else "PARTIAL"
    else:
        # Prefix-level write restrictions cannot be proven by a read-only probe.
        status = "PARTIAL"
        findings.append("prefix_write_scope_requires_provider_policy_receipt")
    return {"status": status, "findings": findings, "mutation_performed": False}


def build_receipt(bundle: CredentialBundle) -> dict[str, Any]:
    with requests.Session() as session:
        profiles = [
            _profile_receipt(bundle, profile, session=session) for profile in bundle.profiles
        ]
    return {
        "schema": "folynta.r2-production-gate-receipt.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "account_id": bundle.account_id,
        "endpoint_host": urlsplit(bundle.endpoint_url).hostname,
        "read_only": True,
        "profiles": profiles,
        "gate": assess_gate(profiles),
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    receipt = build_receipt(parse_credentials_file(args.credentials_file))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "gate": receipt["gate"],
                "profile_count": len(receipt["profiles"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
