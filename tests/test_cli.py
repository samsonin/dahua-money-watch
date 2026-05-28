import json
from pathlib import Path

from dahua_money_watch.cli import (
    cloud_review_command,
    cloud_review_output_path,
    discover_candidate_clips,
    event_output_paths,
    handover_report_command,
)
from dahua_money_watch.report import expected_clip_name


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def event(date, event_class, score, start, end, source_start="09.00.00", source_end="09.05.00"):
    return {
        "file": f"/archive/{date}/001/dav/09/{source_start}-{source_end}[M][0@0][0].dav",
        "start_time": start,
        "end_time": end,
        "combined_score": score,
        "class": event_class,
    }


def touch_clip(root: Path, row):
    path = root / "clips" / expected_clip_name(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"mp4")
    return path


def test_discover_candidate_clips_prioritizes_oldest_source_day(tmp_path):
    old_high = event("2026-05-18", "high", 0.7, "09:01:00", "09:01:05")
    old_low = event("2026-05-18", "low", 0.4, "09:02:00", "09:02:05")
    new_high = event("2026-05-19", "high", 0.9, "09:01:00", "09:01:05")
    write_jsonl(tmp_path / "events" / "reviewed-2026-05-27.jsonl", [new_high, old_low, old_high])
    old_high_path = touch_clip(tmp_path, old_high)
    old_low_path = touch_clip(tmp_path, old_low)
    touch_clip(tmp_path, new_high)

    selected = discover_candidate_clips(tmp_path, limit=2)

    assert selected == [old_high_path, old_low_path]


def test_discover_candidate_clips_fills_limit_after_oldest_day_is_closed(tmp_path):
    old_low = event("2026-05-18", "low", 0.4, "09:02:00", "09:02:05")
    new_high = event("2026-05-19", "high", 0.9, "09:01:00", "09:01:05")
    write_jsonl(tmp_path / "events" / "reviewed-2026-05-27.jsonl", [new_high, old_low])
    old_low_path = touch_clip(tmp_path, old_low)
    new_high_path = touch_clip(tmp_path, new_high)

    selected = discover_candidate_clips(tmp_path, limit=2)

    assert selected == [old_low_path, new_high_path]


def test_discover_candidate_clips_can_filter_source_date(tmp_path):
    old_high = event("2026-05-18", "high", 0.7, "09:01:00", "09:01:05")
    new_high = event("2026-05-19", "high", 0.9, "09:01:00", "09:01:05")
    write_jsonl(tmp_path / "events" / "reviewed-2026-05-27.jsonl", [new_high, old_high])
    touch_clip(tmp_path, old_high)
    new_high_path = touch_clip(tmp_path, new_high)

    selected = discover_candidate_clips(tmp_path, limit=10, source_date="2026-05-19")

    assert selected == [new_high_path]


def test_cloud_review_command_passes_escalation_model_from_config(tmp_path, monkeypatch):
    clip = tmp_path / "clips" / "candidate.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"mp4")
    config = {
        "runtime_dir": str(tmp_path),
        "archive_root": "/archive",
        "pattern": "*.dav",
        "state_db": str(tmp_path / "state" / "processed.sqlite"),
        "roi": {"x": 0, "y": 0, "w": 10, "h": 10},
        "scan": {"stable_file_age_seconds": 90},
        "review": {},
        "clip": {},
        "cloud_review": {
            "project": "demo-project",
            "location": "global",
            "model": "gemini-2.5-flash-lite",
            "stage": "two-stage",
            "escalation_enabled": True,
            "escalation_model": "gemini-2.5-flash",
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    captured = {}

    def fake_two_stage_money_review(clip_path, project, location, model, frame_dir, timeout_seconds=120, **kwargs):
        captured.update(
            {
                "clip": clip_path,
                "project": project,
                "location": location,
                "model": model,
                "frame_dir": frame_dir,
                **kwargs,
            }
        )
        return {"clip": str(clip_path), "event": {"recommended_action": "ignore"}}

    monkeypatch.setattr("dahua_money_watch.cli.two_stage_money_review", fake_two_stage_money_review)

    result = cloud_review_command(
        type(
            "Args",
            (),
            {
                "config": str(config_path),
                "runtime_dir": None,
                "project": None,
                "location": None,
                "model": None,
                "include_reviewed": False,
                "date": None,
                "limit": 1,
                "clip": [str(clip)],
                "dry_run": False,
                "stage": "two-stage",
            },
        )()
    )

    assert result == 0
    assert captured["model"] == "gemini-2.5-flash-lite"
    assert captured["escalation_model"] == "gemini-2.5-flash"


def test_cloud_review_output_path_uses_source_date(tmp_path):
    event_row = event("2026-05-18", "high", 0.7, "09:01:00", "09:01:05")
    clip = tmp_path / "clips" / expected_clip_name(event_row)
    metadata = {clip.name: type("Metadata", (), {"source_date": "2026-05-18"})()}

    output = cloud_review_output_path(tmp_path, clip, metadata)

    assert output == tmp_path / "cloud-reviews" / "by-source-date" / "2026-05-18" / "cloud-reviewed-2026-05-18.jsonl"


def test_event_output_paths_use_source_date(tmp_path):
    events_path, reviewed_path = event_output_paths(tmp_path, "2026-05-18")

    assert events_path == tmp_path / "events" / "by-source-date" / "2026-05-18" / "events-2026-05-18.jsonl"
    assert reviewed_path == tmp_path / "events" / "by-source-date" / "2026-05-18" / "reviewed-2026-05-18.jsonl"


def test_handover_report_command_uses_config_and_writes_payload(tmp_path, monkeypatch):
    config = {
        "runtime_dir": str(tmp_path),
        "archive_root": "/archive",
        "pattern": "*.dav",
        "state_db": str(tmp_path / "state" / "processed.sqlite"),
        "roi": {"x": 0, "y": 0, "w": 10, "h": 10},
        "scan": {"stable_file_age_seconds": 90},
        "review": {},
        "clip": {},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    cloud_path = tmp_path / "cloud.jsonl"
    cloud_path.write_text("")
    output_path = tmp_path / "reports" / "handover.json"
    captured = {}

    def fake_write_report(runtime_dir, config_arg, cloud_review_path, output, report_date, min_confidence, pre_seconds, post_seconds):
        captured.update(
            {
                "runtime_dir": runtime_dir,
                "config": config_arg,
                "cloud_review_path": cloud_review_path,
                "output": output,
                "report_date": report_date,
                "min_confidence": min_confidence,
                "pre_seconds": pre_seconds,
                "post_seconds": post_seconds,
            }
        )
        output.parent.mkdir(parents=True)
        output.write_text("{}\n")
        return 3, {"summary": {"total": 3}, "progress": {"source_cloud_review_rows": 5}}

    monkeypatch.setattr("dahua_money_watch.cli.write_handover_evidence_report", fake_write_report)

    result = handover_report_command(
        type(
            "Args",
            (),
            {
                "config": str(config_path),
                "runtime_dir": None,
                "cloud_review_jsonl": str(cloud_path),
                "date": "2026-05-27",
                "output": str(output_path),
                "min_handover_confidence": 0.85,
                "pre_seconds": 2.0,
                "post_seconds": 6.0,
            },
        )()
    )

    assert result == 0
    assert captured["runtime_dir"] == tmp_path
    assert captured["cloud_review_path"] == cloud_path
    assert captured["output"] == output_path
    assert captured["report_date"] == "2026-05-27"
    assert captured["min_confidence"] == 0.85
    assert captured["pre_seconds"] == 2.0
    assert captured["post_seconds"] == 6.0
