"""Synthetic interruption, restart, integrity and cross-instance replay acceptance."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from akc_cir.base import canonical_json, sha256_digest
from akc_product_core.api import ProductCoreService
from akc_product_core.contracts import PreviousWorldSnapshot

from .test_product_core_api import SECRET, _signed
from .test_product_core_fragments import RELEASE, _document, _request


def _service(path: Path, release: str = RELEASE) -> ProductCoreService:
    return ProductCoreService(hmac_secret=SECRET, core_release_digest=release, journal_path=path)


def _input():
    return _request(
        tuple(_document(f"doc-{i}", f"Revenue is {i + 100} million won.") for i in range(3)),
        request_id="journal-first",
    )


def _compile(service, request):
    body = canonical_json(request.model_dump(mode="json", by_alias=True)).encode()
    return service.compile(body=body, headers=_signed(body, request.request_id))


def test_restart_replays_exact_candidate_without_extraction_and_rebinds_attempt(tmp_path):
    path = tmp_path / "compile.sqlite"
    request = _input()
    status, first = _compile(_service(path), request)
    assert status == 200
    retry = request.model_copy(
        update={
            "request_id": "journal-retry",
            "requested_at": request.requested_at + timedelta(days=1),
            "route": request.route.model_copy(update={"max_latency_ms": 1000}),
        }
    )
    restarted = _service(path)
    with patch.object(
        restarted.compiler, "compile_fragments", side_effect=AssertionError("recomputed")
    ):
        status, replay = _compile(restarted, retry)
    assert status == 200
    assert replay["candidate"] == first["candidate"]
    assert replay["receipt"]["requestId"] == "journal-retry"
    assert replay["receipt"]["inputSha256"] != first["receipt"]["inputSha256"]
    assert first["receipt"]["requestId"] == "journal-first"


def test_interrupted_second_fragment_resumes_only_uncommitted_work(tmp_path):
    path = tmp_path / "compile.sqlite"
    service = _service(path)
    request = _input()
    extract = service.compiler.compile_fragments
    calls = []

    def interrupt(request, keys):
        calls.append(keys)
        if len(calls) == 2:
            raise RuntimeError("synthetic worker death")
        return extract(request, keys)

    with (
        patch.object(service.compiler, "compile_fragments", side_effect=interrupt),
        pytest.raises(RuntimeError, match="worker death"),
    ):
        _compile(service, request)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM compile_fragments").fetchone() == (1,)
        assert connection.execute("SELECT payload FROM compile_jobs").fetchone() == (None,)
    restarted = _service(path)
    retry = request.model_copy(
        update={
            "request_id": "resumed-attempt",
            "requested_at": request.requested_at + timedelta(days=1),
        }
    )
    with patch.object(
        restarted.compiler, "compile_fragments", wraps=restarted.compiler.compile_fragments
    ) as resumed:
        status, result = _compile(restarted, retry)
    assert status == 200
    assert resumed.call_count == 2
    original = _compile(
        ProductCoreService(hmac_secret=SECRET, core_release_digest=RELEASE), request
    )[1]
    assert result["candidate"] == original["candidate"]
    assert result["receipt"]["outputSha256"] == original["receipt"]["outputSha256"]
    assert result["receipt"]["requestId"] == "resumed-attempt"


def test_reducer_failure_keeps_fragments_but_never_partial_candidate(tmp_path):
    path = tmp_path / "compile.sqlite"
    service = _service(path)
    request = _input()
    with (
        patch.object(
            service.compiler, "reduce_fragments", side_effect=RuntimeError("reducer death")
        ),
        pytest.raises(RuntimeError, match="reducer death"),
    ):
        _compile(service, request)
    restarted = _service(path)
    with patch.object(
        restarted.compiler, "compile_fragments", side_effect=AssertionError("recomputed")
    ):
        assert _compile(restarted, request)[0] == 200


@pytest.mark.parametrize("change", ["bytes", "release", "collection", "scope"])
def test_restart_retains_immutable_key_conflict(change, tmp_path):
    path = tmp_path / "compile.sqlite"
    request = _input()
    assert _compile(_service(path), request)[0] == 200
    service = _service(path, "sha256:" + "b" * 64 if change == "release" else RELEASE)
    if change == "bytes":
        request = request.model_copy(update={"documents": (_document("doc-0", "Changed bytes."),)})
    elif change == "collection":
        request = request.model_copy(update={"collection_id": "collection-other"})
    elif change == "scope":
        request = request.model_copy(update={"workspace_id": "workspace-other"})
        # A new authenticated workspace has its own independent idempotency namespace.
        assert _compile(service, request)[0] == 200
        return
    assert _compile(service, request) == (409, {"code": "CORE_IDEMPOTENCY_CONFLICT"})


def test_competing_instances_commit_each_fragment_and_reduce_once(tmp_path):
    path = tmp_path / "compile.sqlite"
    services = [_service(path) for _ in range(4)]
    request = _input()
    with ExitStack() as stack:
        extractors = [
            stack.enter_context(
                patch.object(
                    service.compiler, "compile_fragments", wraps=service.compiler.compile_fragments
                )
            )
            for service in services
        ]
        reducers = [
            stack.enter_context(
                patch.object(
                    service.compiler, "reduce_fragments", wraps=service.compiler.reduce_fragments
                )
            )
            for service in services
        ]
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda service: _compile(service, request), services))
        assert sum(extractor.call_count for extractor in extractors) == 3
        assert sum(reducer.call_count for reducer in reducers) == 1
    assert all(result == results[0] for result in results)
    assert results[0][0] == 200
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM compile_jobs").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM compile_fragments").fetchone() == (3,)


@pytest.mark.parametrize("record", ["candidate", "fragment", "schema", "receipt", "accepted"])
def test_corrupt_journal_fails_closed(record, tmp_path):
    path = tmp_path / "compile.sqlite"
    service = _service(path)
    request = _input()
    if record == "fragment":
        with (
            patch.object(service.compiler, "reduce_fragments", side_effect=RuntimeError),
            pytest.raises(RuntimeError),
        ):
            _compile(service, request)
    else:
        assert _compile(service, request)[0] == 200
    with sqlite3.connect(path) as connection:
        if record == "candidate":
            connection.execute("UPDATE compile_jobs SET payload='{}'")
        elif record == "schema":
            connection.execute(
                "UPDATE compile_jobs SET payload='{}', payload_digest=?", (sha256_digest("{}"),)
            )
        elif record == "receipt":
            payload = json.loads(
                connection.execute("SELECT payload FROM compile_jobs").fetchone()[0]
            )
            payload["receipt"]["requestId"] = "wrong-attempt"
            encoded = canonical_json(payload)
            connection.execute(
                "UPDATE compile_jobs SET payload=?, payload_digest=?",
                (encoded, sha256_digest(encoded)),
            )
        elif record == "accepted":
            payload = json.loads(
                connection.execute("SELECT accepted_work FROM compile_jobs").fetchone()[0]
            )
            payload["request"]["collectionId"] = "wrong-collection"
            encoded = canonical_json(payload)
            connection.execute(
                "UPDATE compile_jobs SET accepted_work=?, accepted_digest=?",
                (encoded, sha256_digest(encoded)),
            )
        else:
            connection.execute("UPDATE compile_fragments SET payload='{}'")
    assert _compile(_service(path), request) == (503, {"code": "CORE_JOURNAL_UNAVAILABLE"})


def test_restart_authentication_and_privacy_gates_still_precede_replay(tmp_path):
    path = tmp_path / "compile.sqlite"
    request = _input()
    assert _compile(_service(path), request)[0] == 200
    restarted = _service(path)
    body = canonical_json(request.model_dump(mode="json", by_alias=True)).encode()
    assert restarted.compile(body=body, headers={})[0] == 401
    private = request.model_copy(
        update={
            "route": request.route.model_copy(update={"privacy_policy": "approved_customer_data"})
        }
    )
    assert _compile(restarted, private) == (403, {"code": "CORE_CUSTOMER_DATA_DISABLED"})


def test_killed_process_rolls_back_inflight_fragment_and_resumes_committed_fragment(tmp_path):
    path = tmp_path / "compile.sqlite"
    request = _input()
    body_path = tmp_path / "request.json"
    body_path.write_text(
        canonical_json(request.model_dump(mode="json", by_alias=True)), encoding="utf-8"
    )
    script = """
import os, sys
from pathlib import Path
from datetime import UTC, datetime
from akc_product_core.api import ProductCoreService
from akc_product_core.auth import sign_product_core_request
from akc_product_core.contracts import ProductCoreCompileRequest
body = Path(sys.argv[2]).read_bytes()
request = ProductCoreCompileRequest.model_validate_json(body)
secret = b"synthetic-test-secret-at-least-32-bytes"
service = ProductCoreService(hmac_secret=secret, core_release_digest=sys.argv[3],
    journal_path=sys.argv[1])
extract = service.compiler.compile_fragments
calls = 0
def killed(request, keys):
    global calls
    calls += 1
    if calls == 2:
        os._exit(73)
    return extract(request, keys)
service.compiler.compile_fragments = killed
headers = sign_product_core_request(body=body, request_id=request.request_id,
    timestamp=int(datetime.now(tz=UTC).timestamp()), secret=secret)
service.compile(body=body, headers=headers)
"""
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    result = subprocess.run(  # noqa: S603 - fixed synthetic script, no shell or external input
        [sys.executable, "-c", script, str(path), str(body_path), RELEASE],
        env=environment,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 73, result.stderr.decode(errors="replace")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM compile_fragments").fetchone() == (1,)
        assert connection.execute("SELECT payload FROM compile_jobs").fetchone() == (None,)
    restarted = _service(path)
    with patch.object(
        restarted.compiler, "compile_fragments", wraps=restarted.compiler.compile_fragments
    ) as resumed:
        status, candidate = _compile(restarted, request)
    assert status == 200
    assert resumed.call_count == 2
    assert candidate["receipt"]["candidatePromotion"] is False


def test_incremental_resume_preserves_parent_and_full_equivalence(tmp_path):
    path = tmp_path / "compile.sqlite"
    service = _service(path)
    initial_request = _input()
    initial = service.compiler.compile(initial_request, input_sha256=sha256_digest("initial"))
    previous = PreviousWorldSnapshot(
        world_state_id=initial.candidate.world_state_id,
        manifest_digest=initial.candidate.manifest_digest,
        units=initial.candidate.units,
        artifact_hashes=initial.candidate.artifact_hashes,
    )
    request = _request(
        (*initial_request.documents[1:], _document("new-doc", "New policy is approved.")),
        request_id="incremental-journal",
        previous=previous,
    )
    with (
        patch.object(service.compiler, "reduce_fragments", side_effect=RuntimeError),
        pytest.raises(RuntimeError),
    ):
        _compile(service, request)
    restarted = _service(path)
    with patch.object(
        restarted.compiler, "compile_fragments", side_effect=AssertionError("recomputed")
    ):
        status, result = _compile(restarted, request)
    assert status == 200
    assert result["receipt"]["equivalence"] == "passed"
    assert result["candidate"]["parentWorldStateId"] == previous.world_state_id
    assert (
        result["candidate"]
        == _compile(ProductCoreService(hmac_secret=SECRET, core_release_digest=RELEASE), request)[
            1
        ]["candidate"]
    )


def test_journal_storage_failure_returns_retryable_error(tmp_path):
    service = _service(tmp_path / "compile.sqlite")
    with patch.object(service.journal, "_connect", side_effect=sqlite3.OperationalError("offline")):
        assert _compile(service, _input()) == (503, {"code": "CORE_JOURNAL_UNAVAILABLE"})
