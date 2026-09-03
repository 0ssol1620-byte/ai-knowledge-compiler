from akc_api.plan_catalog import canonical_plan_code, plan_entitlement


def test_legacy_plan_codes_resolve_to_canonical_commercial_names() -> None:
    assert canonical_plan_code("free") == "evaluation"
    assert canonical_plan_code("personal") == "developer"
    assert canonical_plan_code("pro") == "developer"
    assert canonical_plan_code("studio") == "team"


def test_canonical_launch_entitlements_match_public_allowances() -> None:
    evaluation = plan_entitlement("evaluation")
    developer = plan_entitlement("developer")
    team = plan_entitlement("team")

    assert evaluation.included_standard_pages == 500
    assert developer.monthly_price_usd == 29
    assert developer.included_standard_pages == 500
    assert developer.active_connectors == 1
    assert team.monthly_price_usd == 99
    assert team.included_standard_pages == 2_500
    assert team.seats == 5


def test_unqualified_tiers_do_not_publish_unmeasured_allowances() -> None:
    assert plan_entitlement("scale").commercially_qualified is False
    assert plan_entitlement("scale").included_standard_pages is None
    assert plan_entitlement("enterprise").commercially_qualified is False
