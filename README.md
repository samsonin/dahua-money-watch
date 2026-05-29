# Dahua Money Watch

CPU-friendly payment-event detector and accounting handoff pipeline for Dahua `.dav` camera archives.

The project is designed as a portable self-hosted product:

- install path: choose a host-specific directory
- per-site configs: `<install-dir>/configs/sites/<site-id>.json`
- per-site runtime output: `<install-dir>/runtime/<site-id>`
- first stage: cheap ROI motion detection with `ffmpeg + numpy`
- second stage: cheap visual re-score and cloud review of only short candidate clips
- optional escalation: re-check uncertain clips with a stronger model
- final handoff: daily JSON payloads for an accounting/CRM comparison service
- evidence: short handover clips with audio, suitable for review from another system

It is intentionally conservative about exact amounts. The pipeline separates
confirmed cash handovers from suspicious payment-like interactions, then sends
both with different statuses so downstream systems can decide what needs a human
review.

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
To reduce manual review, enable economical escalation for uncertain clips:

```json
"cloud_review": {
  "model": "gemini-2.5-flash-lite",
  "stage": "two-stage",
  "escalation_enabled": true,
  "escalation_model": "gemini-2.5-flash"
}
```

Escalation runs only after the first pass leaves the final action as
`manual_review`. It sends extracted frames, not the whole original archive, and
can return `ignore`, `crm_compare_candidate`, `crm_compare`, or `manual_review`.
When multiple archive days are waiting, cloud review prioritizes the oldest
source day first so daily accounting reports become complete one by one.

## Handover Evidence Report

After cloud review, build a daily evidence JSON file for cash/payment comparison:

```bash
dahua-money-watch handover-report \
  --config configs/production.json \
  --cloud-review-jsonl runtime/cloud-reviews/by-source-date/2026-05-27/cloud-reviewed-2026-05-27.jsonl \
  --date 2026-05-27 \
  --output runtime/reports/handover-evidence-2026-05-27.json
```

The report contains only one source day. It writes short audio/video evidence
clips under `runtime/handover-clips/by-source-date/<date>/` and includes both a
relative path and, when configured, a ready-to-use URL:

```json
{
  "evidence": {
    "handover_clip": "handover-clips/by-source-date/2026-05-27/example_handover.mp4",
    "handover_clip_url": "https://<public-host>/evidence-clips/by-source-date/2026-05-27/example_handover.mp4"
  }
}
```

The handover report exports two review statuses:

- `confirmed_cash_handover`: cash handover is visible enough to treat as a confirmed event, but the amount can still be unknown or estimated.
- `suspected_payment_interaction`: the clip looks like a payment/counter interaction, but cash or amount is not reliable enough to call confirmed.

Accounting comparison statuses use these values:

- `handover_confirmed_amount_estimated`: send to accounting as a confirmed handover where the amount is not guaranteed.
- `payment_interaction_suspected`: show as a review candidate; do not treat it as a proven discrepancy by itself.

By default the daily evidence export keeps confirmed events first and fills the
remaining slots with the strongest suspected interactions:

```bash
MIN_HANDOVER_CONFIDENCE=0.8 \
MIN_SUSPECTED_CONFIDENCE=0.1 \
MAX_EVENTS_PER_DAY=10 \
scripts/run_handover_compare.sh 2026-05-27
```

## Accounting Compare Handoff

`scripts/run_handover_compare.sh` builds the daily handover evidence file and
sends it to an external accounting compare endpoint:

```bash
scripts/run_handover_compare.sh 2026-05-27
```

Configuration is intentionally kept outside the repository:

```bash
CASH_COMPARE_URL=https://<accounting-host>/integrations/cash-payments/compare
CASH_COMPARE_SECRET=<shared-secret>
```

The sender reads these from `configs/cash-compare.env` by default or from the
environment. Do not commit real endpoints, domains, customer names, or secrets.

To process all changed daily cloud-review files, use:

```bash
scripts/run_handover_compare_pending.sh
```

It stores sent-state hashes under `runtime/state/handover-compare-sent/`. The
hash includes a report schema/version marker so changing the report logic can
trigger a resend without modifying the source cloud-review JSONL.

## Daily Accounting Report

After local filtering and cloud review, write one CSV file for an archive day:

```bash
dahua-money-watch daily-report \
  --config configs/production.json \
  --date 2026-05-27
```

The report is written to `runtime/reports/accounting-YYYY-MM-DD.csv` by default.
It includes event time, source clip name, final action, payment status, amount
status, amount, currency, confidence, and model evidence. Add
`--only-actionable` to exclude ignored clips.
When escalation is enabled, `crm_compare_candidate` means the event is automated
for candidate comparison even though the amount or evidence is less certain than
a full `crm_compare`.

For CRM/accounting integrations, write the same report as typed JSON:

```bash
dahua-money-watch daily-report \
  --config configs/production.json \
  --date 2026-05-27 \
  --format json
```

## Evidence Clip URLs

Evidence clip serving should be configured by deployment, not hard-coded in the
repository. Set a base URL in config or environment:

```json
{
  "evidence": {
    "clip_base_url": "https://<public-host>/evidence-clips"
  }
}
```

or:

```bash
EVIDENCE_CLIPS_BASE_URL=https://<public-host>/evidence-clips
```

If a backend stores only the relative path
`handover-clips/by-source-date/<date>/<file>.mp4`, it can build the public URL by
removing the `handover-clips/` prefix and appending the result to the clip base
URL. Keep Basic Auth or signed URL credentials on the backend; do not expose
them to browser code.

## Storage Cleanup

The repository includes a cron-friendly cleanup script:

```bash
DRY_RUN=1 scripts/cleanup_storage.sh
```

Defaults:

- `TARGET_USED_GB=60`
- `LOW_WATERMARK_GB=58`
- `KEEP_RECENT_DAYS=7`

Cleanup deletes only original camera archive day folders matching
`<archive-root>/YYYY-MM-DD`, oldest first. It does not delete runtime outputs:
events, cloud review JSONL files, reports, state, generated clips, thumbnails, or
handover evidence.

The cron template runs hourly:

```text
deploy/cron/dahua-money-watch-cleanup
```

Example cost shape for a small shop archive:

- source video per day: 1-3 hours of motion-triggered clips
- expected candidate video sent to model: 5-25 minutes/day after local filtering
- Gemini 2.5 Flash-Lite: roughly `$0.02-$0.05/day`
- Gemini 2.5 Flash: roughly `$0.08-$0.16/day`
