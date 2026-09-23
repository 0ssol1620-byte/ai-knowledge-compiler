"""Limit classification, environment scrubbing/preflight, pricing and selection."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from arena.core import ids as core_ids
from arena.opus import env as opus_env
from arena.opus.command import OpusCommandConfig
from arena.opus.env import (
    AuthStatus,
    PreflightError,
    check_auth_status,
    cli_version_token,
    dropped_names,
    preflight,
    resolve_claude_executable,
    scrub_env,
    subscription_image_digest,
)
from arena.opus.limits import (
    AUTH_EXPIRED,
    AUTH_EXPIRED_RESET_HINT,
    RATE_LIMIT,
    SUBSCRIPTION_LIMIT,
    TEMPORARY_CAPACITY,
    classify,
    extract_reset_hint,
)
from arena.opus.paths import SecretLeakError, assert_secret_free, atomic_write_json, sha256_tagged
from arena.opus.pricing import (
    PriceSnapshot,
    PriceSnapshotError,
    TokenUsage,
    auxiliary_usage,
    estimate_price,
    extract_usage,
)
from arena.opus.prompt import PromptError, resolve_prompt
from arena.opus.selection import (
    SelectionError,
    fallback_canary_keys,
    read_frozen_opus_canary,
    read_png_size,
    select_canary_pages,
    select_source_manifest_pages,
)

# --------------------------------------------------------------------------- env


def test_scrub_env_keeps_what_the_cli_needs_and_drops_credentials() -> None:
    parent = {
        "PATH": "/usr/bin",
        "USERPROFILE": r"C:\Users\x",
        "APPDATA": r"C:\Users\x\AppData\Roaming",
        "ANTHROPIC_API_KEY": "secret",
        "ANTHROPIC_AUTH_TOKEN": "secret",
        "ANTHROPIC_BASE_URL": "https://gateway.example",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "CLAUDE_CODE_SSE_PORT": "1",
        "UNRELATED": "kept out by the allow list",
    }
    child = scrub_env(parent)

    assert child["PATH"] == "/usr/bin"
    assert child["USERPROFILE"] == r"C:\Users\x"
    assert child["APPDATA"].endswith("Roaming")
    for dropped in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_SSE_PORT",
    ):
        assert dropped not in child
    assert "UNRELATED" not in child
    assert "secret" not in json.dumps(child)


def test_dropped_names_reports_what_was_removed() -> None:
    names = dropped_names({"CLAUDECODE": "1", "CLAUDE_CODE_X": "1", "PATH": "/usr/bin"})
    assert names == ["CLAUDECODE", "CLAUDE_CODE_X"]


def test_preflight_fails_when_the_parent_carries_an_api_key(tmp_path: Path) -> None:
    fake = tmp_path / "claude.py"
    fake.write_text("print('2.1.252 (Claude Code)')\n", encoding="utf-8")
    result = preflight(
        parent={"ANTHROPIC_API_KEY": "sk-should-block", "PATH": "/usr/bin"},
        executable=sys.executable,
    )

    assert result.ok is False
    assert result.parent_blocking_names == ("ANTHROPIC_API_KEY",)
    assert any("21.2" in f for f in result.findings)
    assert not any("sk-should-block" in f for f in result.findings)


def test_preflight_reports_a_missing_executable() -> None:
    result = preflight(parent={"PATH": "/usr/bin"}, executable="definitely-not-a-real-binary")
    assert result.ok is False
    assert result.claude_version is None
    assert any("not found" in f for f in result.findings)


def test_resolve_claude_executable_raises_when_absent() -> None:
    with pytest.raises(PreflightError):
        resolve_claude_executable("definitely-not-a-real-binary")


# ------------------------------------------------------------------ auth status


def _fake_completed(stdout: str, *, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["claude", "auth", "status", "--json"],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


def test_check_auth_status_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "loggedIn": True,
        "authMethod": "claude.ai",
        "apiProvider": "firstParty",
        "subscriptionType": "max",
        "email": "claude23@vieworks.com",
        "orgId": "32693053-68e1-4e74-9276-e3d8b9f5cf0c",
    }
    monkeypatch.setattr(
        opus_env.subprocess, "run", lambda *a, **k: _fake_completed(json.dumps(payload))
    )

    status = check_auth_status(parent={"PATH": "/usr/bin"}, executable=sys.executable)

    assert status == AuthStatus(
        logged_in=True,
        auth_method="claude.ai",
        api_provider="firstParty",
        subscription_type="max",
    )


def test_check_auth_status_raises_when_not_logged_in(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"loggedIn": False, "authMethod": None, "apiProvider": None}
    monkeypatch.setattr(
        opus_env.subprocess, "run", lambda *a, **k: _fake_completed(json.dumps(payload))
    )

    with pytest.raises(PreflightError, match="loggedIn=false"):
        check_auth_status(parent={"PATH": "/usr/bin"}, executable=sys.executable)


@pytest.mark.parametrize("auth_method", ["console", "api_key", None])
def test_check_auth_status_raises_when_auth_method_is_not_claude_ai(
    monkeypatch: pytest.MonkeyPatch, auth_method: str | None
) -> None:
    payload = {"loggedIn": True, "authMethod": auth_method, "apiProvider": "firstParty"}
    monkeypatch.setattr(
        opus_env.subprocess, "run", lambda *a, **k: _fake_completed(json.dumps(payload))
    )

    with pytest.raises(PreflightError, match="authMethod"):
        check_auth_status(parent={"PATH": "/usr/bin"}, executable=sys.executable)


def test_check_auth_status_raises_when_api_provider_is_not_first_party(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "bedrock"}
    monkeypatch.setattr(
        opus_env.subprocess, "run", lambda *a, **k: _fake_completed(json.dumps(payload))
    )

    with pytest.raises(PreflightError, match="apiProvider"):
        check_auth_status(parent={"PATH": "/usr/bin"}, executable=sys.executable)


@pytest.mark.parametrize(
    "stdout",
    ["not json at all", "", "[1, 2, 3]", '"just a string"'],
)
def test_check_auth_status_raises_on_malformed_output(
    monkeypatch: pytest.MonkeyPatch, stdout: str
) -> None:
    monkeypatch.setattr(opus_env.subprocess, "run", lambda *a, **k: _fake_completed(stdout))

    with pytest.raises(PreflightError):
        check_auth_status(parent={"PATH": "/usr/bin"}, executable=sys.executable)


def test_check_auth_status_never_carries_token_like_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "loggedIn": True,
        "authMethod": "claude.ai",
        "apiProvider": "firstParty",
        "subscriptionType": "max",
        "sessionToken": "sk-ant-should-never-appear",
        "apiKey": "sk-should-never-appear",
        "secret": "also-should-never-appear",
        "credential": "also-should-never-appear",
    }
    monkeypatch.setattr(
        opus_env.subprocess, "run", lambda *a, **k: _fake_completed(json.dumps(payload))
    )

    status = check_auth_status(parent={"PATH": "/usr/bin"}, executable=sys.executable)
    dumped = json.dumps(status.to_json())

    assert "sk-ant-should-never-appear" not in dumped
    assert "sk-should-never-appear" not in dumped
    assert "also-should-never-appear" not in dumped
    for name in ("sessionToken", "apiKey", "secret", "credential", "token", "key"):
        assert name not in dumped


def test_preflight_reports_ok_and_carries_auth_when_everything_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good_auth = {
        "loggedIn": True,
        "authMethod": "claude.ai",
        "apiProvider": "firstParty",
        "subscriptionType": "max",
    }

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if argv[1:] == ["--version"]:
            return _fake_completed("2.1.252 (Claude Code)\n")
        assert argv[1:] == ["auth", "status", "--json"]
        return _fake_completed(json.dumps(good_auth))

    monkeypatch.setattr(opus_env.subprocess, "run", fake_run)

    result = preflight(parent={"PATH": "/usr/bin"}, executable=sys.executable)

    assert result.ok is True
    assert result.auth == AuthStatus(
        logged_in=True, auth_method="claude.ai", api_provider="firstParty",
        subscription_type="max",
    )
    assert result.to_json()["auth"] == {
        "logged_in": True,
        "auth_method": "claude.ai",
        "api_provider": "firstParty",
        "subscription_type": "max",
    }


def test_preflight_fails_closed_when_auth_method_is_not_claude_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_auth = {"loggedIn": True, "authMethod": "console", "apiProvider": "firstParty"}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if argv[1:] == ["--version"]:
            return _fake_completed("2.1.252 (Claude Code)\n")
        return _fake_completed(json.dumps(bad_auth))

    monkeypatch.setattr(opus_env.subprocess, "run", fake_run)

    result = preflight(parent={"PATH": "/usr/bin"}, executable=sys.executable)

    assert result.ok is False
    assert result.auth is None
    assert any("authMethod" in f for f in result.findings)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("2.1.252 (Claude Code)", "2.1.252"),
        ("2.1.252", "2.1.252"),
        (None, "unknown"),
        ("", "unknown"),
    ],
)
def test_cli_version_token(version: str | None, expected: str) -> None:
    assert cli_version_token(version) == expected


def test_subscription_image_digest_follows_d27() -> None:
    """ARENA_CONTRACT D27: ``subscription:claude-code-<cli version>-<model id>``."""
    digest = subscription_image_digest("2.1.252 (Claude Code)", "claude-opus-5")
    assert digest == "subscription:claude-code-2.1.252-claude-opus-5"


def test_subscription_image_digest_is_accepted_by_arena_core_ids() -> None:
    """The lane may not write an identifier the shared module would reject."""
    digest = subscription_image_digest("2.1.252 (Claude Code)", "claude-opus-5")
    assert re.fullmatch(core_ids.RUNTIME_IMAGE_DIGEST_PATTERN, digest)
    job_id = core_ids.inference_job_id(
        campaign_id="c",
        benchmark_revision="rev",
        sample_id="omnidoc:images/x",
        source_sha256="sha256:" + "0" * 64,
        model_repo="anthropic:claude-opus-5",
        model_revision="claude-opus-5",
        runtime_image_digest=digest,
        prompt_sha256="sha256:" + "1" * 64,
        inference_config_sha256="sha256:" + "2" * 64,
    )
    assert re.fullmatch(r"[0-9a-f]{64}", job_id)


def test_subscription_image_digest_refuses_an_empty_model_id() -> None:
    with pytest.raises(PreflightError):
        subscription_image_digest("2.1.252", "")


def test_subscription_image_digest_sanitises_the_label() -> None:
    """A version string with a space cannot be allowed to break the grammar."""
    digest = subscription_image_digest("2.1.252-rc 1", "claude-opus-5")
    assert re.fullmatch(core_ids.RUNTIME_IMAGE_DIGEST_PATTERN, digest)


# ------------------------------------------------------------------------ limits


def test_subscription_limit_from_payload_result() -> None:
    payload = {
        "is_error": True,
        "result": "Claude usage limit reached. Your limit resets at 2026-09-03T18:00:00Z.",
    }
    detection = classify(exit_code=1, stderr="", payload=payload)

    assert detection is not None
    assert detection.kind == SUBSCRIPTION_LIMIT
    assert detection.error_class == "SUBSCRIPTION_LIMIT"
    assert detection.matched_in == "payload"
    assert detection.reset_hint == "2026-09-03T18:00:00Z"


def test_rate_limit_from_stderr() -> None:
    detection = classify(
        exit_code=1, stderr="API error 429: too many requests", payload=None
    )
    assert detection is not None
    assert detection.kind == RATE_LIMIT
    assert detection.error_class == "RATE_LIMIT"


def test_temporary_capacity_maps_to_infra_capacity() -> None:
    detection = classify(exit_code=1, stderr="Error: overloaded_error", payload=None)
    assert detection is not None
    assert detection.kind == TEMPORARY_CAPACITY
    assert detection.error_class == "INFRA_CAPACITY"


def test_auth_expired_from_real_failure_payload() -> None:
    """The exact shape of the 2026-09-04T05:46 attempt's failure payload.

    is_error true, terminal_reason "api_error", modelUsage empty, result names
    no model at all -- and must be classified AUTH_EXPIRED before it ever
    reaches the "unexpected model" check, not scored as a page failure.
    """
    payload = {
        "is_error": True,
        "subtype": "success",
        "terminal_reason": "api_error",
        "result": "Failed to authenticate: OAuth session expired and could not be refreshed",
        "modelUsage": {},
    }
    detection = classify(exit_code=1, stderr="", payload=payload)

    assert detection is not None
    assert detection.kind == AUTH_EXPIRED
    assert detection.error_class == "AUTH"
    assert detection.matched_in == "payload"
    assert detection.reset_hint == AUTH_EXPIRED_RESET_HINT


@pytest.mark.parametrize(
    "text",
    [
        "authentication_failed",
        "Invalid authentication credentials",
        "oauth_org_not_allowed",
        "You are not logged in",
    ],
)
def test_auth_expired_wording_family_from_stderr(text: str) -> None:
    detection = classify(exit_code=1, stderr=text, payload=None)
    assert detection is not None
    assert detection.kind == AUTH_EXPIRED
    assert detection.reset_hint == AUTH_EXPIRED_RESET_HINT


def test_a_successful_page_whose_text_mentions_a_limit_is_not_a_limit() -> None:
    """A transcription containing the words 'usage limit' must not pause the campaign."""
    payload = {
        "is_error": False,
        "subtype": "success",
        "result": "# Terms\n\nThe monthly usage limit reached by a customer is 5 GB.\n",
    }
    assert classify(exit_code=0, stderr="", payload=payload) is None


def test_clean_success_is_not_a_limit() -> None:
    payload = {"is_error": False, "subtype": "success", "result": "OK"}
    assert classify(exit_code=0, stderr="", payload=payload) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Your limit resets at 5pm", "5pm"),
        ("try again in 3600 seconds", "3600 seconds"),
        ("retry-after: 120", "120"),
        ("nothing here", None),
    ],
)
def test_extract_reset_hint(text: str, expected: str | None) -> None:
    assert extract_reset_hint(text) == expected


# ----------------------------------------------------------------------- pricing


def test_price_snapshot_loads_the_committed_file() -> None:
    snapshot = PriceSnapshot.load()
    assert snapshot.model_id == "claude-opus-5"
    assert snapshot.input_per_mtok_usd == 5.0
    assert snapshot.output_per_mtok_usd == 25.0
    # Cache prices were not published; they must stay null, not be guessed.
    assert snapshot.cache_write_per_mtok_usd is None
    assert snapshot.cache_read_per_mtok_usd is None
    assert snapshot.source_urls


def test_price_snapshot_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PriceSnapshotError):
        PriceSnapshot.load(tmp_path / "nope.json")


def test_price_snapshot_without_prices_raises(tmp_path: Path) -> None:
    target = tmp_path / "prices.json"
    target.write_text(json.dumps({"model_id": "x"}), encoding="utf-8")
    with pytest.raises(PriceSnapshotError):
        PriceSnapshot.load(target)


def test_estimate_price_uses_list_prices() -> None:
    snapshot = PriceSnapshot.load()
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=100_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    estimate = estimate_price(usage, snapshot)

    assert estimate.api_equivalent_list_price_usd == pytest.approx(5.0 + 2.5)
    assert estimate.price_complete is True


def test_estimate_price_flags_unpriced_cache_tokens() -> None:
    snapshot = PriceSnapshot.load()
    usage = TokenUsage(
        input_tokens=10,
        output_tokens=10,
        cache_creation_input_tokens=11_947,
        cache_read_input_tokens=1_247,
    )
    estimate = estimate_price(usage, snapshot)

    assert estimate.price_complete is False
    assert "cache_creation_input_tokens" in estimate.uncovered
    assert "cache_read_input_tokens" in estimate.uncovered
    assert estimate.api_equivalent_list_price_usd is not None


def test_unknown_usage_gives_a_null_price_not_zero() -> None:
    snapshot = PriceSnapshot.load()
    estimate = estimate_price(TokenUsage(None, None, None, None), snapshot)

    assert estimate.api_equivalent_list_price_usd is None
    assert estimate.price_complete is False


def test_extract_usage_prefers_the_named_model_entry() -> None:
    payload: dict[str, Any] = {
        "usage": {"input_tokens": 999, "output_tokens": 999},
        "modelUsage": {
            "claude-haiku-4-5-20251001": {"inputTokens": 898, "outputTokens": 11},
            "claude-opus-5": {"inputTokens": 2, "outputTokens": 4},
        },
    }
    usage = extract_usage(payload, model="claude-opus-5")

    assert usage.input_tokens == 2
    assert usage.output_tokens == 4
    assert usage.source == "modelUsage[claude-opus-5]"


def test_extract_usage_falls_back_to_the_top_level_block() -> None:
    usage = extract_usage({"usage": {"input_tokens": 7, "output_tokens": 8}}, model="absent")
    assert (usage.input_tokens, usage.output_tokens, usage.source) == (7, 8, "usage")


def test_extract_usage_reports_nothing_rather_than_zero() -> None:
    usage = extract_usage({}, model="claude-opus-5")
    assert usage.input_tokens is None
    assert usage.source == "not_reported"


def test_auxiliary_usage_is_kept_separate() -> None:
    payload = {
        "modelUsage": {"claude-haiku-4-5-20251001": {"inputTokens": 898, "outputTokens": 11}}
    }
    aux = auxiliary_usage(payload, ["claude-haiku-4-5-20251001"])
    assert aux["claude-haiku-4-5-20251001"]["input_tokens"] == 898


# ------------------------------------------------------------------------ prompt


def test_prompt_registry_copy_matches_lane_ds_transcription() -> None:
    """Lane A4's registry file and lane D's private copy must be byte-identical."""
    resolved = resolve_prompt()
    assert resolved.prompt_id == "opus5_transcription_v1"
    assert "Do not summarize." in resolved.text
    assert "Do not infer missing or obscured content." in resolved.text
    assert resolved.sha256.startswith("sha256:")


def test_prompt_falls_back_to_the_private_copy(tmp_path: Path) -> None:
    fallback = tmp_path / "fallback.txt"
    fallback.write_bytes(b"body\n")
    resolved = resolve_prompt(registry_path=tmp_path / "absent.txt", fallback_path=fallback)

    assert resolved.source == "lane_d_fallback"
    assert any("registry copy MUST hash" in n for n in resolved.notes)


def test_prompt_reports_a_registry_mismatch_instead_of_reconciling(tmp_path: Path) -> None:
    registry = tmp_path / "registry.txt"
    registry.write_bytes(b"registry text\n")
    fallback = tmp_path / "fallback.txt"
    fallback.write_bytes(b"different text\n")
    resolved = resolve_prompt(registry_path=registry, fallback_path=fallback)

    assert resolved.source == "prompt_registry"
    assert resolved.text == "registry text\n"
    assert any("registry copy is authoritative" in n.lower() for n in resolved.notes)


def test_prompt_with_nothing_available_raises(tmp_path: Path) -> None:
    with pytest.raises(PromptError):
        resolve_prompt(registry_path=tmp_path / "a.txt", fallback_path=tmp_path / "b.txt")


# --------------------------------------------------------------------- selection


def test_read_png_size_reads_the_ihdr(png_bytes: bytes) -> None:
    assert read_png_size(png_bytes) == (8, 6)


def test_read_png_size_refuses_a_non_png() -> None:
    with pytest.raises(SelectionError, match="not a PNG"):
        read_png_size(b"GIF89a" + b"\x00" * 40)


@pytest.mark.parametrize(
    ("benchmark", "entry", "expected"),
    [
        (
            "omnidoc",
            {
                "source_relative_path": "images/PPT_1001115_eng_page_003.png",
                "media_type": "image",
                "page_index": 3,
            },
            "omnidoc:images/PPT_1001115_eng_page_003",
        ),
        (
            "olmocr",
            {
                "source_relative_path": "bench_data/pdfs/arxiv_math/2502.15977_pg21.pdf",
                "media_type": "pdf",
                "page_index": 0,
            },
            "olmocr:bench_data/pdfs/arxiv_math/2502.15977_pg21#p0",
        ),
    ],
)
def test_sample_id_comes_from_arena_core_ids(
    benchmark: str, entry: dict[str, object], expected: str
) -> None:
    """D27: the lane derives sample_id through the shared module, not its own."""
    assert core_ids.sample_id_from_staged(entry, benchmark) == expected


def test_the_lane_keeps_no_private_sample_id_implementation() -> None:
    import arena.opus.selection as selection_module

    assert not hasattr(selection_module, "sample_id_for")


def test_selection_refuses_the_fallback_once_the_file_exists(tmp_path: Path) -> None:
    """ARENA_CONTRACT D27: a frozen selection may not be silently replaced."""
    path = tmp_path / "canary_selection.json"
    path.write_text(json.dumps({"campaign_id": "c"}), encoding="utf-8")
    with pytest.raises(SelectionError, match="opus_canary"):
        select_canary_pages(3, selection_path=path)


def test_selection_refuses_more_pages_than_the_frozen_block_holds(tmp_path: Path) -> None:
    path = tmp_path / "canary_selection.json"
    path.write_text(
        json.dumps({"opus_canary": {"samples": [{"case_key": "omnidocbench-aaa"}]}}),
        encoding="utf-8",
    )
    with pytest.raises(SelectionError, match="may not invent"):
        select_canary_pages(50, selection_path=path)


def test_frozen_block_reader_accepts_the_samples_shape(tmp_path: Path) -> None:
    """Lane A2 publishes ``opus_canary.samples``; the reader must not miss it."""
    path = tmp_path / "canary_selection.json"
    path.write_text(
        json.dumps(
            {
                "opus_canary": {
                    "samples": [
                        {
                            "case_key": "omnidocbench-aaa",
                            "sample_id": "omnidoc:images/a",
                            "input_png_sha256": "sha256:" + "0" * 64,
                        },
                        {"case_key": "omnidocbench-bbb"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    pages = read_frozen_opus_canary(path)
    assert [p.case_key for p in pages] == ["omnidocbench-aaa", "omnidocbench-bbb"]
    assert pages[0].sample_id == "omnidoc:images/a"
    assert pages[1].sample_id is None


def test_frozen_block_reader_refuses_a_repeated_case_key(tmp_path: Path) -> None:
    path = tmp_path / "canary_selection.json"
    path.write_text(
        json.dumps({"opus_canary": {"samples": [{"case_key": "x"}, {"case_key": "x"}]}}),
        encoding="utf-8",
    )
    with pytest.raises(SelectionError, match="repeats"):
        read_frozen_opus_canary(path)


def _write_staged_manifest(
    root: Path, staged_id: str, revision: str, entries: list[dict[str, Any]]
) -> None:
    manifest_dir = root / staged_id
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "inference-input-manifest.json").write_text(
        json.dumps({"dataset_revision": revision, "inputs": entries}), encoding="utf-8"
    )


def _staged_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    import arena.opus.selection as selection_module

    staged_root = tmp_path / "staged"
    monkeypatch.setattr(selection_module, "STAGED_PUBLIC_CORE_ROOT", staged_root, raising=True)
    return staged_root


def _write_source_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_select_source_manifest_pages_resolves_and_cross_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged_root = _staged_root(monkeypatch, tmp_path)
    sha_a = "sha256:" + "a" * 64
    sha_b = "sha256:" + "b" * 64
    _write_staged_manifest(
        staged_root,
        "omnidocbench",
        "rev-omni",
        [
            {
                "case_id": "omnidocbench-aaa",
                "source_relative_path": "images/page_a.png",
                "media_type": "image",
                "page_index": 0,
                "input_relative_path": "omnidocbench/inputs/omnidocbench-aaa.png",
                "input_sha256": sha_a,
                "source_sha256": "sha256:" + "1" * 64,
            }
        ],
    )
    _write_staged_manifest(
        staged_root,
        "olmocr-bench",
        "rev-olmocr",
        [
            {
                "case_id": "olmocr-bench-bbb",
                "source_relative_path": "bench_data/pdfs/a.pdf",
                "media_type": "pdf",
                "page_index": 0,
                "input_relative_path": "olmocr-bench/inputs/olmocr-bench-bbb.png",
                "input_sha256": sha_b,
                "source_sha256": "sha256:" + "2" * 64,
            }
        ],
    )

    manifest_path = tmp_path / "source_manifest.jsonl"
    _write_source_manifest(
        manifest_path,
        [
            {"benchmark": "omnidoc", "case_key": "omnidocbench-aaa", "input_png_sha256": sha_a},
            {"benchmark": "olmocr", "case_key": "olmocr-bench-bbb", "input_png_sha256": sha_b},
        ],
    )

    selection = select_source_manifest_pages(None, manifest_path=manifest_path)

    assert selection.source == "source_manifest.jsonl"
    assert [s.case_key for s in selection.specs] == ["omnidocbench-aaa", "olmocr-bench-bbb"]
    assert "omnidoc=1" in selection.detail
    assert "olmocr=1" in selection.detail
    assert sha256_tagged(manifest_path.read_bytes()) in selection.detail


def test_select_source_manifest_pages_honours_limit_and_preserves_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged_root = _staged_root(monkeypatch, tmp_path)
    entries = [
        {
            "case_id": f"omnidocbench-{letter}{letter}{letter}",
            "source_relative_path": f"images/page_{letter}.png",
            "media_type": "image",
            "page_index": 0,
            "input_relative_path": f"omnidocbench/inputs/omnidocbench-{letter}{letter}{letter}.png",
            "input_sha256": "sha256:" + letter * 64,
            "source_sha256": "sha256:" + "9" * 64,
        }
        for letter in ("c", "a", "b")
    ]
    _write_staged_manifest(staged_root, "omnidocbench", "rev-omni", entries)

    manifest_path = tmp_path / "source_manifest.jsonl"
    _write_source_manifest(
        manifest_path,
        [
            {"benchmark": "omnidoc", "case_key": "omnidocbench-ccc"},
            {"benchmark": "omnidoc", "case_key": "omnidocbench-aaa"},
            {"benchmark": "omnidoc", "case_key": "omnidocbench-bbb"},
        ],
    )

    selection = select_source_manifest_pages(2, manifest_path=manifest_path)

    # Manifest order preserved (c, a, b), not staged-manifest or sorted order.
    assert [s.case_key for s in selection.specs] == ["omnidocbench-ccc", "omnidocbench-aaa"]
    assert "3 rows" in selection.detail
    assert "2 selected" in selection.detail


def test_select_source_manifest_pages_fails_closed_on_missing_case_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged_root = _staged_root(monkeypatch, tmp_path)
    _write_staged_manifest(
        staged_root,
        "omnidocbench",
        "rev-omni",
        [
            {
                "case_id": "omnidocbench-aaa",
                "source_relative_path": "images/page_a.png",
                "media_type": "image",
                "page_index": 0,
                "input_relative_path": "omnidocbench/inputs/omnidocbench-aaa.png",
                "input_sha256": "sha256:" + "a" * 64,
                "source_sha256": "sha256:" + "1" * 64,
            }
        ],
    )
    manifest_path = tmp_path / "source_manifest.jsonl"
    _write_source_manifest(
        manifest_path, [{"benchmark": "omnidoc", "case_key": "omnidocbench-zzz"}]
    )

    with pytest.raises(SelectionError, match="is not in the staged"):
        select_source_manifest_pages(None, manifest_path=manifest_path)


def test_select_source_manifest_pages_fails_closed_on_sha_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged_root = _staged_root(monkeypatch, tmp_path)
    _write_staged_manifest(
        staged_root,
        "omnidocbench",
        "rev-omni",
        [
            {
                "case_id": "omnidocbench-aaa",
                "source_relative_path": "images/page_a.png",
                "media_type": "image",
                "page_index": 0,
                "input_relative_path": "omnidocbench/inputs/omnidocbench-aaa.png",
                "input_sha256": "sha256:" + "a" * 64,
                "source_sha256": "sha256:" + "1" * 64,
            }
        ],
    )
    manifest_path = tmp_path / "source_manifest.jsonl"
    _write_source_manifest(
        manifest_path,
        [
            {
                "benchmark": "omnidoc",
                "case_key": "omnidocbench-aaa",
                "input_png_sha256": "sha256:" + "f" * 64,
            }
        ],
    )

    with pytest.raises(SelectionError, match="derives"):
        select_source_manifest_pages(None, manifest_path=manifest_path)


def test_select_source_manifest_pages_refuses_a_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(SelectionError, match="source manifest missing"):
        select_source_manifest_pages(None, manifest_path=tmp_path / "nope.jsonl")


def test_fallback_canary_selection_is_deterministic() -> None:
    """Still deterministic, but reachable only when lane A2 has published nothing."""
    first = fallback_canary_keys(3)
    second = fallback_canary_keys(3)
    assert first == second
    assert len(first) == 3
    assert all(k.startswith("omnidocbench-") for k in first)


# ------------------------------------------------------------------- secret-free


@pytest.mark.parametrize(
    "value",
    [
        {"k": "sk-ant-api03-abcdefghijklmnop"},
        {"k": "rpa_ABCDEFGHIJKLMNOPQRST"},
        ["ghp_ABCDEFGHIJKLMNOPQRST"],
        {"nested": {"deep": "AK" + "IA" + "A" * 16}},
        {"k": "aB3" * 30},
    ],
)
def test_assert_secret_free_rejects_credentials(value: Any) -> None:
    with pytest.raises(SecretLeakError):
        assert_secret_free(value, where="test")


def test_assert_secret_free_allows_a_sha256_digest() -> None:
    assert_secret_free({"sha": "sha256:" + "a1" * 32}, where="test")


def test_atomic_write_json_refuses_to_persist_a_secret(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    with pytest.raises(SecretLeakError):
        atomic_write_json(target, {"token": "sk-ant-api03-abcdefghijklmnop"}, where="test")
    assert not target.exists()


def test_atomic_write_json_returns_the_hash(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    digest = atomic_write_json(target, {"a": 1}, where="test")
    assert digest == sha256_tagged(target.read_bytes())
    assert not list(tmp_path.glob("*.tmp"))


# ----------------------------------------------------------------- config guard


def test_default_config_never_names_another_model() -> None:
    cfg = OpusCommandConfig(claude_executable="claude")
    rendered = json.dumps(cfg.inference_config())
    for forbidden in ("sonnet", "haiku", "fable", "gpt", "gemini"):
        assert forbidden not in rendered


def test_the_session_limit_text_of_2026_09_04_is_a_subscription_limit_with_its_reset() -> None:
    """D69: the real `claude -p` result on the 5-hour window. Before this, the
    payload named no model and the pool stopped as unexpected_model instead."""
    text = "You've hit your session limit \u00b7 resets 7:50am (Asia/Seoul)"
    detection = classify(
        exit_code=1, stderr="", payload={"type": "result", "is_error": True, "result": text},
        raw_stdout="",
    )
    assert detection is not None
    assert detection.kind == SUBSCRIPTION_LIMIT
    assert detection.reset_hint == "7:50am (Asia/Seoul)"
