"""D-V-llamaparse: Parse v2, ``tier: agentic`` with a dated ``version``.

Wire facts come from competitor-protocol-receipts/web/llamaparse-tiers.html (sha256
a12df665…, 2026-10-17): upload the file (``purpose parse``, response ``.id``), start a job with
``POST https://api.cloud.llamaindex.ai/api/v2/parse`` and ``{"file_id", "tier", "version"}``
(response ``.id``), then poll the job with ``expand markdown`` every 2 s until ``job.status`` is
COMPLETED, FAILED or CANCELLED; the text is ``markdown.pages[].markdown`` and a failed job says
``job.error_message``. "tier and version are both required on every parse request", and only a
dated version is reproducible, so ``latest`` is refused. ``metadata.version`` and
``metadata.usage.num_pages_billed`` are read from the completed job (llamaparse-docs-pricing.html
sha256 2eabf853…). The upload and job-status URLs were not captured, so they are None.
"""

from __future__ import annotations

import re
from typing import Any

from .base import Adapter, Calls, Document, Failure, Pin, Request, ResponseShape, Status

PARSE_URL = "https://api.cloud.llamaindex.ai/api/v2/parse"
TIERS = ("fast", "cost_effective", "agentic", "agentic_plus")
TERMINAL_FAILURES = ("FAILED", "CANCELLED")
POLL_INTERVAL_S = 2.0
RECEIPT = "competitor-protocol-receipts/web/llamaparse-tiers.html sha256 a12df665"


def _string_id(payload: Any, operation: str) -> str:
    value = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value:
        raise Failure(Status.MALFORMED_RESPONSE, f"{operation}: response has no string id")
    return value


class LlamaParseAdapter(Adapter):
    vendor = "llamaparse"
    endpoint = PARSE_URL
    wire_source = f"documented flow: {RECEIPT}; upload and job-status URLs not captured"
    default_shape = ResponseShape(
        source=RECEIPT,
        markdown=("markdown", "pages", "*", "markdown"),
        page_count=("markdown", "pages"),
        usage={
            "num_pages_billed": ("metadata", "usage", "num_pages_billed"),
            "version": ("metadata", "version"),
        },
    )

    def validate_config(self, pin: Pin) -> None:
        if pin.config.get("tier") not in TIERS:
            raise ValueError(f"llamaparse: tier must be one of {TIERS}")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", pin.config.get("version", "")):
            raise ValueError("llamaparse: version must be a published date; 'latest' drifts")

    def exchange(self, document: Document, pin: Pin, calls: Calls) -> Any:
        def request(operation: str, method: str, url: str | None, **kwargs: Any) -> Any:
            return calls.send(
                Request(operation, method, url, pin.api_key_env, pin.timeout_s, **kwargs)
            )

        upload = request(
            "upload_file", "POST", None, params={"purpose": "parse"}, file_bytes=document.pdf
        )
        body = {
            "file_id": _string_id(upload, "upload_file"),
            "tier": pin.config["tier"],
            "version": pin.config["version"],
        }
        job_id = _string_id(request("create_job", "POST", PARSE_URL, json_body=body), "create_job")
        deadline = self._clock() + pin.timeout_s
        while True:
            result = request(
                "get_job", "GET", None, params={"job_id": job_id, "expand": "markdown"}
            )
            job = result.get("job") if isinstance(result, dict) else None
            status = job.get("status") if isinstance(job, dict) else None
            if not isinstance(job, dict) or not isinstance(status, str):
                raise Failure(Status.MALFORMED_RESPONSE, "get_job: no job.status")
            if status == "COMPLETED":
                return result
            if status in TERMINAL_FAILURES:
                message = job.get("error_message")
                raise Failure(Status.VENDOR_JOB_FAILED, f"job {status}: {message}")
            if self._clock() >= deadline:
                raise Failure(Status.TIMEOUT, f"job still {status} after {pin.timeout_s} s")
            self._sleep(POLL_INTERVAL_S)
