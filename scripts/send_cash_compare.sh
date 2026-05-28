#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="${CASH_COMPARE_ENV_FILE:-$PROJECT_DIR/configs/cash-compare.env}"
REPORT_FILE="${1:-}"
COMPARE_URL="${2:-${CASH_COMPARE_URL:-}}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

COMPARE_URL="${2:-${CASH_COMPARE_URL:-}}"
SECRET="${CASH_COMPARE_SECRET:-}"

if [[ -z "$REPORT_FILE" ]]; then
  echo "Usage: $0 <accounting-report.json> [compare-url]" >&2
  exit 2
fi

if [[ ! -f "$REPORT_FILE" ]]; then
  echo "Report file not found: $REPORT_FILE" >&2
  exit 2
fi

if [[ -z "$COMPARE_URL" ]]; then
  echo "CASH_COMPARE_URL is required, or pass the full compare URL as the second argument." >&2
  exit 2
fi

if [[ -z "$SECRET" ]]; then
  echo "CASH_COMPARE_SECRET is required in environment or $ENV_FILE." >&2
  exit 2
fi

curl --fail --show-error --silent \
  --request POST "$COMPARE_URL" \
  --header "Content-Type: application/json" \
  --header "X-Cash-Compare-Secret: $SECRET" \
  --data-binary "@$REPORT_FILE"

echo
