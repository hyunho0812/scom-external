#!/usr/bin/env python3
"""
Feed health check — verifies every source in feeds.txt actually parses AND
returns items, not just that the HTTP request succeeds.

Why this exists: a feed can return HTTP 200 while being unparsable (e.g. a
plain HTML page instead of RSS/XML) or genuinely empty. collect_feeds.py's
parse_feed() silently swallows XML parse errors and returns an empty list —
by design, so one bad feed doesn't crash the whole daily run — but that also
means a permanently-broken feed produces ZERO log output and can go unnoticed
indefinitely (this is exactly how the Anthropic entry was found broken:
pointed at a plain HTML page, parsed to 0 items, no error, every single day).

Runs daily alongside check_model.py and optimize.py (same reasoning: cheap to
run, and catches breakage as early as possible instead of letting it sit
unnoticed). Writes data/feed_health.json; does not touch data/events.json or
feed_state.json.
"""
import os, sys, json, urllib.request, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
from collect_feeds import http, parse_feed, load_feeds

OUT = os.path.join(HERE, "..", "data", "feed_health.json")


def check_one(label, url):
    try:
        raw = http(url)
    except urllib.error.HTTPError as e:
        return {"status": "error", "detail": f"HTTP {e.code}"}
    except Exception as e:
        return {"status": "error", "detail": f"{type(e).__name__}: {e}"}
    items = parse_feed(raw)
    if not items:
        # Could be a genuinely empty (but valid) feed, or unparsable content —
        # parse_feed() doesn't distinguish, so flag both as worth a human look.
        looks_like_xml = raw.strip()[:1] in (b"<",)
        detail = ("fetched OK but 0 items — parses as XML-ish but empty, or "
                   "not RSS/Atom at all" if looks_like_xml else
                   "fetched OK but 0 items — response doesn't look like XML "
                   "(likely a plain HTML page, not a feed)")
        return {"status": "empty", "detail": detail}
    return {"status": "ok", "detail": f"{len(items)} items"}


def main():
    feeds = load_feeds()
    results = {}
    for label, url in feeds.items():
        results[label] = check_one(label, url)
        icon = {"ok": "✓", "empty": "⚠", "error": "✗"}[results[label]["status"]]
        print(f"  {icon} {label}: {results[label]['detail']}")

    problems = {k: v for k, v in results.items() if v["status"] != "ok"}
    out = {"checked": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "feeds": results}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\nfeed health: {len(results)-len(problems)}/{len(results)} OK")
    if problems:
        print(f"[diag] {len(problems)} feed(s) need attention: {list(problems.keys())}")


if __name__ == "__main__":
    main()
