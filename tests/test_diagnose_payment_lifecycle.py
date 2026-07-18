from scripts.diagnose_payment_lifecycle import (
    _classify_root_cause,
    _sanitize_subscription,
    _sanitize_transaction,
    _webhook_matches,
)


def test_transaction_sanitizer_excludes_customer_and_payment_details():
    result = _sanitize_transaction(
        {
            "id": "txn_123",
            "status": "completed",
            "origin": "web",
            "subscription_id": "sub_123",
            "customer_id": "ctm_secret",
            "custom_data": {"private": "value"},
            "payments": [{"method_details": {"card": "secret"}}],
        }
    )

    assert result == {
        "id": "txn_123",
        "status": "completed",
        "origin": "web",
        "billed_at": None,
        "created_at": None,
        "updated_at": None,
        "subscription_id": "sub_123",
    }


def test_subscription_sanitizer_exposes_status_without_provider_secrets():
    result = _sanitize_subscription(
        {
            "id": "sub_123",
            "status": "active",
            "scheduled_change": None,
            "customer_id": "ctm_secret",
            "items": [{"price": {"unit_price": {"amount": "2900"}}}],
        }
    )

    assert result["id"] == "sub_123"
    assert result["status"] == "active"
    assert result["scheduled_change_present"] is False
    assert "customer_id" not in result
    assert "items" not in result


def test_webhook_match_uses_transaction_subscription_or_safe_local_identity():
    assert _webhook_matches(
        {"event_type": "transaction.completed", "data": {"id": "txn_123"}},
        transaction_id="txn_123",
        subscription_id="sub_123",
        local_ids=set(),
    )
    assert _webhook_matches(
        {"event_type": "subscription.updated", "data": {"id": "sub_123"}},
        transaction_id="txn_123",
        subscription_id="sub_123",
        local_ids=set(),
    )
    assert _webhook_matches(
        {
            "event_type": "transaction.created",
            "data": {"custom_data": {"payment_attempt_uuid": "attempt-uuid"}},
        },
        transaction_id="txn_missing",
        subscription_id="sub_missing",
        local_ids={"attempt-uuid"},
    )
    assert not _webhook_matches(
        {"event_type": "transaction.completed", "data": {"id": "txn_other"}},
        transaction_id="txn_123",
        subscription_id="sub_123",
        local_ids=set(),
    )


def test_completed_provider_transaction_without_local_event_is_identified():
    assert (
        _classify_root_cause(
            paddle_transaction_status="completed",
            billing_status="payment_processing",
            transaction_completed_events=[],
            matching_change_request_count=0,
        )
        == "completed_provider_transaction_missing_local_webhook"
    )


def test_processed_completed_event_with_stale_state_is_identified():
    assert (
        _classify_root_cause(
            paddle_transaction_status="completed",
            billing_status="payment_processing",
            transaction_completed_events=[{"processing_status": "processed"}],
            matching_change_request_count=0,
        )
        == "completed_webhook_processed_without_lifecycle_transition"
    )


def test_completed_event_with_matching_change_request_flags_interception_risk():
    assert (
        _classify_root_cause(
            paddle_transaction_status="completed",
            billing_status="payment_processing",
            transaction_completed_events=[{"processing_status": "processed"}],
            matching_change_request_count=1,
        )
        == "completed_webhook_processed_with_matching_subscription_change"
    )
