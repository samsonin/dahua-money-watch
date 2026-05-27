#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
SERVICE_USER="${SERVICE_USER:-root}"

cd "$PROJECT_DIR"

apt-get update
apt-get install -y ffmpeg python3-venv python3-pip

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .

mkdir -p "$PROJECT_DIR/runtime"/{events,clips,thumbs,state,logs}

sed "s#__PROJECT_DIR__#$PROJECT_DIR#g" deploy/systemd/dahua-money-watch.service > /etc/systemd/system/dahua-money-watch.service
install -m 0644 deploy/systemd/dahua-money-watch.timer /etc/systemd/system/dahua-money-watch.timer

systemctl daemon-reload
systemctl enable --now dahua-money-watch.timer
systemctl status dahua-money-watch.timer --no-pager

echo "Installed dahua-money-watch in $PROJECT_DIR"
