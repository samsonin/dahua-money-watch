import json
from pathlib import Path

from dahua_money_watch.report import (
    accounting_status,
    build_daily_report_payload,
    build_daily_report_rows,
    expected_clip_name,
    json_event_from_row,
    load_latest_cloud_review_rows,
    load_reviewed_event_rows,
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


def test_load_cloud_review_rows_reads_source_date_subdirectories(tmp_path):
    legacy_clip = "/runtime/clips/legacy.mp4"
    source_date_clip = "/runtime/clips/source-date.mp4"
    write_jsonl(tmp_path / "cloud-reviews" / "cloud-reviewed-2026-05-27.jsonl", [{"clip": legacy_clip}])
    write_jsonl(
        tmp_path / "cloud-reviews" / "by-source-date" / "2026-05-18" / "cloud-reviewed-2026-05-18.jsonl",
        [{"clip": source_date_clip}],
    )

    rows = list(load_latest_cloud_review_rows(tmp_path))

    assert {row["clip"] for row in rows} == {legacy_clip, source_date_clip}


def test_load_reviewed_event_rows_reads_source_date_subdirectories(tmp_path):
    legacy = {"file": "/archive/2026-05-27/001/dav/09/legacy.dav"}
    source_date = {"file": "/archive/2026-05-18/001/dav/09/source-date.dav"}
    write_jsonl(tmp_path / "events" / "reviewed-2026-05-27.jsonl", [legacy])
    write_jsonl(
        tmp_path / "events" / "by-source-date" / "2026-05-18" / "reviewed-2026-05-18.jsonl",
        [source_date],
    )
    write_jsonl(
        tmp_path / "events" / "by-source-date" / "2026-05-18" / "events-2026-05-18.jsonl",
        [{"file": "/archive/2026-05-18/001/dav/09/raw-event.dav"}],
    )

    rows = list(load_reviewed_event_rows(tmp_path))

    assert rows == [source_date, legacy]


def test_accounting_status_marks_crm_compare_candidate_ready():
    assert accounting_status("crm_compare_candidate", {}) == "ready_for_candidate_comparison"


def test_json_event_marks_confirmed_handover_candidate_with_evidence_clip():
    event = json_event_from_row(
        {
            "source_date": "2026-05-27",
            "event_start_time": "15:08:32",
            "event_end_time": "15:08:35",
            "source_file": "15.08.16-15.09.32[M][0@0][0].dav",
            "clip": "candidate.mp4",
            "local_class": "high",
            "local_score": "0.707",
            "metadata_status": "matched",
            "final_action": "crm_compare_candidate",
            "payment_likely": "true",
            "money_handover_visible": "true",
            "payment_type": "cash",
            "handover_confidence": "0.9",
            "amount_status": "estimated",
            "amount": 1000,
            "currency": "RUB",
            "amount_confidence": "0.6",
            "visible_denominations": "[1000]",
            "timestamp_hint": "00:06",
            "handover_evidence": "Cash handover is visible.",
            "amount_evidence": "A note may be 1000 RUB.",
            "review_error": "",
            "handover_confirmed": True,
            "handover_clip": "handover-clips/by-source-date/2026-05-27/candidate_handover.mp4",
        }
    )

    assert event["review"]["handover_confirmed"] is True
    assert event["evidence"]["handover_clip"] == "handover-clips/by-source-date/2026-05-27/candidate_handover.mp4"
    assert event["accounting"]["comparison_status"] == "handover_confirmed_amount_estimated"
