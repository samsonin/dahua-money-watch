from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .report import json_event_from_row, load_local_clip_metadata, report_row, summarize_rows
from .review import safe_name
from .video import extract_clip


REPORT_SCHEMA_VERSION = "1.1"
HANDOVER_REVIEW_STATUS_CONFIRMED = "confirmed_cash_handover"
HANDOVER_REVIEW_STATUS_SUSPECTED = "suspected_payment_interaction"
SUSPECTED_LOCAL_CLASSES = {"high", "medium"}
MIN_SUSPECTED_LOCAL_SCORE = 0.45


def build_handover_evidence_payload(
    runtime_dir: Path,
    config: Dict[str, Any],
    cloud_review_path: Path,
    report_date: Optional[str] = None,
    min_handover_confidence: float = 0.8,
    min_suspected_confidence: float = 0.1,
    max_events_per_day: int = 10,
    pre_seconds: float = 3.0,
    post_seconds: float = 5.0,
) -> Dict[str, Any]:
    metadata_index, ambiguous = load_local_clip_metadata(runtime_dir)
    rows: List[Dict[str, Any]] = []
    candidates: List[Tuple[Dict[str, Any], Optional[Any], str]] = []
    clip_errors: List[Dict[str, str]] = []
    source_rows = 0
    confirmed_candidates = 0
    suspected_interactions = 0
    source_dates = {}
    clip_base_url = evidence_clip_base_url(config)

    for cloud_row in _read_jsonl(cloud_review_path):
        source_rows += 1
        clip_name = Path(str(cloud_row.get("clip") or "")).name
        metadata = metadata_index.get(clip_name)
        row = report_row(cloud_row, metadata, ambiguous)
        if report_date and row["source_date"] != report_date:
            continue
        handover_status = handover_review_status(row, min_handover_confidence, min_suspected_confidence)
        if not handover_status:
            continue
        if handover_status == HANDOVER_REVIEW_STATUS_CONFIRMED:
            confirmed_candidates += 1
        else:
            suspected_interactions += 1
        candidates.append((row, metadata, handover_status))

    for row, metadata, handover_status in select_handover_rows(candidates, max_events_per_day):
        if metadata is None:
            clip_errors.append({"clip": row.get("clip") or "", "error": "missing local metadata"})
            continue
        else:
            clip_path, error = write_handover_clip(
                runtime_dir,
                config,
                row,
                metadata.event,
                pre_seconds,
                post_seconds,
            )
            if clip_path:
                row["handover_clip"] = _relative_to_runtime(runtime_dir, clip_path)
                if clip_base_url:
                    row["handover_clip_url"] = join_clip_url(clip_base_url, row["handover_clip"])
            if error:
                clip_errors.append({"clip": row.get("clip") or "", "error": error})
                continue
        row["handover_confirmed"] = handover_status == HANDOVER_REVIEW_STATUS_CONFIRMED
        row["handover_suspected"] = handover_status == HANDOVER_REVIEW_STATUS_SUSPECTED
        row["handover_review_status"] = handover_status
        rows.append(row)
        source_dates[row["source_date"] or "unknown-source-date"] = source_dates.get(row["source_date"] or "unknown-source-date", 0) + 1

    rows.sort(key=lambda item: (item["source_date"], item["event_start_time"], item["clip"]))
    payload_source_date = report_date or "mixed"
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_type": "dahua_money_watch.handover_evidence",
        "source_date": payload_source_date,
        "status": "handover_evidence",
        "complete": False,
        "thresholds": {
            "min_handover_confidence": min_handover_confidence,
            "min_suspected_confidence": min_suspected_confidence,
            "min_suspected_local_score": MIN_SUSPECTED_LOCAL_SCORE,
            "max_events_per_day": max_events_per_day,
            "pre_seconds": pre_seconds,
            "post_seconds": post_seconds,
        },
        "progress": {
            "source_cloud_review_rows": source_rows,
            "confirmed_handover_candidates": confirmed_candidates,
            "suspected_payment_interactions": suspected_interactions,
            "exported_events": len(rows),
            "clip_errors": len(clip_errors),
        },
        "clip_errors": clip_errors,
        "source_dates": dict(sorted(source_dates.items())),
        "summary": summarize_rows(rows),
        "events": [json_event_from_row(row) for row in rows],
    }


def write_handover_evidence_report(
    runtime_dir: Path,
    config: Dict[str, Any],
    cloud_review_path: Path,
    output_path: Path,
    report_date: Optional[str] = None,
    min_handover_confidence: float = 0.8,
    min_suspected_confidence: float = 0.1,
    max_events_per_day: int = 10,
    pre_seconds: float = 3.0,
    post_seconds: float = 5.0,
) -> Tuple[int, Dict[str, Any]]:
    payload = build_handover_evidence_payload(
        runtime_dir,
        config,
        cloud_review_path,
        report_date,
        min_handover_confidence,
        min_suspected_confidence,
        max_events_per_day,
        pre_seconds,
        post_seconds,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return len(payload["events"]), payload


def is_confirmed_handover_candidate(row: Dict[str, Any], min_handover_confidence: float) -> bool:
    return (
        row.get("final_action") in {"crm_compare_candidate", "manual_review"}
        and _truthy(row.get("payment_likely"))
        and _truthy(row.get("money_handover_visible"))
        and str(row.get("payment_type") or "").lower() == "cash"
        and _float(row.get("handover_confidence")) >= min_handover_confidence
    )


def is_suspected_payment_interaction(row: Dict[str, Any], min_suspected_confidence: float) -> bool:
    if row.get("final_action") not in {"crm_compare_candidate", "manual_review"}:
        return False
    if str(row.get("payment_type") or "").lower() not in {"cash", "unknown"}:
        return False
    model_suspected = (
        (_truthy(row.get("payment_likely")) or _truthy(row.get("money_handover_visible")))
        and _float(row.get("handover_confidence")) >= min_suspected_confidence
    )
    local_suspected = (
        str(row.get("local_class") or "").lower() in SUSPECTED_LOCAL_CLASSES
        and _float(row.get("local_score")) >= MIN_SUSPECTED_LOCAL_SCORE
    )
    return model_suspected or local_suspected


def handover_review_status(
    row: Dict[str, Any],
    min_handover_confidence: float,
    min_suspected_confidence: float,
) -> str:
    if is_confirmed_handover_candidate(row, min_handover_confidence):
        return HANDOVER_REVIEW_STATUS_CONFIRMED
    if is_suspected_payment_interaction(row, min_suspected_confidence):
        return HANDOVER_REVIEW_STATUS_SUSPECTED
    return ""


def select_handover_rows(
    candidates: List[Tuple[Dict[str, Any], Optional[Any], str]],
    max_events_per_day: int,
) -> List[Tuple[Dict[str, Any], Optional[Any], str]]:
    confirmed = [item for item in candidates if item[2] == HANDOVER_REVIEW_STATUS_CONFIRMED]
    suspected = [item for item in candidates if item[2] == HANDOVER_REVIEW_STATUS_SUSPECTED]
    slots = max(0, int(max_events_per_day) - len(confirmed))
    selected = confirmed + sorted(suspected, key=_suspected_priority)[:slots]
    return sorted(selected, key=lambda item: (item[0]["source_date"], item[0]["event_start_time"], item[0]["clip"]))


def _suspected_priority(item: Tuple[Dict[str, Any], Optional[Any], str]) -> Tuple[float, float, str]:
    row = item[0]
    return (-_float(row.get("local_score")), -_float(row.get("handover_confidence")), row.get("event_start_time") or "")


def write_handover_clip(
    runtime_dir: Path,
    config: Dict[str, Any],
    row: Dict[str, Any],
    local_event: Dict[str, Any],
    pre_seconds: float,
    post_seconds: float,
) -> Tuple[Optional[Path], str]:
    source = Path(str(local_event.get("file") or ""))
    if not source.exists():
        return None, f"source file not found: {source}"
    source_date = row.get("source_date") or "unknown-source-date"
    target = handover_clip_path(runtime_dir, source_date, row.get("clip") or source.stem)
    review_cfg = config.get("review", {})
    clip_cfg = config.get("clip", {})
    source_start = max(0.0, _float(local_event.get("start_offset_s")) - _float(review_cfg.get("pre_padding_seconds"), 0.0))
    hint = parse_timestamp_hint(str(row.get("timestamp_hint") or ""))
    if hint is None:
        handover_at = (_float(local_event.get("start_offset_s")) + _float(local_event.get("end_offset_s"))) / 2
    else:
        handover_at = source_start + hint
    start = max(0.0, handover_at - pre_seconds)
    duration = pre_seconds + post_seconds
    try:
        extract_clip(
            source,
            target,
            start,
            duration,
            int(clip_cfg.get("crf", 24)),
            str(clip_cfg.get("preset", "fast")),
            True,
        )
    except Exception as exc:  # pragma: no cover - exact ffmpeg failures vary by host
        return None, str(exc)
    return target, ""


def handover_clip_path(runtime_dir: Path, source_date: str, clip_name: str) -> Path:
    stem = Path(clip_name).stem
    return runtime_dir / "handover-clips" / "by-source-date" / source_date / f"{safe_name(stem)}_handover.mp4"


def parse_timestamp_hint(value: str) -> Optional[float]:
    value = value.strip()
    if not value:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", value):
        return float(value)
    parts = value.split(":")
    if len(parts) == 2 and all(part.isdigit() for part in parts):
        return float(int(parts[0]) * 60 + int(parts[1]))
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return float(int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]))
    return None


def evidence_clip_base_url(config: Dict[str, Any]) -> str:
    evidence_cfg = config.get("evidence", {})
    if isinstance(evidence_cfg, dict) and evidence_cfg.get("clip_base_url"):
        return str(evidence_cfg["clip_base_url"]).rstrip("/")
    return str(os.environ.get("EVIDENCE_CLIPS_BASE_URL") or "").rstrip("/")


def join_clip_url(base_url: str, clip_path: str) -> str:
    path = clip_path
    if path.startswith("handover-clips/"):
        path = path[len("handover-clips/") :]
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _read_jsonl(path: Path):
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            yield json.loads(line)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _relative_to_runtime(runtime_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(runtime_dir))
    except ValueError:
        return str(path)
