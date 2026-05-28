from pathlib import Path

from dahua_money_watch.cloud_review import apply_escalation_event


def base_manual_event():
    return {
        "clip": "/runtime/clips/example.mp4",
        "payment_likely": True,
        "money_handover_visible": True,
        "payment_type": "cash",
        "handover_confidence": 0.7,
        "amount_status": "unknown",
        "amount": None,
        "currency": "unknown",
        "amount_confidence": 0.0,
        "visible_denominations": [],
        "evidence": {
            "handover": "Possible cash exchange.",
            "amount": "",
            "timestamp_hint": "00:06",
        },
        "recommended_action": "manual_review",
    }


def test_apply_escalation_promotes_manual_review_to_crm_compare_candidate():
    event = apply_escalation_event(
        base_manual_event(),
        {
            "recommended_action": "crm_compare_candidate",
            "payment_type": "cash",
            "amount_status": "estimated",
            "amount": 5000,
            "currency": "RUB",
            "amount_confidence": 0.62,
            "visible_denominations": [5000],
            "evidence": "A 5000 RUB note appears visible near the counter.",
        },
    )

    assert event["recommended_action"] == "crm_compare_candidate"
    assert event["amount_status"] == "estimated"
    assert event["amount"] == 5000
    assert event["currency"] == "RUB"
    assert event["evidence"]["escalation"] == "A 5000 RUB note appears visible near the counter."


def test_apply_escalation_can_auto_ignore_manual_review():
    event = apply_escalation_event(
        base_manual_event(),
        {
            "recommended_action": "ignore_auto",
            "payment_type": "unknown",
            "amount_status": "unknown",
            "amount": None,
            "currency": "unknown",
            "amount_confidence": 0,
            "visible_denominations": [],
            "evidence": "Hands move near the counter, but no payment instrument is visible.",
        },
    )

    assert event["recommended_action"] == "ignore"
    assert event["payment_likely"] is False
    assert event["amount"] is None

