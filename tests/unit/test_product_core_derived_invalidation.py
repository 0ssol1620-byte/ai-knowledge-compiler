"""Fixed source bytes do not imply fixed extraction or trust inputs."""

import pytest
from akc_cir.models import BBox1000
from akc_product_core import ProductCoreCompiler
from akc_product_core.contracts import PreviousWorldSnapshot

from tests.unit.test_product_core_bridge import RELEASE, _document, _request, _sha


@pytest.mark.parametrize("change", ["authority", "geometry", "ocr"])
def test_derived_input_change_rebuilds_only_affected_units(change: str) -> None:
    compiler = ProductCoreCompiler(core_release_digest=RELEASE)
    changed = _document("changing", "TAVONEL reported revenue of 100 million won.")
    untouched = _document("untouched", "The board approved the policy.")
    initial = compiler.compile(
        _request((changed, untouched), request_id="derived-initial"),
        input_sha256=_sha("derived-initial"),
    )
    previous = PreviousWorldSnapshot(
        world_state_id=initial.candidate.world_state_id,
        manifest_digest=initial.candidate.manifest_digest,
        units=initial.candidate.units,
        artifact_hashes=initial.candidate.artifact_hashes,
    )
    updates = {
        "authority": {"authority": "informal"},
        "geometry": {"bbox1000": BBox1000((120, 140, 900, 260))},
        "ocr": {"text": "TAVONEL reported revenue of 120 million won."},
    }[change]
    revised = changed.model_copy(
        update={"regions": (changed.regions[0].model_copy(update=updates),)}
    )
    assert revised.content_sha256 == changed.content_sha256
    result = compiler.compile(
        _request((revised, untouched), request_id=f"derived-{change}", previous=previous),
        input_sha256=_sha(f"derived-{change}"),
    )
    assert result.receipt.equivalence == "passed"
    assert result.status == "completed"
    assert result.receipt.rebuilt_artifacts == 7
    assert result.receipt.work_avoided_artifacts == 3
    old_units = {unit.source_id: unit for unit in initial.candidate.units}
    for unit in result.candidate.units:
        assert unit.logical_id == old_units[unit.source_id].logical_id
        assert unit.source_version_id == old_units[unit.source_id].source_version_id
    affected_id = old_units[changed.source_id].logical_id
    unaffected_id = old_units[untouched.source_id].logical_id
    for key, digest in result.candidate.artifact_hashes.items():
        if key.endswith("/" + affected_id):
            assert digest != initial.candidate.artifact_hashes[key]
        elif key.endswith("/" + unaffected_id):
            assert digest == initial.candidate.artifact_hashes[key]
