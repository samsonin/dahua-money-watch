from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import load_config, resolve_archive_root, resolve_runtime_dir, roi_from_config
from .cloud_review import CloudReviewError, default_gcloud_project, review_clip_with_vertex, two_stage_money_review
from .dahua import iter_dav_files, parse_dahua_clip
from .handover_evidence import write_handover_evidence_report
from .license import license_status, load_license
from .motion import motion_events
from .report import load_local_clip_metadata, write_daily_report, write_daily_report_json
from .review import cheap_review, safe_name
from .state import StateStore
from .video import extract_clip, extract_frame


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="dahua-money-watch")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("run-once", help="Scan stable Dahua files once.")
    scan.add_argument("--config", required=True)
    scan.add_argument("--date", help="Optional archive date, for example 2026-05-27.")
    scan.add_argument("--archive-root")
    scan.add_argument("--pattern")
    scan.add_argument("--runtime-dir")
    scan.add_argument("--force", action="store_true", help="Reprocess files even if state says they were done.")
    scan.set_defaults(func=run_once)

    stats = sub.add_parser("stats", help="Print archive day statistics.")
    stats.add_argument("--config", required=True)
    stats.add_argument("--archive-root")
    stats.set_defaults(func=stats_command)

    init = sub.add_parser("init-site", help="Create a portable site config for a new server/customer.")
    init.add_argument("--site-id", required=True)
    init.add_argument("--archive-root", required=True)
    init.add_argument("--output", required=True)
    init.add_argument("--site-name", default="Store")
    init.add_argument("--timezone", default="UTC")
    init.add_argument("--camera-id", default="001")
    init.add_argument("--camera-name", default="Counter camera")
    init.add_argument("--roi", default="0,320,540,256", help="x,y,w,h")
    init.set_defaults(func=init_site_command)

    license_info = sub.add_parser("license-info", help="Print license information.")
    license_info.add_argument("--license", required=True)
    license_info.set_defaults(func=license_info_command)

    cloud = sub.add_parser("cloud-review", help="Review candidate clips with a cloud visual model.")
    cloud.add_argument("--config", required=True)
    cloud.add_argument("--clip", action="append", help="Specific MP4 clip to review. Can be repeated.")
    cloud.add_argument("--runtime-dir")
    cloud.add_argument("--project", help="Google Cloud project id. Defaults to config or GOOGLE_CLOUD_PROJECT.")
    cloud.add_argument("--location", help="Vertex AI location. Defaults to config or global.")
    cloud.add_argument("--model", help="Gemini model id. Defaults to config or gemini-2.5-flash-lite.")
    cloud.add_argument("--escalation-model", help="Second-pass model for manual_review clips. Defaults to config.")
    cloud.add_argument("--date", help="Only review clips whose source archive date matches YYYY-MM-DD.")
    cloud.add_argument("--limit", type=int)
    cloud.add_argument("--stage", choices=["handover", "two-stage"], default="two-stage")
    cloud.add_argument("--include-reviewed", action="store_true", help="Review clips even if they already appear in cloud review logs.")
    cloud.add_argument("--dry-run", action="store_true")
    cloud.set_defaults(func=cloud_review_command)

    daily_report = sub.add_parser("daily-report", help="Write a daily summary for accounting reconciliation.")
    daily_report.add_argument("--config", required=True)
    daily_report.add_argument("--date", required=True, help="Source archive date, for example 2026-05-27.")
    daily_report.add_argument("--runtime-dir")
    daily_report.add_argument("--format", choices=["csv", "json"], default="csv")
    daily_report.add_argument("--output", help="Output path. Defaults to runtime/reports/accounting-YYYY-MM-DD.<format>.")
    daily_report.add_argument(
        "--only-actionable",
        action="store_true",
        help="Exclude ignored clips and keep only manual review, CRM compare, and errors.",
    )
    daily_report.set_defaults(func=daily_report_command)

    handover_report = sub.add_parser(
        "handover-report",
        help="Write confirmed cash handover evidence JSON and short audio clips from a cloud-review JSONL file.",
    )
    handover_report.add_argument("--config", required=True)
    handover_report.add_argument("--cloud-review-jsonl", required=True)
    handover_report.add_argument("--date", help="Optional source date filter, for example 2026-05-27.")
    handover_report.add_argument("--runtime-dir")
    handover_report.add_argument("--output", required=True)
    handover_report.add_argument("--min-handover-confidence", type=float, default=0.8)
    handover_report.add_argument("--min-suspected-confidence", type=float, default=0.1)
    handover_report.add_argument("--max-events-per-day", type=int, default=10)
    handover_report.add_argument("--pre-seconds", type=float, default=3.0)
    handover_report.add_argument("--post-seconds", type=float, default=5.0)
    handover_report.set_defaults(func=handover_report_command)

    args = parser.parse_args(argv)
    return int(args.func(args))


def run_once(args: argparse.Namespace) -> int:
    require_ffmpeg()
    config = load_config(args.config)
    archive_root = resolve_archive_root(config, args.archive_root)
    runtime_dir = resolve_runtime_dir(config, args.runtime_dir)
    pattern = args.pattern or config["pattern"]
    state_path = Path(config["state_db"]) if not args.runtime_dir else runtime_dir / "state" / "processed.sqlite"

    ensure_runtime_dirs(runtime_dir)
    store = StateStore(state_path)
    roi = roi_from_config(config)

    processed = 0
    motion_count = 0
    reviewed_count = 0

    try:
        for path in iter_dav_files(
            archive_root,
            pattern,
            args.date,
            int(config["scan"]["stable_file_age_seconds"]),
        ):
            if not args.force and store.already_processed(path):
                continue
            source_date = source_date_for_path(path)
            events_path, reviewed_path = event_output_paths(runtime_dir, source_date)
            events = motion_events(path, config["scan"])
            append_jsonl(events_path, events)
            motion_count += len(events)

            reviewed = [cheap_review(event, config["review"], roi) for event in events]
            reviewed.sort(key=lambda event: event["combined_score"], reverse=True)
            append_jsonl(reviewed_path, reviewed)
            reviewed_count += len(reviewed)
            write_artifacts(reviewed, runtime_dir, config)

            store.mark_processed(path)
            processed += 1
            print(f"processed file={path} motion={len(events)}")
    finally:
        store.close()

    print(
        json.dumps(
            {
                "processed_files": processed,
                "motion_events": motion_count,
                "reviewed_events": reviewed_count,
                "runtime_dir": str(runtime_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0


def stats_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    archive_root = resolve_archive_root(config, args.archive_root)
    by_day: Dict[str, Dict[str, float]] = {}
    from .dahua import parse_dahua_clip

    for path in archive_root.glob(config["pattern"]):
        clip = parse_dahua_clip(path)
        if clip is None or clip.date is None:
            continue
        day = by_day.setdefault(clip.date, {"count": 0, "seconds": 0, "bytes": 0})
        day["count"] += 1
        day["seconds"] += clip.duration_s
        day["bytes"] += path.stat().st_size
    for date in sorted(by_day):
        item = by_day[date]
        print(
            f"{date} count={int(item['count'])} "
            f"hours={item['seconds'] / 3600:.3f} "
            f"gb={item['bytes'] / 1024 ** 3:.3f}"
        )
    return 0


def init_site_command(args: argparse.Namespace) -> int:
    x, y, w, h = [int(part) for part in args.roi.split(",")]
    runtime_dir = f"runtime/{args.site_id}"
    config = {
        "site": {
            "id": args.site_id,
            "name": args.site_name,
            "timezone": args.timezone,
        },
        "archive_root": args.archive_root,
        "pattern": "*/001/dav/*/*.dav",
        "runtime_dir": runtime_dir,
        "state_db": f"{runtime_dir}/state/processed.sqlite",
        "cameras": [
            {
                "id": args.camera_id,
                "name": args.camera_name,
                "path_hint": f"{args.camera_id}/dav",
                "roi": {"x": x, "y": y, "w": w, "h": h},
            }
        ],
        "roi": {"x": x, "y": y, "w": w, "h": h},
        "scan": {
            "fps": 3.0,
            "width": 352,
            "height": 288,
            "grid_rows": 6,
            "grid_cols": 8,
            "window_seconds": 2.0,
            "percentile": 92.0,
            "min_score": 4.0,
            "stable_file_age_seconds": 90,
        },
        "review": {
            "fps": 6.0,
            "width": 270,
            "height": 128,
            "pre_padding_seconds": 5.0,
            "post_padding_seconds": 10.0,
            "artifact_threshold": 0.35,
            "max_artifacts_per_file": 8,
            "medium_threshold": 0.50,
            "high_threshold": 0.68,
        },
        "clip": {
            "enabled": True,
            "crf": 28,
            "preset": "ultrafast",
            "audio": False,
        },
        "cloud_review": {
            "enabled": False,
            "provider": "gemini",
            "model": "gemini-2.5-flash-lite",
            "location": "global",
            "stage": "two-stage",
            "media_resolution": "low",
            "escalation_enabled": False,
            "escalation_model": "gemini-2.5-flash",
            "max_clips_per_run": 20,
            "max_clip_seconds_per_day": 1800,
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    print(f"created {output}")
    return 0


def license_info_command(args: argparse.Namespace) -> int:
    data = load_license(args.license)
    status, detail = license_status(data)
    license_data = data.get("license", {})
    print(
        json.dumps(
            {
                "status": status,
                "detail": detail,
                "customer_id": license_data.get("customer_id"),
                "site_id": license_data.get("site_id"),
                "plan": license_data.get("plan"),
                "expires_at": license_data.get("expires_at"),
                "max_cameras": license_data.get("max_cameras"),
                "features": license_data.get("features", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cloud_review_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    runtime_dir = resolve_runtime_dir(config, args.runtime_dir)
    cloud_cfg = config.get("cloud_review", {})
    project = args.project or cloud_cfg.get("project") or env("GOOGLE_CLOUD_PROJECT") or default_gcloud_project()
    location = args.location or cloud_cfg.get("location") or env("GOOGLE_CLOUD_LOCATION") or "global"
    model = args.model or cloud_cfg.get("model") or "gemini-2.5-flash-lite"
    requested_escalation_model = getattr(args, "escalation_model", None)
    escalation_model = (
        requested_escalation_model
        or cloud_cfg.get("escalation_model")
        or ("gemini-2.5-flash" if cloud_cfg.get("escalation_enabled") else None)
    )
    if not cloud_cfg.get("escalation_enabled") and not requested_escalation_model:
        escalation_model = None
    reviewed_clip_paths = set() if args.include_reviewed else load_cloud_reviewed_clip_paths(runtime_dir)
    limit = int(args.limit or cloud_cfg.get("max_clips_per_run") or 20)
    clips = (
        [Path(path) for path in args.clip]
        if args.clip
        else discover_candidate_clips(runtime_dir, limit, reviewed_clip_paths, getattr(args, "date", None))
    )
    if args.clip and reviewed_clip_paths:
        clips = [clip for clip in clips if str(clip) not in reviewed_clip_paths]

    if not clips:
        print(json.dumps({"reviewed": 0, "reason": "no clips selected"}, ensure_ascii=False))
        return 0
    if args.dry_run:
        print(json.dumps({"dry_run": True, "model": model, "clips": [str(path) for path in clips]}, indent=2))
        return 0
    if not project:
        raise SystemExit("Google Cloud project is required. Pass --project or set GOOGLE_CLOUD_PROJECT.")

    metadata_by_name, _ambiguous = load_local_clip_metadata(runtime_dir)
    output_paths = set()
    reviewed = 0
    for clip in clips[:limit]:
        output_path = cloud_review_output_path(runtime_dir, clip, metadata_by_name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_paths.add(str(output_path))
        try:
            if args.stage == "handover":
                result = review_clip_with_vertex(clip, project, location, model)
            else:
                result = two_stage_money_review(
                    clip,
                    project,
                    location,
                    model,
                    runtime_dir / "cloud-reviews" / "amount-frames",
                    escalation_model=escalation_model,
                )
        except CloudReviewError as exc:
            result = {
                "clip": str(clip),
                "model": model,
                "location": location,
                "stage": args.stage,
                "error": str(exc),
            }
        with output_path.open("a") as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(json.dumps(result, ensure_ascii=False))
        reviewed += 1
    print(json.dumps({"reviewed": reviewed, "outputs": sorted(output_paths)}, ensure_ascii=False))
    return 0


def daily_report_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    runtime_dir = resolve_runtime_dir(config, args.runtime_dir)
    suffix = "json" if args.format == "json" else "csv"
    output_path = (
        Path(args.output)
        if args.output
        else runtime_dir / "reports" / f"accounting-{args.date}.{suffix}"
    )
    if args.format == "json":
        rows, summary = write_daily_report_json(runtime_dir, args.date, output_path, bool(args.only_actionable))
    else:
        rows, summary = write_daily_report(runtime_dir, args.date, output_path, bool(args.only_actionable))
    print(
        json.dumps(
            {
                "date": args.date,
                "format": args.format,
                "rows": rows,
                "summary": summary,
                "output": str(output_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


def handover_report_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    runtime_dir = resolve_runtime_dir(config, args.runtime_dir)
    output_path = Path(args.output)
    rows, payload = write_handover_evidence_report(
        runtime_dir,
        config,
        Path(args.cloud_review_jsonl),
        output_path,
        args.date,
        float(args.min_handover_confidence),
        float(getattr(args, "min_suspected_confidence", 0.1)),
        int(getattr(args, "max_events_per_day", 10)),
        float(args.pre_seconds),
        float(args.post_seconds),
    )
    print(
        json.dumps(
            {
                "date": args.date or "mixed",
                "rows": rows,
                "summary": payload["summary"],
                "progress": payload["progress"],
                "output": str(output_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


def write_artifacts(reviewed: List[Dict[str, Any]], runtime_dir: Path, config: Dict[str, Any]) -> None:
    clip_cfg = config["clip"]
    review_cfg = config["review"]
    artifact_threshold = float(review_cfg.get("artifact_threshold", review_cfg["medium_threshold"]))
    max_artifacts = int(review_cfg.get("max_artifacts_per_file", 8))
    candidates = [
        event
        for event in reviewed
        if event["class"] in {"medium", "high"} or float(event["combined_score"]) >= artifact_threshold
    ][:max_artifacts]
    for index, event in enumerate(candidates, 1):
        source = Path(event["file"])
        base = safe_name(source.stem)
        stamp = f"{event['start_time'].replace(':', '')}-{event['end_time'].replace(':', '')}"
        score = f"{float(event['combined_score']):.3f}".replace(".", "p")
        prefix = f"{event['class']}_{score}_{stamp}_{base}"

        frame_times = {
            "start": float(event["start_offset_s"]),
            "mid": (float(event["start_offset_s"]) + float(event["end_offset_s"])) / 2,
            "end": float(event["end_offset_s"]),
        }
        for label, offset in frame_times.items():
            extract_frame(source, runtime_dir / "thumbs" / f"{prefix}_{label}.jpg", offset)

        if clip_cfg.get("enabled", True):
            start = max(0.0, float(event["start_offset_s"]) - float(review_cfg["pre_padding_seconds"]))
            duration = (
                float(event["end_offset_s"])
                - float(event["start_offset_s"])
                + float(review_cfg["pre_padding_seconds"])
                + float(review_cfg["post_padding_seconds"])
            )
            extract_clip(
                source,
                runtime_dir / "clips" / f"{prefix}.mp4",
                start,
                duration,
                int(clip_cfg["crf"]),
                str(clip_cfg["preset"]),
                bool(clip_cfg["audio"]),
            )


def ensure_runtime_dirs(runtime_dir: Path) -> None:
    for name in ["events", "clips", "thumbs", "state", "logs", "cloud-reviews"]:
        (runtime_dir / name).mkdir(parents=True, exist_ok=True)


def append_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def discover_candidate_clips(
    runtime_dir: Path,
    limit: int,
    reviewed_clip_paths: Optional[set] = None,
    source_date: Optional[str] = None,
) -> List[Path]:
    clips_dir = runtime_dir / "clips"
    if not clips_dir.exists():
        return []
    reviewed = reviewed_clip_paths or set()
    pending = [clip for clip in sorted(clips_dir.glob("*.mp4"), key=candidate_clip_sort_key) if str(clip) not in reviewed]
    if not pending:
        return []

    metadata_by_name, _ambiguous = load_local_clip_metadata(runtime_dir)
    if source_date:
        pending = [
            clip
            for clip in pending
            if metadata_by_name.get(clip.name) is not None and metadata_by_name[clip.name].source_date == source_date
        ]
    by_day: Dict[str, List[Path]] = defaultdict(list)
    undated: List[Path] = []
    for clip in pending:
        metadata = metadata_by_name.get(clip.name)
        if metadata and metadata.source_date:
            by_day[metadata.source_date].append(clip)
        else:
            undated.append(clip)

    selected: List[Path] = []
    for day in sorted(by_day):
        selected.extend(sorted(by_day[day], key=candidate_clip_sort_key)[: max(0, limit - len(selected))])
        if len(selected) >= limit:
            return selected[:limit]
    selected.extend(undated[: max(0, limit - len(selected))])
    return selected[:limit]


def candidate_clip_sort_key(path: Path) -> tuple:
    parts = path.name.split("_", 2)
    event_class = parts[0] if parts else ""
    score = 0.0
    if len(parts) > 1:
        try:
            score = float(parts[1].replace("p", "."))
        except ValueError:
            score = 0.0
    class_order = {"high": 0, "medium": 1, "low": 2}.get(event_class, 3)
    return (class_order, -score, path.name)


def cloud_review_output_path(runtime_dir: Path, clip: Path, metadata_by_name: Dict[str, Any]) -> Path:
    metadata = metadata_by_name.get(clip.name)
    source_date = getattr(metadata, "source_date", "") if metadata is not None else ""
    if not source_date:
        source_date = "unknown-source-date"
    return runtime_dir / "cloud-reviews" / "by-source-date" / source_date / f"cloud-reviewed-{source_date}.jsonl"


def source_date_for_path(path: Path) -> str:
    clip = parse_dahua_clip(path)
    if clip is None or not clip.date:
        return "unknown-source-date"
    return clip.date


def event_output_paths(runtime_dir: Path, source_date: str) -> tuple[Path, Path]:
    if not source_date:
        source_date = "unknown-source-date"
    base = runtime_dir / "events" / "by-source-date" / source_date
    return base / f"events-{source_date}.jsonl", base / f"reviewed-{source_date}.jsonl"


def load_cloud_reviewed_clip_paths(runtime_dir: Path) -> set:
    reviewed = set()
    paths = list((runtime_dir / "cloud-reviews").glob("*.jsonl"))
    paths.extend((runtime_dir / "cloud-reviews" / "by-source-date").glob("*/*.jsonl"))
    for path in paths:
        with path.open() as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                clip = row.get("clip")
                if clip and not row.get("error"):
                    reviewed.add(str(clip))
    return reviewed


def env(name: str) -> Optional[str]:
    import os

    value = os.environ.get(name)
    return value if value else None


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is required but was not found on PATH")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
