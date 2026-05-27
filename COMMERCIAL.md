# Commercialization Plan

This project is structured as a self-hosted product that can be installed on any server that stores Dahua-compatible `.dav` files.

## Product Shape

Name placeholder:

```text
Dahua Money Watch
```

Core value:

- detects likely payment / money handover moments in store camera archives;
- runs locally on weak CPU servers;
- stores only short candidate clips and keyframes;
- optionally sends only candidate clips to a cloud visual model;
- keeps full video archive on the customer server.

## Deployment Model

Recommended commercial package:

```text
<install-dir>
  app code
  configs/sites/<site-id>.json
  runtime/<site-id>/
```

One installation can support multiple stores/cameras by using separate config files.

## Monetization Options

### Option A: One-Time Setup + Monthly Support

- installation fee per server;
- monthly support/maintenance fee;
- customer pays cloud model usage directly through their Google account.

Good for early deployments.

### Option B: Per-Camera Subscription

- base fee per camera per month;
- includes updates, monitoring, and support;
- cloud usage can be included with a fair-use cap.

Suggested packaging:

- Starter: local-only candidate clips.
- Standard: local candidate clips + Gemini review.
- Pro: multi-camera, reports, alerting, cloud dashboard.

### Option C: BYO Cloud Key

Customer provides:

- `GOOGLE_API_KEY` or Vertex AI service account;
- billing stays under customer control;
- your fee covers software license/support.

This avoids you becoming responsible for cloud overage.

## License Hooks

The current project includes a soft license config:

```text
configs/license.example.json
```

It is intentionally not DRM. It records:

- customer id;
- site id;
- licensed camera count;
- expiry date;
- enabled features;
- cloud review permission.

For production sales, add a signed license token later. Do not block early field trials on heavy DRM.

## Privacy / Security Positioning

- full camera archive stays on customer server;
- only short event clips are exported;
- cloud review is optional;
- no customer clips are committed to Git;
- runtime data is ignored by `.gitignore`.

## Roadmap To Sellable V1

1. Installer that creates a site config interactively.
2. License file validation and usage summary.
3. Gemini review command for candidate clips.
4. Daily HTML/PDF report.
5. Optional Telegram/email notifications.
6. Simple web UI for reviewing events.
7. Multi-site deployment scripts.
