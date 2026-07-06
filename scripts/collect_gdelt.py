#!/usr/bin/env python3
"""
Layer 1b — GDELT free news collector (no key, no signup, effectively unlimited).

GDELT monitors news worldwide in 100+ languages, updates every 15 minutes, and
exposes a free JSON endpoint. We use it to BROADEN coverage beyond NewsAPI's
daily cap. Articles found here are written to the same raw pool that collect_news.py's
filter+Gemini stage consumes — so GDELT items get the same Korean-summary and
relevance treatment.

This script only FETCHES and appends to data/gdelt_pool.json (title/url/domain/
date). The existing collect_news.py owns keyword-filtering and Gemini judging; to keep
things simple and free, we let collect_news.py read this raw pool too.

Endpoint: https://api.gdeltproject.org/api/v2/doc/doc
Docs: scattered, but the query form is simple. We request ArtList JSON.
"""
import os, json, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
RAW = os.path.join(HERE, "..", "data", "gdelt_pool.json")

# Queries: shared with NewsAPI via queries.txt (edit one file, both update)
def load_queries():
    path = os.path.join(HERE, "..", "queries.txt")
    out = []
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    except Exception:
        pass
    return out or ["samsung", "samsung galaxy", "smartphone market", "ecommerce"]

QUERIES = load_queries()
MAX_PER_QUERY = 10   # 10 articles per query, same as NewsAPI

def fetch_one(q, retries=2):
    params = {
        "query": q + " sourcelang:english",
        "mode": "ArtList",
        "maxrecords": str(MAX_PER_QUERY),
        "timespan": "1d",            # last 1 day
        "format": "json",
        "sort": "DateDesc",
    }
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "scom-tracker/1.0"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8", "replace")
            # GDELT sometimes returns empty/HTML responses; parse defensively
            if not raw.strip().startswith("{"):
                print("  GDELT non-JSON response for:", q)
                return []
            data = json.loads(raw)
            arts = data.get("articles", []) or []
            out = []
            for a in arts:
                out.append({
                    "title": a.get("title", "") or "",
                    "url": a.get("url", "") or "",
                    "domain": a.get("domain", "") or "",
                    "date": (a.get("seendate", "") or "")[:8],  # YYYYMMDD
                    "source": a.get("domain", "") or "gdelt",
                    "query": q,
                })
            return out
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                wait = 20 * (attempt + 1)  # 20s, then 40s
                print(f"  GDELT 429 for '{q}' — backing off {wait}s "
                      f"(retry {attempt+1}/{retries})")
                time.sleep(wait)
                continue
            print("  GDELT HTTP error", e.code, "for", q,
                  "(gave up)" if e.code == 429 else "")
            return []
        except Exception as e:
            # Generic network faults (SSL handshake timeout, connection reset, DNS
            # blip) are usually transient too — retry them the same as 429 instead
            # of giving up on the first hit, which was silently dropping queries.
            if attempt < retries:
                wait = 20 * (attempt + 1)
                print(f"  GDELT network error for '{q}': {e} — retrying in {wait}s "
                      f"({attempt+1}/{retries})")
                time.sleep(wait)
                continue
            print("  GDELT error for", q, ":", e, "(gave up)")
            return []
    return []

def main():
    print("GDELT collect start")
    all_items = []
    seen = set()
    failed_queries = []
    for q in QUERIES:
        items = fetch_one(q)
        if not items:
            failed_queries.append(q)
        for it in items:
            key = it["url"]
            if key and key not in seen:
                seen.add(key)
                all_items.append(it)
        time.sleep(8)  # courtesy gap — widened after repeated 429s persisted at 5s,
                       # likely due to GitHub Actions' shared runner IP pool
    # Normalize dates to YYYY-MM-DD
    for it in all_items:
        d = it.get("date", "")
        if len(d) == 8 and d.isdigit():
            it["date"] = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        else:
            it["date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    json.dump(all_items, open(RAW, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"GDELT done. {len(all_items)} unique articles -> data/gdelt_pool.json")
    if failed_queries:
        print(f"[diag] {len(failed_queries)}/{len(QUERIES)} queries returned nothing "
              f"(rate-limited or errored): {failed_queries}")

if __name__ == "__main__":
    main()
