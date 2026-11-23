#!/usr/bin/env python3
"""Generate the static dashboard: reads tracker.db, writes docs/data.json."""

import datetime
import json
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "tracker.db"
OUT = BASE / "docs" / "data.json"


def main():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    pages = []
    for r in db.execute("SELECT * FROM pages ORDER BY lastmod DESC"):
        snap = db.execute(
            "SELECT content FROM snapshots WHERE url=? ORDER BY id DESC LIMIT 1", (r["url"],)
        ).fetchone()
        pages.append(
            {
                "url": r["url"],
                "site": r["site"],
                "title": r["title"] or r["url"],
                "lastmod": r["lastmod"],
                "status": r["status"],
                "first_seen": r["first_seen"],
                "last_checked": r["last_checked"],
                "last_changed": r["last_changed"],
                "content": snap["content"] if snap else "",
            }
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
        f"Wrote {OUT} — {len(pages)} pages, {len(events)} change events, "
        f"{OUT.stat().st_size / 1024:.0f} KB"
    )


if __name__ == "__main__":
    main()
