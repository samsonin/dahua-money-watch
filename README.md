# Dahua Money Watch

CPU-friendly payment-event pre-filter for Dahua `.dav` camera archives.

The project is designed as a portable self-hosted product:

- install path: choose a host-specific directory
- per-site configs: `<install-dir>/configs/sites/<site-id>.json`
- per-site runtime output: `<install-dir>/runtime/<site-id>`
- first stage: cheap ROI motion detection with `ffmpeg + numpy`
- second stage: cheap visual re-score and optional cloud review of only short candidate clips

It does not claim to prove a payment handover by itself. It narrows a full day of video to short review clips.

## Commercial / Portable Install

Create a site config for any server that stores Dahua `.dav` files:

```bash
dahua-money-watch init-site \
  --site-id store-001 \
  --site-name "Store 001" \
  --archive-root <archive-root> \
  --timezone UTC \
  --roi 0,320,540,256 \
  --output configs/sites/store-001.json
```

Run it:

```bash
dahua-money-watch run-once --config configs/sites/store-001.json
```

Check a license file:

```bash
dahua-money-watch license-info --license configs/license.example.json
```

## Local Install

```bash
cd dahua-money-watch
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

`ffmpeg` must be available on `PATH`.

## One-Off Run

```bash
dahua-money-watch run-once \
  --config configs/production.json \
  --date 2026-05-27
```

For local testing against another archive root:

```bash
dahua-money-watch run-once \
  --config configs/production.example.json \
  --archive-root <local-archive-root> \
  --pattern "*/*.dav" \
  --runtime-dir runtime/local-test
```

## Server Deploy Shape

The repo should be cloned to:

```text
<install-dir>
```

Runtime files are written under:

```text
<install-dir>/runtime
```

Use `scripts/deploy.sh` after setting `REMOTE` and optionally `BRANCH`:

```bash
REMOTE=<ssh-target> PROJECT_DIR=<install-dir> ./scripts/deploy.sh
```

Then on the server:

```bash
cd <install-dir>
sudo ./scripts/install_server.sh
```

For a generic customer server where the archive root differs:

```bash
ARCHIVE_ROOT=<archive-root> \
SITE_ID=customer-store-001 \
./scripts/install_any_server.sh
```

## Google / Gemini Review

The local pipeline creates candidate clips first. Cloud review should only receive clips from `runtime/clips`, not the original day archive.

Local smoke test with Vertex AI:

```bash
gcloud auth login
gcloud config set project <google-cloud-project>
dahua-money-watch cloud-review \
  --config configs/production.example.json \
  --clip <candidate-clip.mp4> \
  --limit 1 \
  --stage two-stage
```

The default two-stage mode first returns `ignore`, `manual_review`, or `likely_payment`.
Only `likely_payment` clips get a second amount-estimation request with
`amount`, `amount_confidence`, and `amount_status`.

Example cost shape for a small shop archive:

- source video per day: 1-3 hours of motion-triggered clips
- expected candidate video sent to model: 5-25 minutes/day after local filtering
- Gemini 2.5 Flash-Lite: roughly `$0.02-$0.05/day`
- Gemini 2.5 Flash: roughly `$0.08-$0.16/day`
