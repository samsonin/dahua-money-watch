#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
STATE_DIR="$PROJECT_DIR/runtime/state/handover-compare-sent"
CLOUD_REVIEW_ROOT="$PROJECT_DIR/runtime/cloud-reviews/by-source-date"
HANDOVER_COMPARE_STATE_VERSION="${HANDOVER_COMPARE_STATE_VERSION:-handover-evidence-schema-1.1-suspected-v2}"

mkdir -p "$STATE_DIR"

if [[ ! -d "$CLOUD_REVIEW_ROOT" ]]; then
  echo "No source-date cloud review directory: $CLOUD_REVIEW_ROOT"
  exit 0
fi

sent_any=0
while IFS= read -r -d '' cloud_file; do
  date_dir="$(basename "$(dirname "$cloud_file")")"
  expected_name="cloud-reviewed-$date_dir.jsonl"
  if [[ "$(basename "$cloud_file")" != "$expected_name" ]]; then
    continue
  fi

  cloud_hash="$(sha256sum "$cloud_file" | awk '{print $1}')"
  current_hash="$(printf '%s %s\n' "$HANDOVER_COMPARE_STATE_VERSION" "$cloud_hash" | sha256sum | awk '{print $1}')"
  state_file="$STATE_DIR/$date_dir.sha256"
  previous_hash=""
  if [[ -f "$state_file" ]]; then
    previous_hash="$(cat "$state_file")"
  fi

  if [[ "$current_hash" == "$previous_hash" ]]; then
    echo "unchanged date=$date_dir"
    continue
  fi

  echo "sending date=$date_dir"
  "$PROJECT_DIR/scripts/run_handover_compare.sh" "$date_dir"
  printf '%s\n' "$current_hash" > "$state_file"
  sent_any=1
done < <(find "$CLOUD_REVIEW_ROOT" -mindepth 2 -maxdepth 2 -type f -name 'cloud-reviewed-*.jsonl' -print0 | sort -z)

if [[ "$sent_any" -eq 0 ]]; then
  echo "no changed daily cloud review files"
fi
