"""Static contract checks for the scheduler's least-privilege ACL query."""

from __future__ import annotations

from akc_scheduler.database import _POSTGRES_CAPABILITY_QUERY


def test_scheduler_acl_query_allows_verification_delivery_grants() -> None:
    sql = str(_POSTGRES_CAPABILITY_QUERY)

    assert "'email_verification_tokens'" in sql
    assert "'email_verification_deliveries'" in sql
    for column in (
        "status",
        "attempts",
        "available_at",
        "last_error_code",
        "provider_message_id",
        "delivered_at",
        "dead_lettered_at",
        "updated_at",
    ):
        assert f"'{column}'" in sql
