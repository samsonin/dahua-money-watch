#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${REMOTE:-}" ]]; then
  echo "REMOTE is required, for example: REMOTE=<ssh-target> $0" >&2
  exit 2
fi

if [[ -z "${PROJECT_DIR:-}" ]]; then
  echo "PROJECT_DIR is required, for example: PROJECT_DIR=<install-dir> $0" >&2
  exit 2
fi

BRANCH="${BRANCH:-main}"

ssh "$REMOTE" "mkdir -p '$PROJECT_DIR'"

if ssh "$REMOTE" "test -d '$PROJECT_DIR/.git'"; then
  ssh "$REMOTE" "cd '$PROJECT_DIR' && git fetch --all && git checkout '$BRANCH' && git pull --ff-only"
else
  if git remote get-url origin >/dev/null 2>&1; then
    ORIGIN="$(git remote get-url origin)"
    ssh "$REMOTE" "git clone '$ORIGIN' '$PROJECT_DIR' && cd '$PROJECT_DIR' && git checkout '$BRANCH'"
  else
    rsync -az --delete \
      --exclude '.git' \
      --exclude '.venv' \
      --exclude 'runtime' \
      --exclude '__pycache__' \
      ./ "$REMOTE:$PROJECT_DIR/"
  fi
fi

echo "Deployed to $REMOTE:$PROJECT_DIR"
