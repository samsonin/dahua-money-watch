import json
from pathlib import Path

from dahua_money_watch.cli import discover_candidate_clips
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
