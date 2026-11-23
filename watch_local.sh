#!/bin/bash
# Local 30-minute watcher for help-topstep-watch.
# Runs the check, rebuilds the dashboard, and pushes to main (Pages auto-deploys).
set -euo pipefail

REPO="/Users/mandarnirantar/help-topstep-watch"
PY="/opt/homebrew/bin/python3"
GIT="/usr/bin/git"
LOCK="/tmp/topstep-watch.lock"
LOG="$REPO/watch.log"

cd "$REPO"

# Prevent overlapping runs (a check can take a few minutes).
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "$(date -u +%FT%TZ) another run is active, skipping" >> "$LOG"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

echo "$(date -u +%FT%TZ) starting local watch run" >> "$LOG"

"$GIT" pull --rebase >> "$LOG" 2>&1
"$PY" tracker.py run >> "$LOG" 2>&1
"$PY" build_site.py >> "$LOG" 2>&1

"$GIT" add tracker.db docs CHANGELOG.md
if ! "$GIT" diff --cached --quiet; then
  "$GIT" -c user.name="topstep-watch-bot" -c user.email="actions@users.noreply.github.com" \
    commit -m "watch: update snapshots and dashboard" >> "$LOG" 2>&1
  "$GIT" push >> "$LOG" 2>&1
  echo "$(date -u +%FT%TZ) pushed updated state" >> "$LOG"
else
  echo "$(date -u +%FT%TZ) no changes" >> "$LOG"
fi
