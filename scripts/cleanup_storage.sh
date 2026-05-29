#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CONFIG="${CONFIG:-$PROJECT_DIR/configs/production.json}"
TARGET_USED_GB="${TARGET_USED_GB:-60}"
LOW_WATERMARK_GB="${LOW_WATERMARK_GB:-58}"
KEEP_RECENT_DAYS="${KEEP_RECENT_DAYS:-7}"
DRY_RUN="${DRY_RUN:-0}"
LOG_PREFIX="dahua-money-watch-cleanup"

python_bin="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  python_bin="python3"
fi

read_config_value() {
  local key="$1"
  "$python_bin" - "$CONFIG" "$key" <<'PY'
import json
import sys
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text())
print(config.get(sys.argv[2], ""))
PY
}

archive_root="$(read_config_value archive_root)"
if [[ -z "$archive_root" ]]; then
  echo "$LOG_PREFIX: archive_root is required in $CONFIG" >&2
  exit 2
fi

archive_root="$(cd "$archive_root" && pwd)"
mount_point="$(df -P "$PROJECT_DIR" | awk 'NR==2 {print $6}')"

used_gb() {
  df -BG --output=used "$mount_point" | awk 'NR==2 {gsub(/G/, "", $1); print $1}'
}

delete_path() {
  local path="$1"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "$LOG_PREFIX: dry-run delete $path"
    return
  fi
  rm -rf --one-file-system -- "$path"
  echo "$LOG_PREFIX: deleted $path"
}

should_stop() {
  local used
  used="$(used_gb)"
  [[ "$used" -le "$LOW_WATERMARK_GB" ]]
}

current_used="$(used_gb)"
if [[ "$current_used" -le "$TARGET_USED_GB" ]]; then
  echo "$LOG_PREFIX: used=${current_used}G target=${TARGET_USED_GB}G no cleanup needed"
  exit 0
fi

echo "$LOG_PREFIX: used=${current_used}G target=${TARGET_USED_GB}G low_watermark=${LOW_WATERMARK_GB}G starting cleanup"

today_epoch="$(date +%s)"
while IFS= read -r day_dir; do
  day_name="$(basename "$day_dir")"
  day_epoch="$(date -d "$day_name" +%s 2>/dev/null || echo 0)"
  if [[ "$day_epoch" -eq 0 ]]; then
    continue
  fi
  age_days="$(( (today_epoch - day_epoch) / 86400 ))"
  if [[ "$age_days" -lt "$KEEP_RECENT_DAYS" ]]; then
    continue
  fi
  delete_path "$day_dir"
  if should_stop; then
    echo "$LOG_PREFIX: reached low watermark after archive cleanup"
    exit 0
  fi
done < <(find "$archive_root" -mindepth 1 -maxdepth 1 -type d -regextype posix-extended -regex '.*/[0-9]{4}-[0-9]{2}-[0-9]{2}' -printf '%p\n' | sort)

echo "$LOG_PREFIX: finished used=$(used_gb)G; runtime outputs are preserved"
