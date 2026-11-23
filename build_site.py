#!/usr/bin/env python3
"""Generate the static dashboard: reads tracker.db, writes docs/data.json
plus per-page content files in docs/p/ (loaded on demand by the page view)."""

import datetime
import hashlib
import json
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "tracker.db"
OUT = BASE / "docs" / "data.json"
PAGES_DIR = BASE / "docs" / "p"


def page_key(url):
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def main():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    for old in PAGES_DIR.glob("*.json"):
        old.unlink()

    pages = []
    for r in db.execute("SELECT * FROM pages ORDER BY lastmod DESC"):
        snap = db.execute(
            "SELECT content, content_html FROM snapshots WHERE url=? ORDER BY id DESC LIMIT 1",
            (r["url"],),
        ).fetchone()
        key = page_key(r["url"])
        pages.append(
            {
                "key": key,
                "url": r["url"],
                "site": r["site"],
                "title": r["title"] or r["url"],
                "lastmod": r["lastmod"],
                "status": r["status"],
                "first_seen": r["first_seen"],
                "last_checked": r["last_checked"],
                "last_changed": r["last_changed"],
            }
        )
        (PAGES_DIR / f"{key}.json").write_text(
            json.dumps(
                {
                    "url": r["url"],
                    "title": r["title"] or r["url"],
                    "content": snap["content"] if snap else "",
                    "content_html": (snap["content_html"] or "") if snap else "",
                },
                ensure_ascii=False,
            )
        )

    events = []
    for r in db.execute(
        "SELECT e.*, p.title FROM events e LEFT JOIN pages p ON p.url = e.url"
        " WHERE e.kind != 'baseline' ORDER BY e.id DESC"
    ):
        events.append(
            {
                "id": r["id"],
                "url": r["url"],
                "site": r["site"],
                "kind": r["kind"],
                "detected_at": r["detected_at"],
                "old_lastmod": r["old_lastmod"],
                "new_lastmod": r["new_lastmod"],
                "title": r["title"] or r["url"],
                "diff": r["diff"],
            }
        )

    baseline = db.execute("SELECT MIN(first_seen) FROM pages").fetchone()[0]
    last_check = db.execute("SELECT MAX(last_checked) FROM pages").fetchone()[0]
    data = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baseline_at": baseline,
        "last_check": last_check,
        "pages": pages,
        "events": events,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False))
    print(
        f"Wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB) + {len(pages)} page files — "
        f"{len(events)} change events"
    )


if __name__ == "__main__":
    main()
