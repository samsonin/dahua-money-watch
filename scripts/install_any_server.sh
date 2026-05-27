#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
SITE_ID="${SITE_ID:-default-site}"
ARCHIVE_ROOT="${ARCHIVE_ROOT:-}"

if [[ -z "$ARCHIVE_ROOT" ]]; then
  echo "ARCHIVE_ROOT is required, for example:"
  echo "ARCHIVE_ROOT=<archive-root> PROJECT_DIR=$PROJECT_DIR SITE_ID=<site-id> $0"
  exit 1
fi

apt-get update
apt-get install -y ffmpeg python3-venv python3-pip

cd "$PROJECT_DIR"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .

mkdir -p "configs/sites" "runtime/$SITE_ID"/{events,clips,thumbs,state,logs}

if [[ ! -f "configs/sites/$SITE_ID.json" ]]; then
  dahua-money-watch init-site \
    --site-id "$SITE_ID" \
    --archive-root "$ARCHIVE_ROOT" \
    --output "configs/sites/$SITE_ID.json"
fi

echo "Installed site config: $PROJECT_DIR/configs/sites/$SITE_ID.json"
echo "Run once with:"
echo "$PROJECT_DIR/.venv/bin/dahua-money-watch run-once --config $PROJECT_DIR/configs/sites/$SITE_ID.json"
