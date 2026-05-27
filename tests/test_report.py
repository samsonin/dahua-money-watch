import json
from pathlib import Path

from dahua_money_watch.report import (
    build_daily_report_payload,
    build_daily_report_rows,
    expected_clip_name,
    load_latest_cloud_review_rows,
    parse_clip_event_times,
)


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_expected_clip_name_matches_artifact_writer():
    event = {
        "file": "/archive/2026-05-27/001/dav/19/19.57.17-20.00.00[M][0@0][0].dav",
        "start_time": "19:59:08",
        "end_time": "19:59:18",
        "combined_score": 0.374,
        "class": "low",
    }

    assert expected_clip_name(event) == "low_0p374_195908-195918_19.57.17-20.00.00_M_0_0_0_.mp4"


def test_parse_clip_event_times():
    assert parse_clip_event_times("high_0p707_150832-150835_15.08.16-15.09.32_M_0_0_0_.mp4") == (
        "15:08:32",
        "15:08:35",
    )


def test_build_daily_report_rows_joins_cloud_and_local_metadata(tmp_path):
    event = {
        "file": "/archive/2026-05-27/001/dav/19/19.57.17-20.00.00[M][0@0][0].dav",
        "start_time": "19:59:08",
        "end_time": "19:59:18",
        "combined_score": 0.374,
        "class": "low",
    }
    clip = tmp_path / "clips" / expected_clip_name(event)
    cloud = {
        "clip": str(clip),
        "event": {
            "recommended_action": "manual_review",
            "payment_likely": True,
            "money_handover_visible": True,
            "payment_type": "cash",
            "handover_confidence": 0.8,
            "amount_status": "unknown",
            "amount": None,
            "currency": "unknown",
            "amount_confidence": 0.0,
            "visible_denominations": [],
            "evidence": {
                "handover": "Cash was handed over.",
                "amount": "Denominations are not visible.",
                "timestamp_hint": "00:11",
            },
        },
    }
    write_jsonl(tmp_path / "events" / "reviewed-2026-05-27.jsonl", [event])
    write_jsonl(tmp_path / "cloud-reviews" / "cloud-reviewed-2026-05-27.jsonl", [cloud])

    rows = build_daily_report_rows(tmp_path, "2026-05-27")

    assert len(rows) == 1
    assert rows[0]["source_date"] == "2026-05-27"
    assert rows[0]["event_start_time"] == "19:59:08"
    assert rows[0]["final_action"] == "manual_review"
    assert rows[0]["payment_type"] == "cash"
    assert rows[0]["metadata_status"] == "matched"

    payload = build_daily_report_payload(tmp_path, "2026-05-27")
    assert payload["status"] == "complete"
    assert payload["progress"]["candidate_clips"] == 1
    assert payload["events"][0]["review"]["payment_likely"] is True
    assert payload["events"][0]["amount"]["amount"] is None
    assert payload["events"][0]["accounting"]["comparison_status"] == "manual_review_required"


def test_latest_cloud_review_prefers_success_after_error(tmp_path):
    clip = "/runtime/clips/example.mp4"
    write_jsonl(
        tmp_path / "cloud-reviews" / "cloud-reviewed-2026-05-27.jsonl",
        [
            {"clip": clip, "error": "temporary auth failure"},
            {"clip": clip, "event": {"recommended_action": "ignore"}},
        ],
    )

    rows = list(load_latest_cloud_review_rows(tmp_path))

    assert len(rows) == 1
    assert "error" not in rows[0]
