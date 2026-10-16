"""No-op incremental revisions retain equivalence across distinct attempts."""

from datetime import timedelta

import pytest
from akc_product_core import ProductCoreCompiler
from akc_product_core.contracts import PreviousWorldSnapshot

from tests.unit.test_product_core_fragments import RELEASE, _document, _request, _sha


@pytest.mark.parametrize("hours", [0, 1])
def test_unchanged_incremental_revision_passes_full_rebuild_equivalence(hours: int) -> None:
    compiler = ProductCoreCompiler(core_release_digest=RELEASE)
    documents = (_document("noop", "The board approved the policy."),)
    initial_request = _request(documents, request_id="noop-initial")
    initial = compiler.compile(initial_request, input_sha256=_sha("noop-initial"))
    previous = PreviousWorldSnapshot(
        world_state_id=initial.candidate.world_state_id,
        manifest_digest=initial.candidate.manifest_digest,
        units=initial.candidate.units,
        artifact_hashes=initial.candidate.artifact_hashes,
    )
    revision = _request(documents, request_id="noop-revision", previous=previous).model_copy(
        update={"requested_at": initial_request.requested_at + timedelta(hours=hours)}
    )
    result = compiler.compile(revision, input_sha256=_sha("noop-revision"))
    assert result.receipt.equivalence == "passed"
    assert result.status == "completed"
    assert result.candidate.parent_world_state_id == initial.candidate.world_state_id
    assert result.receipt.work_avoided_artifacts == 3
    assert result.receipt.rebuilt_artifacts == 4
