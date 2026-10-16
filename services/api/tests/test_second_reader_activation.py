"""Registry identity and tenant gate regressions for measured second readers."""

from types import SimpleNamespace

from akc_api.routing_runtime import _registry_route, _route_enabled
from akc_router import FeatureFlags, Route


def test_second_reader_identity_rejects_incidental_substrings() -> None:
    assert (
        _registry_route(SimpleNamespace(endpoint="provisioned_reader", model_id="improviser"))
        is None
    )
    assert (
        _registry_route(SimpleNamespace(endpoint="infinity_workspace", model_id="flashlight"))
        is None
    )
    assert (
        _registry_route(SimpleNamespace(endpoint="ovisocr2_reader", model_id="OvisOCR2"))
        == Route.OVIS_VL
    )
    assert (
        _registry_route(
            SimpleNamespace(endpoint="infinity_parser2_flash", model_id="Infinity-Parser2-Flash")
        )
        == Route.INFINITY_FLASH
    )


def test_second_readers_require_separate_tenant_flags_after_registry_readiness() -> None:
    closed = FeatureFlags()
    assert not _route_enabled(Route.OVIS_VL, closed, external_allowed=True)
    assert not _route_enabled(Route.INFINITY_FLASH, closed, external_allowed=True)

    ovis_only = FeatureFlags(ovis_vl_enabled=True)
    assert _route_enabled(Route.OVIS_VL, ovis_only, external_allowed=False)
    assert not _route_enabled(Route.INFINITY_FLASH, ovis_only, external_allowed=False)

    flash_only = FeatureFlags(infinity_flash_enabled=True)
    assert not _route_enabled(Route.OVIS_VL, flash_only, external_allowed=False)
    assert _route_enabled(Route.INFINITY_FLASH, flash_only, external_allowed=False)
