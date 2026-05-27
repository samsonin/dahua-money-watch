# Deployment Notes

This document intentionally uses placeholders. Do not commit real hostnames, IP addresses, archive roots, customer names, SSH users, or camera identifiers.

## First Deploy With Git Remote

1. Create a remote repository, for example on GitHub/GitLab.
2. Add it locally:

```bash
git remote add origin <git-remote-url>
git push -u origin main
```

3. Deploy to the server:

```bash
REMOTE=<ssh-target> PROJECT_DIR=<install-dir> ./scripts/deploy.sh
```

If `origin` exists, `scripts/deploy.sh` clones/pulls in `PROJECT_DIR`.
If `origin` does not exist yet, it falls back to `rsync` and copies the project without runtime data.

## Server Install

```bash
ssh <ssh-target>
cd <install-dir>
./scripts/install_server.sh
```

## Generic Customer Server Install

For a different server/customer, clone or copy the project to:

```text
<install-dir>
```

Then run:

```bash
cd <install-dir>
ARCHIVE_ROOT=<archive-root> SITE_ID=<site-id> ./scripts/install_any_server.sh
```

This creates:

```text
configs/sites/<site-id>.json
runtime/<site-id>/
```

Run manually:

```bash
. .venv/bin/activate
dahua-money-watch run-once --config configs/sites/<site-id>.json
```

This installs:

- `ffmpeg`
- Python virtualenv
- package dependencies
- `dahua-money-watch.service`
- `dahua-money-watch.timer`

## Updating Later

After pushing new code:

```bash
REMOTE=<ssh-target> PROJECT_DIR=<install-dir> ./scripts/deploy.sh
ssh <ssh-target> 'cd <install-dir> && . .venv/bin/activate && pip install -e . && systemctl restart dahua-money-watch.timer'
```

## Runtime Outputs

```text
<install-dir>/runtime/events
<install-dir>/runtime/clips
<install-dir>/runtime/thumbs
<install-dir>/runtime/state
<install-dir>/runtime/logs
```

The Git repo should never store runtime video, clips, thumbnails, or SQLite state.
