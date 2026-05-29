import json
from pathlib import Path

from dahua_money_watch.handover_evidence import build_handover_evidence_payload, parse_timestamp_hint
from dahua_money_watch.report import expected_clip_name


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_parse_timestamp_hint_accepts_minute_second_and_hour_formats():
    assert parse_timestamp_hint("00:06") == 6.0
    assert parse_timestamp_hint("01:02:03") == 3723.0
    assert parse_timestamp_hint("6") == 6.0
    assert parse_timestamp_hint("") is None


def test_build_handover_evidence_payload_filters_confirmed_candidates_and_writes_audio_clip(tmp_path, monkeypatch):
    source = tmp_path / "archive" / "2026-05-27" / "001" / "dav" / "15" / "15.08.16-15.09.32[M][0@0][0].dav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"dav")
    event = {
        "file": str(source),
        "start_time": "15:08:32",
        "end_time": "15:08:35",
        "start_offset_s": 16.0,
        "end_offset_s": 19.0,
        "combined_score": 0.707,
        "class": "high",
    }
    clip = tmp_path / "clips" / expected_clip_name(event)
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"mp4")
    write_jsonl(tmp_path / "events" / "by-source-date" / "2026-05-27" / "reviewed-2026-05-27.jsonl", [event])
    cloud_path = tmp_path / "cloud-reviewed.jsonl"
    write_jsonl(
        cloud_path,
        [
            {
                "clip": str(clip),
                "event": {
                    "recommended_action": "crm_compare_candidate",
                    "payment_likely": True,
                    "money_handover_visible": True,
                    "payment_type": "cash",
                    "handover_confidence": 0.9,
                    "amount_status": "estimated",
                    "amount": 1000,
                    "currency": "RUB",
                    "amount_confidence": 0.6,
                    "visible_denominations": [1000],
                    "evidence": {"timestamp_hint": "00:06", "handover": "Cash visible.", "amount": "Possible 1000."},
                },
            },
            {
                "clip": str(clip.with_name("weak.mp4")),
                "event": {
                    "recommended_action": "crm_compare_candidate",
                    "payment_likely": True,
                    "money_handover_visible": True,
                    "payment_type": "cash",
                    "handover_confidence": 0.4,
                    "amount_status": "unknown",
                    "amount": None,
                    "currency": "unknown",
                    "amount_confidence": 0,
                    "visible_denominations": [],
                    "evidence": {},
                },
            },
        ],
    )
    calls = []

    def fake_extract_clip(source_path, target_path, start_s, duration_s, crf, preset, audio):
        calls.append((source_path, target_path, start_s, duration_s, crf, preset, audio))
        target_path.parent.mkdir(parents=True)
        target_path.write_bytes(b"handover")

    monkeypatch.setattr("dahua_money_watch.handover_evidence.extract_clip", fake_extract_clip)

    payload = build_handover_evidence_payload(
        tmp_path,
        {
            "review": {"pre_padding_seconds": 5.0},
            "clip": {"crf": 24, "preset": "fast"},
            "evidence": {"clip_base_url": "https://clips.example/evidence-clips"},
        },
        cloud_path,
        min_handover_confidence=0.8,
        pre_seconds=3.0,
        post_seconds=5.0,
    )

    assert payload["summary"]["total"] == 1
    assert payload["summary"]["crm_compare_candidate"] == 1
    assert payload["progress"]["source_cloud_review_rows"] == 2
    assert payload["events"][0]["review"]["handover_confirmed"] is True
    assert payload["events"][0]["amount"]["amount"] == 1000
    assert payload["events"][0]["accounting"]["comparison_status"] == "handover_confirmed_amount_estimated"
    assert payload["events"][0]["evidence"]["handover_clip"].endswith("_handover.mp4")
    assert payload["events"][0]["evidence"]["handover_clip_url"].startswith("https://clips.example/evidence-clips/")
    assert len(calls) == 1
    assert calls[0][0] == source
    assert calls[0][2] == 14.0
    assert calls[0][3] == 8.0
    assert calls[0][6] is True


def test_build_handover_evidence_payload_skips_confirmed_candidate_when_clip_cannot_be_saved(tmp_path, monkeypatch):
    source = tmp_path / "archive" / "2026-05-27" / "001" / "dav" / "15" / "missing.dav"
    event = {
        "file": str(source),
        "start_time": "15:08:32",
        "end_time": "15:08:35",
        "start_offset_s": 16.0,
        "end_offset_s": 19.0,
        "combined_score": 0.707,
        "class": "high",
    }
    clip = tmp_path / "clips" / expected_clip_name(event)
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"mp4")
    write_jsonl(tmp_path / "events" / "by-source-date" / "2026-05-27" / "reviewed-2026-05-27.jsonl", [event])
    cloud_path = tmp_path / "cloud-reviewed.jsonl"
    write_jsonl(
        cloud_path,
        [
            {
                "clip": str(clip),
                "event": {
                    "recommended_action": "crm_compare_candidate",
                    "payment_likely": True,
                    "money_handover_visible": True,
                    "payment_type": "cash",
                    "handover_confidence": 0.9,
                    "amount_status": "estimated",
                    "amount": 1000,
                    "currency": "RUB",
                    "amount_confidence": 0.6,
                    "visible_denominations": [1000],
                    "evidence": {"timestamp_hint": "00:06"},
                },
            }
        ],
    )

    payload = build_handover_evidence_payload(
        tmp_path,
        {"review": {"pre_padding_seconds": 5.0}, "clip": {}},
        cloud_path,
        min_handover_confidence=0.8,
    )

    assert payload["summary"]["total"] == 0
    assert payload["progress"]["confirmed_handover_candidates"] == 1
    assert payload["progress"]["clip_errors"] == 1
    assert payload["clip_errors"][0]["clip"] == clip.name


def test_build_handover_evidence_payload_includes_confirmed_manual_review_cash_handover(tmp_path, monkeypatch):
    source = tmp_path / "archive" / "2026-05-28" / "001" / "dav" / "18" / "18.00.00-18.01.00[M][0@0][0].dav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"dav")
    event = {
        "file": str(source),
        "start_time": "18:00:10",
        "end_time": "18:00:20",
        "start_offset_s": 10.0,
        "end_offset_s": 20.0,
        "combined_score": 0.5,
        "class": "medium",
    }
    clip = tmp_path / "clips" / expected_clip_name(event)
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"mp4")
    write_jsonl(tmp_path / "events" / "by-source-date" / "2026-05-28" / "reviewed-2026-05-28.jsonl", [event])
    cloud_path = tmp_path / "cloud-reviewed.jsonl"
    write_jsonl(
        cloud_path,
        [
            {
                "clip": str(clip),
                "event": {
                    "recommended_action": "manual_review",
                    "payment_likely": True,
                    "money_handover_visible": True,
                    "payment_type": "cash",
                    "handover_confidence": 0.8,
                    "amount_status": "unknown",
                    "amount": None,
                    "currency": "RUB",
                    "amount_confidence": 0,
                    "visible_denominations": [],
                    "evidence": {"timestamp_hint": "00:06", "handover": "Cash is being handled."},
                },
            }
        ],
    )

    def fake_extract_clip(source_path, target_path, start_s, duration_s, crf, preset, audio):
        target_path.parent.mkdir(parents=True)
        target_path.write_bytes(b"handover")

    monkeypatch.setattr("dahua_money_watch.handover_evidence.extract_clip", fake_extract_clip)

    payload = build_handover_evidence_payload(
        tmp_path,
        {"review": {"pre_padding_seconds": 5.0}, "clip": {}},
        cloud_path,
        min_handover_confidence=0.8,
    )

    assert payload["summary"]["total"] == 1
    assert payload["events"][0]["review"]["final_action"] == "manual_review"
    assert payload["events"][0]["accounting"]["comparison_status"] == "handover_confirmed_amount_estimated"
