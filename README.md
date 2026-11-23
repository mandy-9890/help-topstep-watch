# Topstep / TopstepX Help-Center Change Tracker

Watches both help centers and records **before/after diffs** whenever a page changes.
Publishes a public dashboard anyone can open — no install, no login.

- `help.topstep.com` (Intercom) — program rules, payouts, loss limits
- `help.topstepx.com` (GitBook) — platform docs, risk settings, API

## Public dashboard (GitHub Pages)

The `docs/` folder is a static web app (dashboard, searchable page list,
before/after diff viewer, page history). A check runs every 30 minutes:
check for changes → rebuild `docs/data.json` → commit + push to `main`.
GitHub Pages publishes `docs/` from `main` directly, so every push deploys
the site automatically (no Pages Actions needed).

One-time setup (already done for this repo):
1. Public repo: `mandy-9890/help-topstep-watch`.
2. Repo **Settings → Pages → Source: Deploy from a branch → main / docs**.
3. Local `launchd` agent (`~/Library/LaunchAgents/com.topstepwatch.check.plist`)
   runs `watch_local.sh` every 1800 seconds — this is the primary scheduler.
4. `.github/workflows/watch.yml` is the cloud fallback / manual trigger (Actions tab → watch → Run workflow).

Public link: **https://mandy-9890.github.io/help-topstep-watch/**

## How it works

1. Reads each site's public sitemap (one request covers all pages, each with a `lastmod` timestamp).
2. First run saves a **baseline snapshot** of every page's text into `tracker.db` (SQLite).
3. Later runs compare timestamps; when one moves, the page is re-fetched and its
   **content hash** is compared (filters out GitBook rebuild noise / false positives).
4. Real changes get a new snapshot + a unified **before/after diff**, logged to the
   `events` table and appended to `CHANGELOG.md`.
5. New pages and deleted pages are also detected and logged.

## Usage

```bash
python3 tracker.py run                 # check for changes (run every 30 min)
python3 tracker.py run --full          # re-fetch everything, catches edits without timestamp bumps
python3 tracker.py run --site topstep  # only one site

python3 tracker.py log                 # recent changes
python3 tracker.py diff "loss limit"   # latest before/after diff (keyword matches URL or title)
python3 tracker.py history "payout"    # full event timeline for matching pages
python3 tracker.py pages               # all pages, most recently updated first
```

## Scheduling (macOS)

Installed and running: `~/Library/LaunchAgents/com.topstepwatch.check.plist`
fires `~/help-topstep-watch/watch_local.sh` every 1800 seconds. It pulls, runs
the check, rebuilds the site, commits and pushes if anything changed. Logs go
to `~/help-topstep-watch/watch.log`.

The scheduler runs from the home-folder clone (not `Desktop/`) because macOS
privacy rules block launchd from reading files on the Desktop.

Useful commands:

```
launchctl list | grep topstepwatch                  # verify it's loaded
tail -f watch.log                                   # follow checks
launchctl kickstart -k gui/501/com.topstepwatch.check  # force a run now
```

The GitHub workflow also has a `0,30` cron plus a weekly `run --full`, but
GitHub's scheduler is best-effort and did not fire reliably for this repo.

## Files

- `tracker.py` — the tracker (Python stdlib only, no dependencies)
- `build_site.py` — generates `docs/data.json` from the database
- `docs/` — static dashboard (index.html, app.js, style.css, data.json)
- `tracker.db` — SQLite: `pages`, `snapshots` (full text history), `events` (diffs)
- `CHANGELOG.md` — human-readable feed of adds/changes/removals
- `watch_local.sh` — local 30-min check + push (driven by launchd)
- `.github/workflows/watch.yml` — cloud fallback / manual trigger (no Pages deploy action)

## Notes

- History starts from the first baseline run; earlier versions aren't publicly available.
- Respects `crawl-delay: 1` on topstep.com; sends a browser User-Agent (GitBook 403s default agents).
- Query diffs directly if needed: `sqlite3 tracker.db "SELECT diff FROM events WHERE kind='changed' ORDER BY id DESC LIMIT 1"`
