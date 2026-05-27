from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from .config import Roi
from .video import ffmpeg_gray_frames


def cheap_review(event: Dict[str, Any], review_config: Dict[str, Any], roi: Roi) -> Dict[str, Any]:
    fps = float(review_config["fps"])
    start = max(0.0, float(event["start_offset_s"]) - float(review_config["pre_padding_seconds"]))
    end = float(event["end_offset_s"]) + float(review_config["post_padding_seconds"])
    duration = max(0.5, end - start)
    frames = list(
        ffmpeg_gray_frames(
            Path(event["file"]),
            fps=fps,
            width=int(review_config["width"]),
            height=int(review_config["height"]),
            start_s=start,
            duration_s=duration,
            roi=roi,
        )
    )
    stats = _visual_stats([frame for _, frame in frames])
    combined = float(stats["visual_score"])
    klass = classify(combined, float(review_config["medium_threshold"]), float(review_config["high_threshold"]))
    return {
        **event,
        **stats,
        "combined_score": round(combined, 4),
        "class": klass,
        "review_start_offset_s": round(start, 2),
        "review_end_offset_s": round(end, 2),
    }


def classify(score: float, medium_threshold: float, high_threshold: float) -> str:
    if score >= high_threshold:
        return "high"
    if score >= medium_threshold:
        return "medium"
    return "low"


def safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", value)


def _visual_stats(frames: List[np.ndarray]) -> Dict[str, Any]:
    if len(frames) < 2:
        return {
            "frames": len(frames),
            "visual_score": 0.0,
            "avg_diff": 0.0,
            "peak_diff": 0.0,
            "counter_focus": 0.0,
            "localized_motion": 0.0,
            "centroid_span": 0.0,
            "hot_roi_grid_row": 0,
            "hot_roi_grid_col": 0,
        }

    diffs: List[float] = []
    active_ratios: List[float] = []
    counter_focuses: List[float] = []
    localized_scores: List[float] = []
    centroids: List[Tuple[float, float]] = []
    cell_votes: Dict[Tuple[int, int], int] = {}

    for previous, current in zip(frames, frames[1:]):
        diff = np.abs(current.astype(np.int16) - previous.astype(np.int16)).astype(np.uint8)
        threshold = max(18, float(np.percentile(diff, 92)))
        mask = diff > threshold
        active_ratios.append(float(mask.mean()))
        diffs.append(float(diff.mean()))
        if mask.any():
            ys, xs = np.nonzero(mask)
            centroids.append((float(xs.mean()) / mask.shape[1], float(ys.mean()) / mask.shape[0]))
        localized, counter, cell = _roi_cell_stats(mask.astype(np.float32))
        localized_scores.append(localized)
        counter_focuses.append(counter)
        cell_votes[cell] = cell_votes.get(cell, 0) + 1

    xs = [point[0] for point in centroids]
    ys = [point[1] for point in centroids]
    centroid_span = (max(xs) - min(xs) if xs else 0.0) + 0.5 * (max(ys) - min(ys) if ys else 0.0)
    peak_diff = max(diffs)
    peak_active = max(active_ratios)
    localized = float(np.mean(localized_scores))
    counter = float(np.mean(counter_focuses))
    hot_cell = max(cell_votes.items(), key=lambda item: item[1])[0] if cell_votes else (0, 0)

    visual_score = (
        0.30 * min(1.0, peak_diff / 32.0)
        + 0.20 * min(1.0, peak_active / 0.18)
        + 0.20 * max(0.0, min(1.0, (localized - 0.10) / 0.35))
        + 0.20 * max(0.0, min(1.0, (counter - 0.45) / 0.45))
        + 0.10 * max(0.0, min(1.0, centroid_span / 0.45))
    )

    return {
        "frames": len(frames),
        "visual_score": round(float(visual_score), 4),
        "avg_diff": round(float(np.mean(diffs)), 4),
        "peak_diff": round(float(peak_diff), 4),
        "avg_active_ratio": round(float(np.mean(active_ratios)), 4),
        "peak_active_ratio": round(float(peak_active), 4),
        "counter_focus": round(counter, 4),
        "localized_motion": round(localized, 4),
        "centroid_span": round(float(centroid_span), 4),
        "hot_roi_grid_row": hot_cell[0],
        "hot_roi_grid_col": hot_cell[1],
    }


def _roi_cell_stats(mask: np.ndarray) -> Tuple[float, float, Tuple[int, int]]:
    rows, cols = 6, 8
    total = float(mask.sum())
    if total <= 0:
        return 0.0, 0.0, (0, 0)
    h, w = mask.shape
    best = 0.0
    best_cell = (0, 0)
    counter_total = 0.0
    for r in range(rows):
        for c in range(cols):
            y0, y1 = r * h // rows, (r + 1) * h // rows
            x0, x1 = c * w // cols, (c + 1) * w // cols
            value = float(mask[y0:y1, x0:x1].sum())
            if value > best:
                best = value
                best_cell = (r, c)
            if r >= 2 and c <= 5:
                counter_total += value
    return best / total, counter_total / total, best_cell
