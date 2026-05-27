from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from .dahua import parse_dahua_clip
from .video import ffmpeg_gray_frames


@dataclass
class MotionScore:
    offset_s: float
    score: float
    hot_grid_row: int
    hot_grid_col: int


def _localized_score(diff: np.ndarray, rows: int, cols: int) -> Tuple[float, Tuple[int, int]]:
    h, w = diff.shape
    values: List[float] = []
    best = 0.0
    best_cell = (0, 0)
    for r in range(rows):
        for c in range(cols):
            y0, y1 = r * h // rows, (r + 1) * h // rows
            x0, x1 = c * w // cols, (c + 1) * w // cols
            value = float(diff[y0:y1, x0:x1].mean())
            values.append(value)
            if value > best:
                best = value
                best_cell = (r, c)
    top = sorted(values, reverse=True)[:4]
    return float(sum(top) / len(top)), best_cell


def scan_motion(path: Path, scan_config: Dict[str, Any]) -> List[MotionScore]:
    fps = float(scan_config["fps"])
    previous = None
    scores: List[MotionScore] = []
    for offset_s, frame in ffmpeg_gray_frames(
        path,
        fps=fps,
        width=int(scan_config["width"]),
        height=int(scan_config["height"]),
    ):
        current = frame.astype(np.int16)
        if previous is None:
            previous = current
            continue
        diff = np.abs(current - previous).astype(np.uint8)
        score, cell = _localized_score(diff, int(scan_config["grid_rows"]), int(scan_config["grid_cols"]))
        scores.append(MotionScore(offset_s, score, cell[0], cell[1]))
        previous = current
    return scores


def motion_events(path: Path, scan_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    scores = scan_motion(path, scan_config)
    if not scores:
        return []
    values = np.array([score.score for score in scores], dtype=np.float32)
    threshold = max(float(scan_config["min_score"]), float(np.percentile(values, float(scan_config["percentile"]))))
    window = float(scan_config["window_seconds"])
    events = _window_scores(scores, window, threshold)
    clip = parse_dahua_clip(path)
    for event in events:
        event["file"] = str(path)
        event["source_duration_s"] = clip.duration_s if clip else None
        if clip:
            event["start_time"] = clip.clock_at(event["start_offset_s"])
            event["end_time"] = clip.clock_at(event["end_offset_s"])
        else:
            event["start_time"] = f"+{event['start_offset_s']:.1f}s"
            event["end_time"] = f"+{event['end_offset_s']:.1f}s"
    return events


def _window_scores(scores: List[MotionScore], window_s: float, threshold: float) -> List[Dict[str, Any]]:
    max_t = scores[-1].offset_s
    step = max(1.0, window_s / 2)
    raw: List[Dict[str, Any]] = []
    t = 0.0
    while t <= max_t:
        chunk = [score for score in scores if t <= score.offset_s < t + window_s]
        if chunk:
            peak = max(score.score for score in chunk)
            avg = float(np.mean([score.score for score in chunk]))
            cells: Dict[Tuple[int, int], int] = {}
            for score in chunk:
                cell = (score.hot_grid_row, score.hot_grid_col)
                cells[cell] = cells.get(cell, 0) + 1
            hot = max(cells.items(), key=lambda item: item[1])[0]
            if peak >= threshold:
                raw.append(
                    {
                        "start_offset_s": round(t, 2),
                        "end_offset_s": round(min(max_t, t + window_s), 2),
                        "peak_motion": round(float(peak), 3),
                        "avg_motion": round(avg, 3),
                        "hot_grid_row": hot[0],
                        "hot_grid_col": hot[1],
                    }
                )
        t += step
    return _merge_events(raw)


def _merge_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not events:
        return []
    merged = [events[0].copy()]
    for event in events[1:]:
        last = merged[-1]
        if event["start_offset_s"] <= last["end_offset_s"] + 1.0:
            last["end_offset_s"] = max(last["end_offset_s"], event["end_offset_s"])
            last["peak_motion"] = max(last["peak_motion"], event["peak_motion"])
            last["avg_motion"] = round((last["avg_motion"] + event["avg_motion"]) / 2, 3)
        else:
            merged.append(event.copy())
    return merged
