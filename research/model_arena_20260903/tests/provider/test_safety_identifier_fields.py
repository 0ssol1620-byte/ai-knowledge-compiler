"""The secret guard runs per field, because a filename is not a token.

On 2026-09-03 the GLM-OCR canary aborted on its fourteenth page. Nothing had
leaked: the sample id
``parsebench:docs/layout/Informe-Anual-Consolidado-2024-ENG-compressed_p14#p0``
carries a 49-character mixed-case run, which is the shape ``_OPAQUE_TOKEN_RE``
looks for, and the guard fails closed. It stopped a canary while protecting
nothing, and the pod was returned with 13 failed pages and no receipts.

The three sample ids below are real rows of ``source_manifest.jsonl``. The
exemption they get covers exactly one rule -- the structural token shape -- and
exactly the fields the campaign derives from a document's own name. Everything
else in this file is the proof the rest of the guard is untouched.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest
from arena.provider.safety import IDENTIFIER_FIELDS, SecretLeak, assert_secret_free
from arena.provider.secrets import Secret

NAMESPACE = Path(__file__).resolve().parents[2]

# source_manifest.jsonl rows, verbatim. The lengths are what trips the shape
# rule: 49, 48 and 61 characters of mixed case and digits.
REAL_SAMPLE_IDS = (
    "parsebench:docs/layout/Informe-Anual-Consolidado-2024-ENG-compressed_p14#p0",
    "parsebench:docs/chart/P505350-59c98ca8-0803-4f23-b470-17f3dab010ab_p49#p0",
    "parsebench:docs/chart/US_Professional_Services_Partner_Compensation_Survey_2024_p21#p0",
)


def test_the_three_ids_are_still_rows_of_the_real_manifest() -> None:
    """A regression test against a value the campaign no longer uses is theatre."""

    wanted = set(REAL_SAMPLE_IDS)
    found: set[str] = set()
    with (NAMESPACE / "source_manifest.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["sample_id"] in wanted:
                found.add(row["sample_id"])
    assert found == wanted


@pytest.mark.parametrize("sample_id", REAL_SAMPLE_IDS)
def test_a_real_sample_id_is_not_a_credential(sample_id: str) -> None:
    record = {
        "schema": "tavonel.arena.canary_page.v1",
        "sample_id": sample_id,
        "case_key": "parsebench-506f8eb5f95d92a747d1a781",
        "inference_job_id": "e" * 64,
        "source_sha256": "sha256:" + "c" * 64,
        "image_path": "parsebench/inputs/parsebench-506f8eb5f95d92a747d1a781.png",
        "status": "FAILED",
    }
    assert_secret_free(record, context="canary page record")


def test_the_page_receipt_of_such_a_page_can_be_written(tmp_path: Path) -> None:
    """End to end through the writer that raised, not just the guard."""

    from arena.provider.safety import write_json_atomic, write_jsonl_append

    receipt = {
        "sample_id": REAL_SAMPLE_IDS[0],
        "case_key": "parsebench-506f8eb5f95d92a747d1a781",
        "inference_job_id": "f" * 64,
        "raw_output_sha256": "sha256:" + "a" * 64,
        "input_relative_path": "parsebench/inputs/parsebench-506f8eb5f95d92a747d1a781.png",
        "status": "SUCCESS",
    }
    write_json_atomic(tmp_path / "receipt.json", receipt, context="page receipt")
    write_jsonl_append(tmp_path / "pages.jsonl", receipt, context="canary page record")
    assert (tmp_path / "pages.jsonl").read_text(encoding="utf-8").count("\n") == 1


def test_a_real_token_in_a_free_text_field_is_still_caught() -> None:
    """``error_message`` is where a worker's own words land. It is not exempt."""

    token = secrets.token_urlsafe(48)[:64]
    assert len(token) == 64
    with pytest.raises(SecretLeak, match="64-character opaque token"):
        assert_secret_free(
            {"error_message": f"adapter refused: {token}"}, context="canary page record"
        )


@pytest.mark.parametrize("field", ["notes", "detail", "log_line", "statement"])
def test_other_free_text_fields_keep_the_full_rule_set(field: str) -> None:
    token = secrets.token_urlsafe(48)[:64]
    with pytest.raises(SecretLeak):
        assert_secret_free({field: token}, context="probe")


def test_a_string_with_no_field_around_it_is_held_to_the_full_rule_set() -> None:
    """``assert_secret_free(text, ...)`` has no name to exempt, and gets none."""

    with pytest.raises(SecretLeak, match="49-character opaque token"):
        assert_secret_free(REAL_SAMPLE_IDS[0], context="log fetch error")


@pytest.mark.parametrize("field", [*sorted(IDENTIFIER_FIELDS), "raw_output_sha256"])
def test_an_identifier_field_still_fails_on_a_credential_prefix(field: str) -> None:
    """Only the shape rule is lifted. The prefixes are not."""

    with pytest.raises(SecretLeak, match="credential prefix"):
        assert_secret_free({field: "rpa_" + "Ab1" * 14}, context="page receipt")


@pytest.mark.parametrize("field", sorted(IDENTIFIER_FIELDS))
def test_an_identifier_field_still_fails_on_a_loaded_credential(field: str) -> None:
    """The exact value of a secret this process holds is caught anywhere."""

    value = "r2fake4Guard3Test2Access1Key0Id9876"
    Secret(value, label="Access Key ID")
    with pytest.raises(SecretLeak, match="credential this process loaded"):
        assert_secret_free({field: f"prefix {value} suffix"}, context="page receipt")


def test_a_presigned_url_is_caught_even_under_an_identifier_field() -> None:
    with pytest.raises(SecretLeak, match="presigned-URL signature"):
        assert_secret_free(
            {"image_path": "https://x.invalid/o?X-Amz-Signature=abc"}, context="page receipt"
        )


def test_a_mapping_key_is_never_exempt() -> None:
    """A key is written by this codebase; a value can come from anywhere."""

    token = secrets.token_urlsafe(48)[:64]
    with pytest.raises(SecretLeak, match="64-character opaque token"):
        assert_secret_free({"sample_id": {token: "value"}}, context="page receipt")


def test_the_exemption_does_not_leak_into_a_nested_object() -> None:
    token = secrets.token_urlsafe(48)[:64]
    with pytest.raises(SecretLeak, match="64-character opaque token"):
        assert_secret_free({"case_key": {"error_message": token}}, context="page receipt")


def test_a_list_of_digests_under_one_name_is_treated_as_that_name() -> None:
    assert_secret_free(
        {"weights_sha256": ["sha256:" + "a" * 64, "sha256:" + "b" * 64]},
        context="page receipt",
    )


# ------------------------------------------------------------------- D88


def test_a_word_that_merely_ends_in_a_prefix_is_not_a_credential() -> None:
    """D88. ``disk-``, ``task-`` and ``mask-`` all end in ``sk-``.

    A bare substring test read those as an OpenAI key, so a ReadinessError
    quoting a container log could not be written to a driver receipt and the
    driver died after doing its work -- seventy times across six slices.
    """

    for text in (
        "worker never reached READY; container log: no disk-space left on device",
        "task-1 crashed during warmup",
        "loading mask-rcnn weights",
        "installed scikit-learn 1.4.2",
        "container disk-usage 78%",
    ):
        assert_secret_free({"error": text}, context="driver receipt")


def test_a_credential_is_still_caught_wherever_a_token_can_start() -> None:
    """Narrowing the rule must not open the door it was guarding."""

    for text in (
        "sk-abc123DEF456ghi",
        "token=sk-live-abc123DEF",
        "the key is sk-proj-abc123DEF",
        "Authorization: sk-abc123DEF456",
        "(sk-abc123DEF456)",
        '"sk-abc123DEF456"',
    ):
        with pytest.raises(SecretLeak):
            assert_secret_free({"error": text}, context="driver receipt")


def test_the_other_prefixes_keep_the_same_boundary_rule() -> None:
    assert_secret_free({"note": "workshf_notes"}, context="t")
    for text in ("hf_abc123DEF", "rpa_abc123DEF", "ghp_abc123DEF", "AKIAABCDEF123456"):
        with pytest.raises(SecretLeak):
            assert_secret_free({"note": text}, context="t")
