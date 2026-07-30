"""Repository policy checks that require no credentials or external services."""

from __future__ import annotations

import json
import os
import re
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_PUBLIC_SUFFIXES = {".exe", ".dll", ".scr", ".com", ".ps1", ".bat"}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_classic_token": re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),
    "github_fine_grained_token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    "openai_api_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{40,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "stripe_live_key": re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b"),
}
SCAN_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    ".next",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
    ".terraform",
    ".akc-data",
    ".akc-data-test",
    "__pycache__",
    "coverage",
    "work",
    "playwright-report",
    "test-results",
}
ACTION_USE_PATTERN = re.compile(
    r"uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)"
    r"@([0-9a-f]{40})\s+#\s+(v[0-9]+\.[0-9]+\.[0-9]+)\s*$"
)
FROZEN_MASTERPLAN_DIGESTS = {
    "AI_Knowledge_Compiler_SaaS_Masterplan_FINAL_v2_KO_2026-07-29.md": (
        "B09D3CC3404A44F20EAF4EDDC79FE44C93B458677D151946EFF32D7B601C39AE"
    ),
    "AI_Knowledge_Compiler_Enterprise_UI_UX_Masterplan_FINAL_KO_2026-07-30.md": (
        "9C08E0DF4437D7EF1C9FB21B228187FA7CE4DD26A303BC9FC449AE4C2D2BED28"
    ),
}


def load_yaml(relative: str) -> Any:
    with (ROOT / relative).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def repository_dockerfiles() -> tuple[Path, ...]:
    """Return source Dockerfiles without traversing generated dependency trees."""

    return tuple(
        sorted(
            path
            for source_root in (ROOT / "apps", ROOT / "services", ROOT / "workers")
            for path in source_root.rglob("Dockerfile")
            if not SCAN_EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts)
        )
    )


def validate_source_registry(errors: list[str]) -> None:
    register = load_yaml("docs/compliance/source-register.yaml")
    ids = [item.get("id") for item in register.get("sources") or []]
    expected = [f"S{number:02d}" for number in range(1, 52)]
    if ids != expected:
        errors.append("source registry must contain S01..S51 exactly once and in order")


def validate_conflict_decisions(errors: list[str]) -> None:
    text = (ROOT / "docs/adr/README.md").read_text(encoding="utf-8")
    for number in range(1, 11):
        conflict = f"C-{number:02d}"
        if conflict not in text:
            errors.append(f"missing spec-conflict decision {conflict}")


def validate_synthetic_ground_truth(errors: list[str]) -> None:
    schema_path = ROOT / "benchmark/schemas/page-ground-truth.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    path = ROOT / "benchmark/ground-truth/synthetic-v1.jsonl"
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            record = json.loads(line)
            for error in validator.iter_errors(record):
                errors.append(f"{path.relative_to(ROOT)}:{line_number}: {error.message}")
            if record.get("is_synthetic") is not True:
                errors.append(f"{path.relative_to(ROOT)}:{line_number}: must be synthetic")


def validate_feature_defaults(errors: list[str]) -> None:
    recipes = load_yaml("infra/model-registry/recipes.yaml")
    if recipes.get("defaults", {}).get("allow_external") is not False:
        errors.append("model recipes must default external processing to false")
    flags = recipes.get("feature_flags") or {}
    for name in (
        "hpd_fast_route",
        "unlimited_long_doc",
        "external_mistral_fallback",
        "external_precision_api",
        "url_ingest_enabled",
        "ontology_export",
        "existing_vault_merge",
        "chart_description",
    ):
        if flags.get(name) is not False:
            errors.append(f"feature flag {name} must default to false")


def scan_public_fixtures(errors: list[str]) -> None:
    corpus = ROOT / "benchmark/corpus"
    for path in corpus.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in FORBIDDEN_PUBLIC_SUFFIXES:
            errors.append(f"forbidden executable fixture: {path.relative_to(ROOT)}")
        if path.stat().st_size > 5 * 1024 * 1024:
            errors.append(f"public corpus file exceeds 5 MiB: {path.relative_to(ROOT)}")


def scan_secrets(errors: list[str]) -> None:
    scanner_path = Path(__file__).resolve()
    for directory, child_directories, filenames in os.walk(ROOT):
        child_directories[:] = [
            name for name in child_directories if name not in SCAN_EXCLUDED_PARTS
        ]
        base = Path(directory)
        for filename in filenames:
            path = base / filename
            if path == scanner_path or path.stat().st_size > 2 * 1024 * 1024:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for name, pattern in SECRET_PATTERNS.items():
                if pattern.search(text):
                    errors.append(f"possible {name} in {path.relative_to(ROOT)}")


def validate_serialized_documents(errors: list[str]) -> None:
    roots = [ROOT / "docs", ROOT / "benchmark", ROOT / "infra", ROOT / "workers", ROOT / ".github"]
    for directory in roots:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            try:
                if path.suffix in {".json", ".jsonld"}:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    if path.name.endswith(".schema.json"):
                        Draft202012Validator.check_schema(value)
                elif path.suffix in {".yaml", ".yml"}:
                    documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
                    if not documents or all(document is None for document in documents):
                        errors.append(f"empty YAML document: {relative}")
            except Exception as exc:  # jsonschema raises several validation subclasses
                errors.append(f"invalid serialized document {relative}: {exc}")


def validate_compose_contract(errors: list[str]) -> None:
    compose = load_yaml("docker-compose.dev.yml")
    services = compose.get("services") or {}
    required = {"postgres", "redis", "minio", "clamav", "api", "scheduler", "web"}
    missing = required.difference(services)
    if missing:
        errors.append(f"development Compose missing services {sorted(missing)}")
    api_environment = services.get("api", {}).get("environment") or {}
    if api_environment.get("AKC_EXTERNAL_OCR_ENABLED") != "false":
        errors.append("Compose API must disable external processing")
    if api_environment.get("AKC_PRIVATE_MODE") != "true":
        errors.append("Compose API must enable private mode by default")
    if api_environment.get("AKC_CLAMAV_ENABLED") != "true":
        errors.append("Compose API must enable fail-closed ClamAV scanning")
    for required_path in (
        "services/api/Dockerfile",
        "services/scheduler/Dockerfile",
        "apps/web/Dockerfile",
    ):
        if not (ROOT / required_path).is_file():
            errors.append(f"Compose build target missing: {required_path}")


def validate_supply_chain_pins(errors: list[str]) -> None:
    pin_path = ROOT / "infra/supply-chain/verified-pins.json"
    pins = json.loads(pin_path.read_text(encoding="utf-8"))
    action_pins: dict[str, tuple[str, str]] = {}
    for versioned_action, sha in pins.get("github_actions", {}).items():
        repository, version = versioned_action.rsplit("@", 1)
        action_pins[repository] = (version, str(sha))

    observed_actions: set[str] = set()
    for workflow in sorted((ROOT / ".github/workflows").glob("*.yml")):
        for line_number, line in enumerate(
            workflow.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if "uses:" not in line or "uses: ./" in line:
                continue
            match = ACTION_USE_PATTERN.search(line)
            if match is None:
                errors.append(
                    f"{workflow.relative_to(ROOT)}:{line_number}: "
                    "external action must use a 40-character SHA and exact version comment"
                )
                continue
            action, sha, version = match.groups()
            repository = "/".join(action.split("/")[:2])
            expected = action_pins.get(repository)
            if expected != (version, sha):
                errors.append(
                    f"{workflow.relative_to(ROOT)}:{line_number}: "
                    f"{repository} does not match verified-pins.json"
                )
            observed_actions.add(repository)
    missing_actions = sorted(set(action_pins) - observed_actions)
    if missing_actions:
        errors.append(f"verified action pins are unused: {missing_actions}")

    image_pins = {
        str(image): str(digest) for image, digest in pins.get("container_images", {}).items()
    }
    dockerfiles = repository_dockerfiles()
    image_sources = [
        *dockerfiles,
        *sorted((ROOT / ".github/workflows").glob("*.yml")),
    ]
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in image_sources)
    for image, digest in image_pins.items():
        if f"{image}@{digest}" not in source_text:
            errors.append(f"verified container pin is unused: {image}@{digest}")

    for dockerfile in dockerfiles:
        stage_aliases: set[str] = set()
        for line_number, line in enumerate(
            dockerfile.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            match = re.match(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", line, re.IGNORECASE)
            if match is None:
                continue
            image, alias = match.groups()
            if image not in stage_aliases and "@sha256:" not in image:
                errors.append(
                    f"{dockerfile.relative_to(ROOT)}:{line_number}: "
                    "external base image must use a verified digest"
                )
            if alias:
                stage_aliases.add(alias)

    for lockfile in ("uv.lock", "workers/gpu-common/uv.lock"):
        if not (ROOT / lockfile).is_file():
            errors.append(f"required Python lockfile is missing: {lockfile}")
    for dockerfile in (
        ROOT / "services/api/Dockerfile",
        ROOT / "services/scheduler/Dockerfile",
    ):
        text = dockerfile.read_text(encoding="utf-8")
        for marker in ("COPY pyproject.toml uv.lock", "uv sync --locked --no-dev"):
            if marker not in text:
                errors.append(f"{dockerfile.relative_to(ROOT)} must enforce locked production sync")
    for dockerfile in sorted((ROOT / "workers").glob("gpu-*/Dockerfile")):
        text = dockerfile.read_text(encoding="utf-8")
        for marker in (
            "workers/gpu-common/uv.lock",
            "uv sync --locked --no-dev",
        ):
            if marker not in text:
                errors.append(f"{dockerfile.relative_to(ROOT)} must enforce the GPU lockfile")

    workflow_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github/workflows").glob("*.yml"))
    )
    for forbidden in ('pip install -e ".[dev]"', "pip install -r "):
        if forbidden in workflow_text:
            errors.append(f"workflow bypasses uv.lock with: {forbidden}")
    if "uv sync --locked --extra dev" not in workflow_text:
        errors.append("workflows must sync the immutable Python development environment")


def validate_implementation_matrix(errors: list[str]) -> None:
    path = ROOT / "docs/IMPLEMENTATION_MATRIX.md"
    raw = path.read_bytes()
    if not raw.startswith(b"\xef\xbb\xbf"):
        errors.append("implementation matrix must retain a UTF-8 BOM for Windows readers")
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        errors.append(f"implementation matrix is not strict UTF-8: {exc}")
        return
    mojibake_fragments = ("臾", "꽌", "뭩", "媛", "쒖", "븳", "怨", "鍮", "吏", "�")
    if any(fragment in text for fragment in mojibake_fragments):
        errors.append("implementation matrix contains a common mojibake fragment")
    chapter_count = len(
        re.findall(
            r"^\|\s+(?:[0-9]|[1-3][0-9]|4[0-5])\.\s",
            text,
            flags=re.MULTILINE,
        )
    )
    phase_count = len(re.findall(r"^\|\s+Phase [0-9]\s", text, flags=re.MULTILINE))
    gate_count = len(re.findall(r"^\|\s+Gate [0-6]\s", text, flags=re.MULTILINE))
    if (chapter_count, phase_count, gate_count) != (46, 10, 7):
        errors.append(
            "implementation matrix coverage must be chapters=46 phases=10 gates=7; "
            f"got {chapter_count}/{phase_count}/{gate_count}"
        )


def validate_frozen_masterplans(errors: list[str]) -> None:
    directory = ROOT / "docs/masterplan"
    for filename, expected_digest in FROZEN_MASTERPLAN_DIGESTS.items():
        path = directory / filename
        if not path.is_file():
            errors.append(f"frozen masterplan is missing: {path.relative_to(ROOT)}")
            continue
        actual_digest = sha256(path.read_bytes()).hexdigest().upper()
        if actual_digest != expected_digest:
            errors.append(
                f"frozen masterplan digest mismatch: {path.relative_to(ROOT)} "
                f"expected {expected_digest}, got {actual_digest}"
            )


def validate_ui_implementation_matrix(errors: list[str]) -> None:
    path = ROOT / "docs/UI_IMPLEMENTATION_MATRIX.md"
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        errors.append(f"UI implementation matrix is not strict UTF-8: {exc}")
        return
    chapter_count = len(
        re.findall(
            r"^\|\s+(?:[0-9]|[1-3][0-9]|4[01])\.\s",
            text,
            flags=re.MULTILINE,
        )
    )
    epic_count = len(
        re.findall(
            r"^\|\s+`EPIC-UI-(?:00[1-9]|01[0-3])`",
            text,
            flags=re.MULTILINE,
        )
    )
    if (chapter_count, epic_count) != (42, 13):
        errors.append(
            "UI implementation matrix coverage must be chapters=42 epics=13; "
            f"got {chapter_count}/{epic_count}"
        )
    frozen_source = (
        "docs/masterplan/AI_Knowledge_Compiler_Enterprise_UI_UX_Masterplan_FINAL_KO_2026-07-30.md"
    )
    if frozen_source not in text:
        errors.append("UI implementation matrix must reference the frozen UI source")


def main() -> int:
    errors: list[str] = []
    validate_source_registry(errors)
    validate_conflict_decisions(errors)
    validate_synthetic_ground_truth(errors)
    validate_feature_defaults(errors)
    scan_public_fixtures(errors)
    scan_secrets(errors)
    validate_serialized_documents(errors)
    validate_compose_contract(errors)
    validate_supply_chain_pins(errors)
    validate_implementation_matrix(errors)
    validate_frozen_masterplans(errors)
    validate_ui_implementation_matrix(errors)
    if errors:
        for error in sorted(set(errors)):
            print(error)
        return 1
    print("repository policy validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
