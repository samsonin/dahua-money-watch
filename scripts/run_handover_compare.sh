#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CONFIG="${CONFIG:-$PROJECT_DIR/configs/production.json}"
DATE="${1:-${DATE:-}}"
MIN_HANDOVER_CONFIDENCE="${MIN_HANDOVER_CONFIDENCE:-0.8}"
PRE_SECONDS="${PRE_SECONDS:-3}"
POST_SECONDS="${POST_SECONDS:-5}"

cd "$PROJECT_DIR"

if [[ -z "$DATE" ]]; then
  echo "Usage: $0 YYYY-MM-DD" >&2
  exit 2
fi

CLOUD_REVIEW_JSONL="$PROJECT_DIR/runtime/cloud-reviews/by-source-date/$DATE/cloud-reviewed-$DATE.jsonl"
OUTPUT="$PROJECT_DIR/runtime/reports/handover-evidence-$DATE.json"

if [[ ! -f "$CLOUD_REVIEW_JSONL" ]]; then
  echo "Cloud review file not found for $DATE: $CLOUD_REVIEW_JSONL" >&2
  exit 2
fi

"$PROJECT_DIR/.venv/bin/dahua-money-watch" handover-report \
  --config "$CONFIG" \
  --cloud-review-jsonl "$CLOUD_REVIEW_JSONL" \
  --date "$DATE" \
  --output "$OUTPUT" \
  --min-handover-confidence "$MIN_HANDOVER_CONFIDENCE" \
  --pre-seconds "$PRE_SECONDS" \
  --post-seconds "$POST_SECONDS"

"$PROJECT_DIR/scripts/send_cash_compare.sh" "$OUTPUT"
