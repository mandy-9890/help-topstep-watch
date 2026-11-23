#!/usr/bin/env python3
"""
Topstep / TopstepX help-center change tracker.

Watches both help centers via their public sitemaps. On first run it saves a
baseline snapshot of every page. On later runs it detects changes (via
lastmod timestamps, confirmed by content hash) and records a before/after
diff for every real change.

Usage:
    python3 tracker.py run              # check for changes (baseline on first run)
    python3 tracker.py run --full       # re-fetch every page, catch silent edits
    python3 tracker.py run --site topstep
    python3 tracker.py log              # recent change events
    python3 tracker.py diff <keyword>   # latest before/after diff for a page
    python3 tracker.py history <keyword># all events for a page
    python3 tracker.py pages            # all tracked pages, newest first

Stdlib only. Data lives in tracker.db; human-readable feed in CHANGELOG.md.
"""

import argparse
import datetime
import difflib
import hashlib
import html as htmlmod
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "tracker.db"
CHANGELOG = BASE / "CHANGELOG.md"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SITES = {
    "topstep": {
        "sitemap": "https://help.topstep.com/sitemap.xml",
        "content_tag": "article",   # Intercom
        "delay": 1.0,               # robots.txt crawl-delay
    },
    "topstepx": {
        "sitemap": "https://help.topstepx.com/sitemap-pages.xml",
        "content_tag": "main",      # GitBook
        "delay": 0.5,
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url          TEXT PRIMARY KEY,
    site         TEXT NOT NULL,
    title        TEXT,
    lastmod      TEXT,
    content_hash TEXT,
    status       TEXT DEFAULT 'active',
    first_seen   TEXT,
    last_checked TEXT,
    last_changed TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    lastmod    TEXT,
    content    TEXT NOT NULL,
    content_html TEXT
);
CREATE INDEX IF NOT EXISTS idx_snapshots_url ON snapshots(url, id);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL,
    site        TEXT NOT NULL,
    kind        TEXT NOT NULL,      -- baseline | added | changed | removed
    detected_at TEXT NOT NULL,
    old_lastmod TEXT,
    new_lastmod TEXT,
    diff        TEXT
);
"""


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"fetch failed for {url}: {last_err}")


def parse_sitemap(url, seen=None):
    """Return {url: lastmod_or_None}; follows sitemap indexes."""
    seen = seen or set()
    if url in seen:
        return {}
    seen.add(url)
    xml = fetch(url)
    if "<sitemapindex" in xml:
        out = {}
        for child in re.findall(r"<sitemap>\s*<loc>(.*?)</loc>", xml, re.S):
            out.update(parse_sitemap(child.strip(), seen))
        return out
    out = {}
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>(.*?)</loc>", block, re.S)
        mod = re.search(r"<lastmod>(.*?)</lastmod>", block, re.S)
        if loc:
            out[loc.group(1).strip()] = mod.group(1).strip() if mod else None
    return out


BLOCK_END = re.compile(
    r"</(p|div|li|h[1-6]|tr|section|article|ul|ol|table|blockquote|pre)>|<br\s*/?>",
    re.I,
)


def extract_text(page_html, content_tag):
    """Pull the main content out of a page as clean, line-based text."""
    m = re.search(rf"<{content_tag}[ >].*?</{content_tag}>", page_html, re.S | re.I)
    chunk = m.group(0) if m else page_html
    # Intercom injects a rotating "Related Articles" widget at the end of the
    # article. Its links change between requests and are not page edits.
    chunk = re.split(r"<section[^>]*related_articles[^>]*>", chunk, maxsplit=1, flags=re.I)[0]
    chunk = re.sub(r"<(script|style|nav|header|footer|svg)[ >].*?</\1>", " ", chunk, flags=re.S | re.I)
    chunk = re.sub(r"</td>|</th>", " | ", chunk, flags=re.I)
    chunk = BLOCK_END.sub("\n", chunk)
    chunk = re.sub(r"<[^>]+>", " ", chunk)
    chunk = htmlmod.unescape(chunk)
    lines = []
    for line in chunk.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line and line not in {"Copy", "|"}:
            lines.append(line)
    return "\n".join(lines)


ALLOWED_ATTRS = {"href", "src", "alt", "colspan", "rowspan"}


def extract_html(page_html, content_tag, base_url):
    """Cleaned content HTML for rendering like the source page (no scripts/styles/attrs)."""
    m = re.search(rf"<{content_tag}[ >].*?</{content_tag}>", page_html, re.S | re.I)
    if not m:
        return ""
    chunk = m.group(0)
    chunk = re.split(r"<section[^>]*related_articles[^>]*>", chunk, maxsplit=1, flags=re.I)[0]
    chunk = re.sub(r"<!--.*?-->", "", chunk, flags=re.S)
    chunk = re.sub(
        r"<(script|style|nav|header|footer|svg|button|form|noscript|iframe)[ >].*?</\1>",
        " ", chunk, flags=re.S | re.I,
    )

    def clean_tag(m):
        tag, attrs = m.group(1).lower(), m.group(2) or ""
        if tag in {"input", "iframe", "source", "object", "embed"}:
            return ""
        keep = []
        for a in re.finditer(r'([a-zA-Z-]+)\s*=\s*"([^"]*)"', attrs):
            name, val = a.group(1).lower(), a.group(2)
            if name not in ALLOWED_ATTRS:
                continue
            if name in ("href", "src"):
                if val.lower().startswith("javascript:"):
                    continue
                if val and not val.startswith(("http", "#", "mailto:", "data:")):
                    val = urljoin(base_url, val)
            keep.append(f'{name}="{val}"')
        return f"<{tag}{' ' + ' '.join(keep) if keep else ''}>"

    chunk = re.sub(r"<([a-zA-Z][a-zA-Z0-9]*)([^>]*)>", clean_tag, chunk)
    return chunk.strip()


def extract_title(page_html, content_tag="article"):
    # Intercom: <title> is reliable. GitBook: <title> is generic, use content <h1>.
    m = re.search(r"<title[^>]*>(.*?)</title>", page_html, re.S | re.I)
    title = htmlmod.unescape(m.group(1)).strip() if m else ""
    title = re.sub(r"\s*\|\s*(Topstep Help Center|TopstepX Platform Help Center)\s*$", "", title)
    if content_tag == "article" and title:
        return title
    m = re.search(rf"<{content_tag}[ >].*?</{content_tag}>", page_html, re.S | re.I)
    chunk = m.group(0) if m else page_html
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", chunk, re.S | re.I)
    if h1:
        t = htmlmod.unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip()
        t = re.sub(r"\s+", " ", t)
        if t:
            return t
    return title


def content_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def latest_snapshot(db, url):
    row = db.execute(
        "SELECT id, fetched_at, lastmod, content FROM snapshots WHERE url=? ORDER BY id DESC LIMIT 1",
        (url,),
    ).fetchone()
    return row


def make_diff(old_text, new_text, old_label, new_label):
    return "\n".join(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=f"before ({old_label})",
            tofile=f"after ({new_label})",
            lineterm="",
            n=2,
        )
    )


def append_changelog(entry):
    new_file = not CHANGELOG.exists()
    with CHANGELOG.open("a") as f:
        if new_file:
            f.write("# Topstep / TopstepX help-center changelog\n\n")
            f.write("Auto-generated by tracker.py. Newest entries at the bottom.\n\n")
        f.write(entry)


def record_event(db, url, site, kind, old_lastmod, new_lastmod, diff, title):
    ts = now()
    db.execute(
        "INSERT INTO events(url, site, kind, detected_at, old_lastmod, new_lastmod, diff) VALUES(?,?,?,?,?,?,?)",
        (url, site, kind, ts, old_lastmod, new_lastmod, diff),
    )
    if kind in ("changed", "added", "removed"):
        entry = f"## {ts} — {kind.upper()}: {title or url}\n\n- Site: `{site}`\n- URL: {url}\n"
        if kind == "changed":
            entry += f"- Page updated: `{old_lastmod}` → `{new_lastmod}`\n\n```diff\n{diff}\n```\n\n"
        else:
            entry += "\n"
        append_changelog(entry)
    db.commit()


def check_site(db, site, cfg, full=False):
    print(f"[{site}] fetching sitemap {cfg['sitemap']}")
    entries = parse_sitemap(cfg["sitemap"])
    if not entries:
        print(f"[{site}] WARNING: sitemap empty, skipping (no removal detection)")
        return
    baseline_mode = db.execute(
        "SELECT COUNT(*) FROM pages WHERE site=?", (site,)
    ).fetchone()[0] == 0

    stats = {"new": 0, "changed": 0, "ts_only": 0, "unchanged": 0, "removed": 0, "errors": 0}
    known = {
        r[0] for r in db.execute("SELECT url FROM pages WHERE site=? AND status='active'", (site,))
    }

    for i, (url, lastmod) in enumerate(sorted(entries.items())):
        row = db.execute("SELECT lastmod, content_hash, title FROM pages WHERE url=?", (url,)).fetchone()
        # Always re-fetch. Intercom/GitBook do not reliably bump sitemap lastmod
        # when article text changes (e.g. Topstep Labs edited 24 Nov but its
        # lastmod stayed 19 Nov), so timestamps cannot be used to skip pages.
        # Full scan is ~145 requests with crawl-delay ≈ 2 min per check.

        time.sleep(cfg["delay"])
        try:
            page_html = fetch(url)
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {url}: {e}")
            stats["errors"] += 1
            continue

        text = extract_text(page_html, cfg["content_tag"])
        html_content = extract_html(page_html, cfg["content_tag"], url)
        title = extract_title(page_html, cfg["content_tag"])
        h = content_hash(text)
        ts = now()

        if row is None:
            kind = "baseline" if baseline_mode else "added"
            db.execute(
                "INSERT INTO pages(url, site, title, lastmod, content_hash, status, first_seen, last_checked, last_changed)"
                " VALUES(?,?,?,?,?,'active',?,?,?)",
                (url, site, title, lastmod, h, ts, ts, ts),
            )
            db.execute(
                "INSERT INTO snapshots(url, fetched_at, lastmod, content, content_html) VALUES(?,?,?,?,?)",
                (url, ts, lastmod, text, html_content),
            )
            record_event(db, url, site, kind, None, lastmod, None, title)
            stats["new"] += 1
            print(f"  + {kind}: {title or url}")
        elif h != row[1]:
            snap = latest_snapshot(db, url)
            diff = make_diff(snap[3], text, snap[2] or snap[1], lastmod or ts)
            db.execute(
                "INSERT INTO snapshots(url, fetched_at, lastmod, content, content_html) VALUES(?,?,?,?,?)",
                (url, ts, lastmod, text, html_content),
            )
            db.execute(
                "UPDATE pages SET title=?, lastmod=?, content_hash=?, status='active',"
                " last_checked=?, last_changed=? WHERE url=?",
                (title, lastmod, h, ts, ts, url),
            )
            record_event(db, url, site, "changed", row[0], lastmod, diff, title)
            stats["changed"] += 1
            print(f"  ~ CHANGED: {title or url}")
        else:
            # timestamp moved but content identical (e.g. GitBook site rebuild)
            db.execute(
                "UPDATE pages SET title=?, lastmod=?, status='active', last_checked=? WHERE url=?",
                (title, lastmod, ts, url),
            )
            stats["ts_only" if row[0] != lastmod else "unchanged"] += 1

        if (i + 1) % 20 == 0:
            print(f"  ... {i + 1}/{len(entries)}")

    for url in known - set(entries):
        row = db.execute("SELECT lastmod, title FROM pages WHERE url=?", (url,)).fetchone()
        db.execute("UPDATE pages SET status='removed', last_checked=? WHERE url=?", (now(), url))
        record_event(db, url, site, "removed", row[0], None, None, row[1])
        stats["removed"] += 1
        print(f"  - REMOVED: {row[1] or url}")

    db.commit()
    print(
        f"[{site}] done: {stats['new']} new, {stats['changed']} changed, "
        f"{stats['ts_only']} timestamp-only, {stats['unchanged']} unchanged, "
        f"{stats['removed']} removed, {stats['errors']} errors"
    )


def find_pages(db, keyword):
    return db.execute(
        "SELECT url, site, title FROM pages WHERE url LIKE ? OR title LIKE ? ORDER BY url",
        (f"%{keyword}%", f"%{keyword}%"),
    ).fetchall()


def cmd_run(args):
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    cols = [r[1] for r in db.execute("PRAGMA table_info(snapshots)")]
    if "content_html" not in cols:
        db.execute("ALTER TABLE snapshots ADD COLUMN content_html TEXT")
        db.commit()
    sites = {args.site: SITES[args.site]} if args.site else SITES
    for site, cfg in sites.items():
        check_site(db, site, cfg, full=args.full)
    db.close()


def cmd_log(args):
    db = sqlite3.connect(DB_PATH)
    rows = db.execute(
        "SELECT detected_at, site, kind, url, old_lastmod, new_lastmod FROM events"
        " WHERE kind != 'baseline' ORDER BY id DESC LIMIT ?",
        (args.n,),
    ).fetchall()
    if not rows:
        print("No change events yet (baseline only). Changes will appear here after future runs.")
        return
    for ts, site, kind, url, old, new in rows:
        print(f"{ts}  [{site}] {kind.upper():8s} {url}")
        if kind == "changed":
            print(f"    page updated: {old} -> {new}")


def cmd_diff(args):
    db = sqlite3.connect(DB_PATH)
    pages = find_pages(db, args.keyword)
    if not pages:
        print(f"No tracked page matches '{args.keyword}'")
        return
    for url, site, title in pages:
        ev = db.execute(
            "SELECT detected_at, old_lastmod, new_lastmod, diff FROM events"
            " WHERE url=? AND kind='changed' ORDER BY id DESC LIMIT 1",
            (url,),
        ).fetchone()
        print(f"\n=== {title} ({site})\n{url}")
        if ev:
            print(f"Change detected {ev[0]} | page updated {ev[1]} -> {ev[2]}\n")
            print(ev[3])
        else:
            print("No changes recorded yet for this page (baseline saved).")


def cmd_history(args):
    db = sqlite3.connect(DB_PATH)
    pages = find_pages(db, args.keyword)
    if not pages:
        print(f"No tracked page matches '{args.keyword}'")
        return
    for url, site, title in pages:
        print(f"\n=== {title} ({site})\n{url}")
        for ts, kind, old, new in db.execute(
            "SELECT detected_at, kind, old_lastmod, new_lastmod FROM events WHERE url=? ORDER BY id",
            (url,),
        ):
            extra = f"  ({old} -> {new})" if kind == "changed" else ""
            print(f"  {ts}  {kind}{extra}")


def cmd_pages(args):
    db = sqlite3.connect(DB_PATH)
    q = "SELECT site, title, lastmod, status, url FROM pages"
    params = ()
    if args.site:
        q += " WHERE site=?"
        params = (args.site,)
    q += " ORDER BY lastmod DESC"
    for site, title, lastmod, status, url in db.execute(q, params):
        flag = "" if status == "active" else f" [{status}]"
        print(f"{lastmod or '?':22s} [{site}]{flag} {title}\n    {url}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="check both sites for changes")
    r.add_argument("--full", action="store_true", help="re-fetch all pages (catch silent edits)")
    r.add_argument("--site", choices=list(SITES), help="only check one site")
    r.set_defaults(fn=cmd_run)

    lg = sub.add_parser("log", help="recent change events")
    lg.add_argument("-n", type=int, default=20)
    lg.set_defaults(fn=cmd_log)

    d = sub.add_parser("diff", help="latest before/after diff for a page (keyword match)")
    d.add_argument("keyword")
    d.set_defaults(fn=cmd_diff)

    h = sub.add_parser("history", help="all events for a page (keyword match)")
    h.add_argument("keyword")
    h.set_defaults(fn=cmd_history)

    pg = sub.add_parser("pages", help="list tracked pages, newest first")
    pg.add_argument("--site", choices=list(SITES))
    pg.set_defaults(fn=cmd_pages)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
