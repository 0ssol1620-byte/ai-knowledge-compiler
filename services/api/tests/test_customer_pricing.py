from decimal import Decimal

from akc_api.customer_pricing import capped_customer_charge, customer_charge_quote


def test_customer_quote_uses_page_prices_without_internal_credit_conversion() -> None:
    quote = customer_charge_quote(total_pages=100, native_pages=75)

    assert quote.minimum_usd == Decimal("4.00")
    assert quote.estimated_usd == Decimal("4.50")
    assert quote.maximum_usd == Decimal("6.00")


def test_customer_charge_never_exceeds_approved_maximum() -> None:
    assert capped_customer_charge(
        calculated_usd=Decimal("8.40"),
        approved_maximum_usd=Decimal("7.75"),
    ) == Decimal("7.75")


def test_customer_quote_clamps_invalid_native_page_count() -> None:
    quote = customer_charge_quote(total_pages=10, native_pages=99)

    assert quote.estimated_usd == Decimal("0.40")
    assert quote.maximum_usd == Decimal("0.60")
