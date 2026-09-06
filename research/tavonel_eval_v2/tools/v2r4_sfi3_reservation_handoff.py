"""Immutable administrative bridge from V2R4 rung 0a to SFI3.

This module does not amend or supersede V2R4 evidence.  It binds the exact
pre-result reservation to the exact historical V2R4 frame and recomputes only
container-identity separation.  It never opens SFI3 material or reads a V2R4
scientific result value.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _directory in (NS / "tools", NS / "acquisition"):
    _text = str(_directory)
    if _text not in sys.path:
        sys.path.insert(0, _text)

import sfi3_root_reservation as reservation  # noqa: E402
from common import canonical_sha, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402

SCHEMA = "V2R4_SFI3_RESERVATION_HANDOFF_V1"
HANDOFF_ID = SCHEMA
STEM = "v2r4-sfi3-reservation-handoff"
INCIDENT_ID = "INC-V2-084"
SCIENTIFIC_SCOPE = "NONE — ADMINISTRATIVE CROSS-STAGE BINDING ONLY"

FRAME_ATTESTATION_REL = (
    "research/tavonel_eval_v2/receipts/"
    "identity-change-migration-closure-v2r4-frame-attestation--"
    "20260826T050508Z-a1a4ec80798a.json"
)
ACQUISITION_FRAME_REL = (
    "research/tavonel_eval_v2/receipts/"
    "identity-change-migration-closure-v2r4-acquisition-frame-freeze--"
    "20260826T050507Z-f9091fd6943a.json"
)
RESERVATION_REL = (
    "research/tavonel_eval_v2/receipts/sfi3-root-reservation--20260826T040829Z-e0f676096927.json"
)
MEASUREMENT_REL = (
    "research/tavonel_eval_v2/receipts/"
    "identity-change-migration-closure-v2r4--20260826T064947Z-e6cab21d2c93.json"
)

FRAME_ATTESTATION_PATH = ROOT / FRAME_ATTESTATION_REL
ACQUISITION_FRAME_PATH = ROOT / ACQUISITION_FRAME_REL
RESERVATION_PATH = ROOT / RESERVATION_REL
MEASUREMENT_PATH = ROOT / MEASUREMENT_REL

FRAME_ATTESTATION_FILE_SHA256 = (
    "sha256:669894efdec510450558c5531b54bab1e9e36459b3f052be661cfd1da909a879"
)
ACQUISITION_FRAME_FILE_SHA256 = (
    "sha256:ce64af49705fba9be3421f9be63925f3e118458a8fabd083bf419d194c5cf60e"
)
RESERVATION_FILE_SHA256 = "sha256:4ed7d2ea654fa89dbb63258ace3a4ea77eab8722e29c3218db351f30cde7a8f4"
MEASUREMENT_FILE_SHA256 = "sha256:28da167f1c98a67b866e40add4bfa5ba840b618e1a1559c24a11b516e2ea3474"

FRAME_ATTESTATION_RUN_ID = "20260826T050508Z-a1a4ec80798a"
ACQUISITION_FRAME_RUN_ID = "20260826T050507Z-f9091fd6943a"
RESERVATION_RUN_ID = "20260826T040829Z-e0f676096927"
MEASUREMENT_RUN_ID = "20260826T064947Z-e6cab21d2c93"

FRAME_ATTESTATION_SCHEMA = "tavonel.v2.identity_change_migration_closure.v2r4_attestation.v1"
RESERVATION_SCHEMA = "tavonel.v2.sfi3_root_reservation.v1"
FRAME_MODULE_REL = "research/tavonel_eval_v2/acquisition/sources_v2r4.py"

BODY_KEYS = frozenset(
    {
        "schema",
        "handoff_id",
        "scientific_scope",
        "incident_id",
        "historical_frame_attestation",
        "acquisition_frame_freeze",
        "reservation",
        "chronology",
        "declared_containers",
        "declared_containers_sha256",
        "declared_container_counts",
        "historical_root_disjointness_sha256",
        "historical_sfi3_separation_sha256",
        "equivalence",
        "separation_corroboration",
    }
)
ENVELOPE_KEYS = BODY_KEYS | {"provenance", "receipt_sha256"}
FAMILIES = ("git_docs", "regulation_ecfr", "sec_edgar")


class HandoffRefused(RuntimeError):
    """The exact predecessor-successor binding cannot be established."""


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise HandoffRefused(detail)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HandoffRefused(f"cannot read exact receipt {path}: {error}") from error
    _require(isinstance(body, dict), f"{path} is not a JSON object")
    return body


def _verify_exact_file(path: Path, expected_relative: str, expected_sha256: str) -> None:
    _require(path.is_file(), f"exact receipt is absent: {expected_relative}")
    try:
        actual_relative = rel(path)
    except ValueError as error:
        raise HandoffRefused(f"receipt escapes the repository: {path}") from error
    _require(actual_relative == expected_relative, f"wrong exact receipt path: {actual_relative}")
    actual_sha256 = sha_file(path)
    _require(
        actual_sha256 == expected_sha256,
        f"exact receipt file digest mismatch for {expected_relative}: {actual_sha256}",
    )


def _verify_provenance(body: dict[str, Any], *, run_id: str, receipt_stem: str) -> dict[str, Any]:
    provenance = body.get("provenance")
    _require(isinstance(provenance, dict), f"{receipt_stem} has no provenance object")
    _require(provenance.get("run_id") == run_id, f"wrong run_id for {receipt_stem}")
    _require(
        provenance.get("receipt_stem") == receipt_stem,
        f"wrong receipt_stem for {receipt_stem}",
    )
    _require(provenance.get("immutable") is True, f"{receipt_stem} is not immutable")
    _require(isinstance(provenance.get("generated_at"), str), f"{receipt_stem} has no time")
    return provenance


def _measurement_metadata() -> dict[str, str]:
    """Read only the trailing provenance object, never a V2R4 result field."""
    _verify_exact_file(MEASUREMENT_PATH, MEASUREMENT_REL, MEASUREMENT_FILE_SHA256)
    with MEASUREMENT_PATH.open("rb") as handle:
        size = handle.seek(0, 2)
        handle.seek(max(0, size - 8192))
        tail = handle.read().decode("utf-8")
    marker = '"provenance"'
    position = tail.rfind(marker)
    _require(position >= 0, "V2R4 measurement has no trailing provenance marker")
    colon = tail.find(":", position + len(marker))
    _require(colon >= 0, "V2R4 measurement provenance is malformed")
    value_start = colon + 1
    while value_start < len(tail) and tail[value_start].isspace():
        value_start += 1
    try:
        provenance, _end = json.JSONDecoder().raw_decode(tail, value_start)
    except json.JSONDecodeError as error:
        raise HandoffRefused("cannot decode V2R4 measurement provenance") from error
    _require(isinstance(provenance, dict), "measurement provenance is not an object")
    _require(provenance.get("run_id") == MEASUREMENT_RUN_ID, "wrong measurement run_id")
    _require(
        provenance.get("receipt_stem") == "identity-change-migration-closure-v2r4",
        "wrong measurement receipt_stem",
    )
    _require(isinstance(provenance.get("generated_at"), str), "measurement has no time")
    return {
        "run_id": provenance["run_id"],
        "generated_at": provenance["generated_at"],
    }


def _parse_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise HandoffRefused(f"{label} is not an ISO timestamp") from error
    _require(parsed.tzinfo is not None, f"{label} has no timezone")
    return parsed


def _canonical_identities(values: Any, label: str) -> list[str]:
    _require(isinstance(values, list), f"{label} containers are not a list")
    _require(all(isinstance(value, str) and value for value in values), f"{label} has bad IDs")
    _require(len(values) == len(set(values)), f"{label} has duplicate container IDs")
    return sorted(values)


def _extract_declared_containers(frame_body: dict[str, Any]) -> dict[str, list[str]]:
    declaration = frame_body.get("frame_declaration")
    _require(isinstance(declaration, dict), "frozen acquisition frame has no declaration")
    source_roots = declaration.get("source_roots")
    _require(isinstance(source_roots, dict), "frozen frame has no source_roots")
    _require(set(source_roots) == set(FAMILIES), "frozen frame family set drifted")

    git = source_roots["git_docs"]
    ecfr = source_roots["regulation_ecfr"]
    sec = source_roots["sec_edgar"]
    _require(all(isinstance(value, dict) for value in (git, ecfr, sec)), "bad source-root shape")

    git_values = _canonical_identities(git.get("containers"), "git_docs")
    git_roots = git.get("roots")
    _require(isinstance(git_roots, list), "git_docs roots are absent")
    git_derived = _canonical_identities(
        [f"{root['owner']}/{root['repo']}" for root in git_roots], "git_docs roots"
    )
    _require(git_values == git_derived, "git container declarations disagree with frozen roots")
    _require(git.get("container_count") == len(git_values), "git container count drifted")

    ecfr_values = _canonical_identities(ecfr.get("containers"), "regulation_ecfr")
    ecfr_roots = ecfr.get("roots")
    _require(isinstance(ecfr_roots, list), "regulation_ecfr roots are absent")
    ecfr_derived = _canonical_identities(
        [f"{root['title']}-{root['part']}" for root in ecfr_roots], "regulation_ecfr roots"
    )
    _require(
        ecfr_values == ecfr_derived,
        "regulation container declarations disagree with frozen roots",
    )
    _require(ecfr.get("container_count") == len(ecfr_values), "eCFR container count drifted")

    _require(sec.get("containers") == "RULE", "SEC frozen container marker is not RULE")
    _require(sec.get("container_count") is None, "SEC RULE acquired a list count")
    _require(isinstance(sec.get("rule"), dict), "SEC frozen rule is absent")
    return {"git_docs": git_values, "regulation_ecfr": ecfr_values, "sec_edgar": []}


def _reference(
    body: dict[str, Any], *, path: Path, run_id: str, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    provenance = body["provenance"]
    result = {
        "receipt": rel(path),
        "file_sha256": sha_file(path),
        "receipt_sha256": body["receipt_sha256"],
        "run_id": run_id,
        "generated_at": provenance["generated_at"],
    }
    if extra:
        result.update(extra)
    return result


def build() -> dict[str, Any]:
    """Build the administrative binding in memory; do not write."""
    _verify_exact_file(FRAME_ATTESTATION_PATH, FRAME_ATTESTATION_REL, FRAME_ATTESTATION_FILE_SHA256)
    _verify_exact_file(ACQUISITION_FRAME_PATH, ACQUISITION_FRAME_REL, ACQUISITION_FRAME_FILE_SHA256)
    _verify_exact_file(RESERVATION_PATH, RESERVATION_REL, RESERVATION_FILE_SHA256)

    frame_attestation = _read_json(FRAME_ATTESTATION_PATH)
    acquisition_frame = _read_json(ACQUISITION_FRAME_PATH)
    stored_reservation = _read_json(RESERVATION_PATH)
    measurement = _measurement_metadata()

    frame_provenance = _verify_provenance(
        frame_attestation,
        run_id=FRAME_ATTESTATION_RUN_ID,
        receipt_stem="identity-change-migration-closure-v2r4-frame-attestation",
    )
    acquisition_provenance = _verify_provenance(
        acquisition_frame,
        run_id=ACQUISITION_FRAME_RUN_ID,
        receipt_stem="identity-change-migration-closure-v2r4-acquisition-frame-freeze",
    )
    reservation_provenance = _verify_provenance(
        stored_reservation, run_id=RESERVATION_RUN_ID, receipt_stem="sfi3-root-reservation"
    )

    _require(frame_attestation.get("schema") == FRAME_ATTESTATION_SCHEMA, "wrong frame schema")
    _require(stored_reservation.get("schema") == RESERVATION_SCHEMA, "wrong reservation schema")
    _require(
        stored_reservation.get("reservation_id") == reservation.RESERVATION_ID,
        "wrong reservation_id",
    )

    attests = frame_attestation.get("attests")
    _require(isinstance(attests, dict), "frame attestation has no rung-0 binding")
    _require(attests.get("receipt") == ACQUISITION_FRAME_REL, "wrong attested frame path")
    _require(
        attests.get("receipt_file_sha256") == ACQUISITION_FRAME_FILE_SHA256,
        "wrong attested frame file digest",
    )
    _require(
        attests.get("receipt_body_sha256") == acquisition_frame.get("receipt_sha256"),
        "wrong attested frame body digest",
    )
    _require(attests.get("run_id") == ACQUISITION_FRAME_RUN_ID, "wrong attested frame run_id")

    pinned_files = frame_attestation.get("pinned_files")
    _require(isinstance(pinned_files, dict), "frame attestation has no file pins")
    _require(
        acquisition_frame.get("frame_module") == FRAME_MODULE_REL,
        "frozen frame names the wrong module",
    )
    _require(
        acquisition_frame.get("frame_module_sha256")
        == pinned_files.get("acquisition/sources_v2r4.py"),
        "frozen frame module digest differs from historical attestation",
    )

    historical_separation = frame_attestation.get("sfi3_separation")
    historical_roots = frame_attestation.get("root_disjointness")
    _require(isinstance(historical_separation, dict), "historical SFI3 separation is absent")
    _require(isinstance(historical_roots, dict), "historical root disjointness is absent")
    _require(historical_separation.get("held") is True, "historical separation was not held")

    equality = {
        "content_digest_equal": stored_reservation.get("content_digest")
        == historical_separation.get("content_digest"),
        "frame_module_sha256_equal": stored_reservation.get("frame_module_sha256")
        == historical_separation.get("sfi3_frame_module_sha256"),
        "replacement_module_sha256_equal": stored_reservation.get("replacement_module_sha256")
        == historical_separation.get("sfi3_replacement_module_sha256"),
    }
    _require(all(equality.values()), f"reservation equivalence failed: {equality}")

    declared = _extract_declared_containers(acquisition_frame)
    counts = {family: len(declared[family]) for family in FAMILIES}
    _require(
        counts == historical_separation.get("containers_checked"),
        "frozen container counts differ from historical separation",
    )
    equality["historical_container_counts_equal"] = True

    reservation_time = _parse_time(reservation_provenance["generated_at"], "reservation time")
    frame_time = _parse_time(frame_provenance["generated_at"], "frame-attestation time")
    measurement_time = _parse_time(measurement["generated_at"], "measurement time")
    _require(
        reservation_time < frame_time < measurement_time,
        "required reservation < frame attestation < measurement chronology failed",
    )

    try:
        drift = reservation.verify(stored_reservation)
        separation = reservation.require_separation(
            reservation=stored_reservation,
            families=declared,
            study="IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4",
        )
    except reservation.ReservationRefused as error:
        raise HandoffRefused(str(error)) from error
    _require(drift.get("held") is True and separation.get("held") is True, "separation not held")

    return {
        "schema": SCHEMA,
        "handoff_id": HANDOFF_ID,
        "scientific_scope": SCIENTIFIC_SCOPE,
        "incident_id": INCIDENT_ID,
        "historical_frame_attestation": _reference(
            frame_attestation,
            path=FRAME_ATTESTATION_PATH,
            run_id=FRAME_ATTESTATION_RUN_ID,
            extra={"schema": FRAME_ATTESTATION_SCHEMA},
        ),
        "acquisition_frame_freeze": _reference(
            acquisition_frame,
            path=ACQUISITION_FRAME_PATH,
            run_id=ACQUISITION_FRAME_RUN_ID,
            extra={
                "frame_module": acquisition_frame["frame_module"],
                "frame_module_sha256": acquisition_frame["frame_module_sha256"],
                "frame_declaration_digest": acquisition_frame["frame_declaration_digest"],
            },
        ),
        "reservation": _reference(
            stored_reservation,
            path=RESERVATION_PATH,
            run_id=RESERVATION_RUN_ID,
            extra={
                "schema": stored_reservation["schema"],
                "reservation_id": stored_reservation["reservation_id"],
                "content_digest": stored_reservation["content_digest"],
                "frame_module_sha256": stored_reservation["frame_module_sha256"],
                "replacement_module_sha256": stored_reservation["replacement_module_sha256"],
            },
        ),
        "chronology": {
            "reservation_generated_at": reservation_provenance["generated_at"],
            "historical_frame_attestation_generated_at": frame_provenance["generated_at"],
            "v2r4_measurement_generated_at": measurement["generated_at"],
            "strict_order_verified": True,
        },
        "declared_containers": declared,
        "declared_containers_sha256": canonical_sha(declared),
        "declared_container_counts": counts,
        "historical_root_disjointness_sha256": canonical_sha(historical_roots),
        "historical_sfi3_separation_sha256": canonical_sha(historical_separation),
        "equivalence": equality,
        "separation_corroboration": {
            "held": True,
            "study": separation["study"],
            "collision_count": 0,
            "families_checked": separation["families_checked"],
            "containers_checked": separation["containers_checked"],
            "decided_on": separation["decided_on"],
        },
    }


def verify(handoff: dict[str, Any]) -> dict[str, Any]:
    """Verify a built body or persisted immutable handoff against exact inputs."""
    keys = set(handoff)
    _require(
        keys in (set(BODY_KEYS), set(ENVELOPE_KEYS)), f"handoff key set is invalid: {sorted(keys)}"
    )
    if keys == set(ENVELOPE_KEYS):
        bare = {key: value for key, value in handoff.items() if key != "receipt_sha256"}
        _require(
            handoff["receipt_sha256"] == canonical_sha(bare), "handoff envelope digest mismatch"
        )
    expected = build()
    actual_body = {key: handoff[key] for key in BODY_KEYS}
    _require(actual_body == expected, "handoff does not equal the exact recomputed binding")
    return {
        "held": True,
        "schema": SCHEMA,
        "handoff_id": HANDOFF_ID,
        "declared_containers_sha256": expected["declared_containers_sha256"],
        "collision_count": 0,
    }


def freeze() -> dict[str, Any]:
    body = build()
    written = write_immutable(
        STEM, body, tool=Path(__file__).resolve(), protocol=None, pointer=False
    )
    return {**body, "written": written}


__all__ = ["HandoffRefused", "SCHEMA", "STEM", "build", "freeze", "verify"]
