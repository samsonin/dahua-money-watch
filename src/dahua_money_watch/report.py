from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .dahua import parse_dahua_clip
from .review import safe_name


REPORT_COLUMNS = [
    "source_date",
    "event_start_time",
    "event_end_time",
    "source_file",
    "clip",
    "local_class",
    "local_score",
    "final_action",
    "payment_likely",
    "money_handover_visible",
    "payment_type",
    "handover_confidence",
    "amount_status",
    "amount",
    "currency",
    "amount_confidence",
    "visible_denominations",
    "timestamp_hint",
    "handover_evidence",
    "amount_evidence",
    "review_error",
    "metadata_status",
]


@dataclass(frozen=True)
class LocalClipMetadata:
    event: Dict[str, Any]
    source_date: str
    source_file: str
    metadata_status: str


def write_daily_report(
    runtime_dir: Path,
    report_date: str,
    output_path: Path,
    only_actionable: bool = False,
) -> Tuple[int, Dict[str, int]]:
    rows = build_daily_report_rows(runtime_dir, report_date, only_actionable)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize_rows(rows)
    return len(rows), summary


def write_daily_report_json(
    runtime_dir: Path,
    report_date: str,
    output_path: Path,
    only_actionable: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    payload = build_daily_report_payload(runtime_dir, report_date, only_actionable)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return len(payload["events"]), payload["summary"]


def build_daily_report_payload(
    runtime_dir: Path,
    report_date: str,
    only_actionable: bool = False,
) -> Dict[str, Any]:
    all_rows = build_daily_report_rows(runtime_dir, report_date, False)
    rows = [row for row in all_rows if row["final_action"] != "ignore"] if only_actionable else all_rows
    metadata_index, _ambiguous = load_local_clip_metadata(runtime_dir)
    candidate_count = sum(1 for metadata in metadata_index.values() if metadata.source_date == report_date)
    reviewed_count = len(all_rows)
    complete = candidate_count > 0 and reviewed_count >= candidate_count
    return {
        "schema_version": "1.0",
        "report_type": "dahua_money_watch.daily_accounting",
        "source_date": report_date,
        "status": "complete" if complete else "partial",
        "complete": complete,
        "progress": {
            "candidate_clips": candidate_count,
            "gemini_reviewed": reviewed_count,
            "gemini_remaining": max(0, candidate_count - reviewed_count),
            "exported_events": len(rows),
        },
        "summary": summarize_rows(rows),
        "events": [json_event_from_row(row) for row in rows],
    }


def build_daily_report_rows(runtime_dir: Path, report_date: str, only_actionable: bool = False) -> List[Dict[str, Any]]:
    metadata_index, ambiguous_names = load_local_clip_metadata(runtime_dir)
    rows: List[Dict[str, Any]] = []

    for cloud_row in load_latest_cloud_review_rows(runtime_dir):
        clip = str(cloud_row.get("clip") or "")
        if not clip:
            continue
        row = report_row(cloud_row, metadata_index.get(Path(clip).name), ambiguous_names)
        if row["source_date"] != report_date:
            continue
        if only_actionable and row["final_action"] == "ignore":
            continue
        rows.append(row)

    rows.sort(key=lambda item: (item["event_start_time"], item["clip"]))
    return rows


def summarize_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    summary: Dict[str, int] = {
        "total": 0,
        "ignore": 0,
        "manual_review": 0,
        "crm_compare": 0,
        "errors": 0,
        "unknown": 0,
    }
    for row in rows:
        summary["total"] += 1
        if row.get("review_error"):
            summary["errors"] += 1
        action = str(row.get("final_action") or "unknown")
        if action not in summary:
            summary[action] = 0
        summary[action] += 1
    return summary


def json_event_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    action = str(row.get("final_action") or "unknown")
    return {
        "source_date": row.get("source_date") or "",
        "event_start_time": row.get("event_start_time") or "",
        "event_end_time": row.get("event_end_time") or "",
        "source_file": row.get("source_file") or "",
        "candidate_clip": row.get("clip") or "",
        "local": {
            "class": row.get("local_class") or "",
            "score": _nullable_float(row.get("local_score")),
            "metadata_status": row.get("metadata_status") or "",
        },
        "review": {
            "final_action": action,
            "payment_likely": _nullable_bool(row.get("payment_likely")),
            "money_handover_visible": _nullable_bool(row.get("money_handover_visible")),
            "payment_type": row.get("payment_type") or "unknown",
            "handover_confidence": _nullable_float(row.get("handover_confidence")),
            "timestamp_hint": row.get("timestamp_hint") or "",
            "evidence": row.get("handover_evidence") or "",
            "error": row.get("review_error") or "",
        },
        "amount": {
            "status": row.get("amount_status") or "unknown",
            "amount": _nullable_float(row.get("amount")),
            "currency": row.get("currency") or "unknown",
            "confidence": _nullable_float(row.get("amount_confidence")),
            "visible_denominations": _json_list(row.get("visible_denominations")),
            "evidence": row.get("amount_evidence") or "",
        },
        "accounting": {
            "comparison_status": accounting_status(action, row),
            "comparison_key": {
                "date": row.get("source_date") or "",
                "time": row.get("event_start_time") or "",
                "amount": _nullable_float(row.get("amount")),
                "currency": row.get("currency") or "unknown",
            },
        },
    }


def accounting_status(action: str, row: Dict[str, Any]) -> str:
    if row.get("review_error"):
        return "review_error"
    if action == "crm_compare":
        return "ready_for_comparison"
    if action == "manual_review":
        return "manual_review_required"
    if action == "ignore":
        return "not_a_payment"
    return "unknown"


def report_row(
    cloud_row: Dict[str, Any],
    metadata: Optional[LocalClipMetadata],
    ambiguous_names: Optional[set] = None,
) -> Dict[str, Any]:
    clip = str(cloud_row.get("clip") or "")
    event = cloud_row.get("event") or {}
    if not event and cloud_row.get("response"):
        event = _event_from_handover_response(cloud_row)

    evidence = event.get("evidence") or {}
    metadata_status = "missing"
    source_date = ""
    event_start_time = ""
    event_end_time = ""
    source_file = ""
    local_class = ""
    local_score = ""
    clip_name = Path(clip).name

    if metadata is not None:
        source_date = metadata.source_date
        source_file = metadata.source_file
        metadata_status = metadata.metadata_status
        local_event = metadata.event
        event_start_time = str(local_event.get("start_time") or "")
        event_end_time = str(local_event.get("end_time") or "")
        local_class = str(local_event.get("class") or "")
        local_score = _format_float(local_event.get("combined_score"))

    if ambiguous_names and clip_name in ambiguous_names:
        metadata_status = "ambiguous"

    fallback_start, fallback_end = parse_clip_event_times(clip_name)
    if not event_start_time:
        event_start_time = fallback_start
    if not event_end_time:
        event_end_time = fallback_end

    return {
        "source_date": source_date,
        "event_start_time": event_start_time,
        "event_end_time": event_end_time,
        "source_file": source_file,
        "clip": clip_name,
        "local_class": local_class,
        "local_score": local_score,
        "final_action": event.get("recommended_action") or ("error" if cloud_row.get("error") else "unknown"),
        "payment_likely": _bool_text(event.get("payment_likely")),
        "money_handover_visible": _bool_text(event.get("money_handover_visible")),
        "payment_type": event.get("payment_type") or "unknown",
        "handover_confidence": _format_float(event.get("handover_confidence")),
        "amount_status": event.get("amount_status") or "unknown",
        "amount": "" if event.get("amount") is None else event.get("amount"),
        "currency": event.get("currency") or "unknown",
        "amount_confidence": _format_float(event.get("amount_confidence")),
        "visible_denominations": json.dumps(event.get("visible_denominations") or [], ensure_ascii=False),
        "timestamp_hint": evidence.get("timestamp_hint") or "",
        "handover_evidence": evidence.get("handover") or "",
        "amount_evidence": evidence.get("amount") or "",
        "review_error": cloud_row.get("error") or "",
        "metadata_status": metadata_status,
    }


def load_local_clip_metadata(runtime_dir: Path) -> Tuple[Dict[str, LocalClipMetadata], set]:
    candidates: Dict[str, List[LocalClipMetadata]] = {}
    for row in load_reviewed_event_rows(runtime_dir):
        clip_name = expected_clip_name(row)
        if not clip_name:
            continue
        source_path = Path(str(row.get("file") or ""))
        source_clip = parse_dahua_clip(source_path)
        source_date = source_clip.date if source_clip else ""
        candidates.setdefault(clip_name, []).append(
            LocalClipMetadata(
                event=row,
                source_date=source_date,
                source_file=source_path.name,
                metadata_status="matched" if source_date else "matched_no_date",
            )
        )

    index: Dict[str, LocalClipMetadata] = {}
    ambiguous = set()
    for clip_name, matches in candidates.items():
        dates = {item.source_date for item in matches}
        if len(matches) > 1 and len(dates) > 1:
            ambiguous.add(clip_name)
        index[clip_name] = matches[0]
    return index, ambiguous


def load_reviewed_event_rows(runtime_dir: Path) -> Iterable[Dict[str, Any]]:
    events_dir = runtime_dir / "events"
    for path in sorted(events_dir.glob("reviewed-*.jsonl")):
        yield from _read_jsonl(path)


def load_cloud_review_rows(runtime_dir: Path) -> Iterable[Dict[str, Any]]:
    review_dir = runtime_dir / "cloud-reviews"
    for path in sorted(review_dir.glob("cloud-reviewed-*.jsonl")):
        yield from _read_jsonl(path)


def load_latest_cloud_review_rows(runtime_dir: Path) -> Iterable[Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for row in load_cloud_review_rows(runtime_dir):
        clip = str(row.get("clip") or "")
        if not clip:
            continue
        previous = latest.get(clip)
        if previous is None or previous.get("error") or not row.get("error"):
            latest[clip] = row
    return latest.values()


def expected_clip_name(event: Dict[str, Any]) -> str:
    source = Path(str(event.get("file") or ""))
    if not source.name:
        return ""
    start_time = str(event.get("start_time") or "").replace(":", "")
    end_time = str(event.get("end_time") or "").replace(":", "")
    if not start_time or not end_time:
        return ""
    score = _format_score(event.get("combined_score"))
    event_class = str(event.get("class") or "unknown")
    return f"{event_class}_{score}_{start_time}-{end_time}_{safe_name(source.stem)}.mp4"


def parse_clip_event_times(clip_name: str) -> Tuple[str, str]:
    parts = clip_name.split("_", 3)
    if len(parts) < 3:
        return "", ""
    stamp = parts[2]
    if "-" not in stamp:
        return "", ""
    start, end = stamp.split("-", 1)
    return _clock_from_compact(start), _clock_from_compact(end)


def _event_from_handover_response(cloud_row: Dict[str, Any]) -> Dict[str, Any]:
    response = cloud_row.get("response") or {}
    return {
        "recommended_action": response.get("recommended_action", "unknown"),
        "payment_likely": bool(response.get("payment_likely")),
        "money_handover_visible": bool(response.get("money_handover_visible")),
        "payment_type": (
            "cash"
            if response.get("cash_visible")
            else "card_or_phone"
            if response.get("card_or_phone_payment")
            else "unknown"
        ),
        "handover_confidence": response.get("confidence", 0.0),
        "amount_status": "unknown",
        "amount": None,
        "currency": "unknown",
        "amount_confidence": 0.0,
        "visible_denominations": [],
        "evidence": {
            "handover": response.get("evidence", ""),
            "amount": "",
            "timestamp_hint": response.get("timestamp_hint", ""),
        },
    }


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def _format_score(value: Any) -> str:
    try:
        return f"{float(value):.3f}".replace(".", "p")
    except (TypeError, ValueError):
        return "0p000"


def _format_float(value: Any) -> str:
    if value in ("", None):
        return ""
    try:
        return f"{float(value):.4f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _nullable_float(value: Any) -> Optional[float]:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nullable_bool(value: Any) -> Optional[bool]:
    if value in ("", None):
        return None
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def _json_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value in ("", None):
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _bool_text(value: Any) -> str:
    if value is None:
        return ""
    return "true" if bool(value) else "false"


def _clock_from_compact(value: str) -> str:
    if len(value) != 6 or not value.isdigit():
        return ""
    return f"{value[0:2]}:{value[2:4]}:{value[4:6]}"
