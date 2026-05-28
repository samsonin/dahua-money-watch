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
chmod +x "$PROJECT_DIR/scripts/run_handover_compare.sh" "$PROJECT_DIR/scripts/run_handover_compare_pending.sh" 2>/dev/null || true

sed "s#__PROJECT_DIR__#$PROJECT_DIR#g" deploy/systemd/dahua-money-watch.service > /etc/systemd/system/dahua-money-watch.service
install -m 0644 deploy/systemd/dahua-money-watch.timer /etc/systemd/system/dahua-money-watch.timer
sed "s#__PROJECT_DIR__#$PROJECT_DIR#g" deploy/systemd/dahua-money-watch-cloud.service > /etc/systemd/system/dahua-money-watch-cloud.service
install -m 0644 deploy/systemd/dahua-money-watch-cloud.timer /etc/systemd/system/dahua-money-watch-cloud.timer
sed "s#__PROJECT_DIR__#$PROJECT_DIR#g" deploy/systemd/dahua-money-watch-handover-compare.service > /etc/systemd/system/dahua-money-watch-handover-compare.service
install -m 0644 deploy/systemd/dahua-money-watch-handover-compare.timer /etc/systemd/system/dahua-money-watch-handover-compare.timer

systemctl daemon-reload
systemctl enable --now dahua-money-watch.timer
systemctl enable --now dahua-money-watch-cloud.timer
systemctl enable --now dahua-money-watch-handover-compare.timer
systemctl status dahua-money-watch.timer --no-pager

echo "Installed dahua-money-watch in $PROJECT_DIR"
