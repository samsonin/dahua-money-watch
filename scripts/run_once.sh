#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"
. .venv/bin/activate
exec dahua-money-watch run-once --config configs/production.example.json "$@"
