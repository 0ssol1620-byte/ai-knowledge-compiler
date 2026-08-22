from __future__ import annotations

from pathlib import Path

from infra.security.verify_r2_production_gate import (
    CredentialBundle,
    CredentialProfile,
    _cors_assessment,
    _lifecycle_assessment,
    _profile_receipt,
    assess_gate,
    parse_credentials_file,
)


def test_parse_credentials_file_extracts_only_r2_profiles(tmp_path: Path) -> None:
    path = tmp_path / "keys.txt"
    path.write_text(
        """Github: ignored
Cloudflare R2
Account API Token: profile
Token value: token-a
Access Key ID: access-a
Secret Access Key: secret-a
Use jurisdiction-specific endpoints for S3 clients:
https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com
User API Tokens: profile
Token value: token-b
Access Key ID: access-b
Secret Access Key: secret-b
Use jurisdiction-specific endpoints for S3 clients:
https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com
""",
        encoding="utf-8",
    )

    bundle = parse_credentials_file(path)

    assert bundle.account_id == "0123456789abcdef0123456789abcdef"
    assert [profile.name for profile in bundle.profiles] == [
        "account_api_token",
        "user_api_token",
    ]
    assert bundle.profiles[0].fingerprint != bundle.profiles[1].fingerprint


def test_assessments_reject_wildcard_and_detect_abort_rule() -> None:
    cors = _cors_assessment(
        {
            "rules": [
                {
                    "allowed": {"origins": ["*"], "methods": ["PUT"]},
                    "exposeHeaders": ["ETag"],
                }
            ]
        }
    )
    lifecycle = _lifecycle_assessment(
        {
            "rules": [
                {
                    "enabled": True,
                    "abortMultipartUploadsTransition": {
                        "condition": {"type": "Age", "maxAge": 86400}
                    },
                }
            ]
        }
    )

    assert cors == {
        "rule_count": 1,
        "origin_count": 1,
        "wildcard_origin": True,
        "methods": ["PUT"],
        "etag_exposed": True,
    }
    assert lifecycle["abort_incomplete_multipart"] is True


def test_gate_is_fail_closed_without_claiming_prefix_scope() -> None:
    profiles = [
        {
            "token_verify": {"success": True},
            "readable_bucket_count": 0,
            "buckets": [
                {
                    "cors": {
                        "rule_count": 1,
                        "wildcard_origin": False,
                        "etag_exposed": True,
                    },
                    "lifecycle": {"abort_incomplete_multipart": True},
                }
            ],
        }
    ]

    result = assess_gate(profiles)

    assert result == {
        "status": "PARTIAL",
        "findings": ["prefix_write_scope_requires_provider_policy_receipt"],
        "mutation_performed": False,
    }


def test_account_owned_token_uses_account_verify_endpoint(monkeypatch) -> None:
    observed: list[str] = []

    def fake_get(_session, *, token: str, path: str):
        del token
        observed.append(path)
        if path.endswith("/r2/buckets"):
            return {"http_status": 200, "success": True, "error_codes": [], "result": []}
        return {"http_status": 200, "success": True, "error_codes": [], "result": {}}

    class FakeS3:
        @staticmethod
        def list_buckets():
            return {"Buckets": []}

    monkeypatch.setattr(
        "infra.security.verify_r2_production_gate._cloudflare_get",
        fake_get,
    )
    monkeypatch.setattr(
        "infra.security.verify_r2_production_gate.boto3.client",
        lambda *args, **kwargs: FakeS3(),
    )
    bundle = CredentialBundle(
        account_id="0123456789abcdef0123456789abcdef",
        endpoint_url=(
            "https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com"
        ),
        profiles=(),
    )
    profile = CredentialProfile("account_api_token", "token", "access", "secret")

    receipt = _profile_receipt(bundle, profile, session=object())

    assert receipt["token_verify"]["success"] is True
    assert observed[0] == "accounts/0123456789abcdef0123456789abcdef/tokens/verify"
