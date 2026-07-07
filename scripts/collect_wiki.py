#!/usr/bin/env python3
"""
Company traffic proxy — Wikipedia daily pageviews (FREE, no key).

Draws the trend graph lines. For each tracked brand we pull daily pageviews of
its Wikipedia article and store a compact time series in data/wiki_series.json.
Samsung is always included (baseline). Competitors map to divisions:
MX (mobile) = Apple, Xiaomi, vivo, OPPO; VD (TV/display) = LG, TCL, Hisense;
DA (home appliances) = LG, Whirlpool, Bosch (LG appears in both VD and DA).
These are interest/attention proxies, NOT real company web traffic.

Official Wikimedia REST API — no token required. Wikimedia rolled out new API
rate limits through 2026 specifically to curb automated bulk-access patterns
(their own stats show ~40% of pageviews are now automated traffic), and their
API etiquette guidance is explicit: incremental collection is preferred over
re-fetching the same bulk historical range repeatedly. So this script:
  - BACKFILLS the full 2-year window only ONCE per brand (when its series is
    empty or clearly incomplete).
  - After that, fetches only a small recent window each day (RETENTION_BUFFER
    days, covering Wikimedia's ~1-2 day pageview-finalization lag) and MERGES
    it into the existing accumulated series, trimming anything older than the
    2-year retention window. This is both far lighter on Wikimedia's API and
    more aligned with their stated etiquette than a full daily re-fetch.
"""
import os, json, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(__file__)
OUT  = os.path.join(HERE, "..", "data", "wiki_series.json")

# brand -> (Wikipedia article, [divisions]). Samsung division "ALL" = always
# shown. A brand can belong to more than one division (e.g. LG makes both
# TVs/displays and home appliances, so it counts toward both VD and DA).
# Article titles verified against en.wikipedia.org directly (not guessed) —
# note vivo/Oppo/Bosch have disambiguated or subsidiary-specific titles:
#   - Oppo's main article is simply "Oppo" (not "Oppo (company)").
#   - vivo's is "Vivo (technology company)" (avoids the "Vivo" telecom brand).
#   - Bosch's HOME-APPLIANCE business is run by its subsidiary BSH Hausgeräte
#     (wholly Bosch-owned since 2015); the general "Robert Bosch GmbH" article
#     covers Bosch's much larger automotive/industrial business instead, so
#     BSH Hausgeräte is the accurate pick for a home-appliance competitor.
BRANDS = {
    "Samsung":   ("Samsung_Electronics", ["ALL"]),
    "Apple":     ("Apple_Inc.",          ["MX"]),
    "Xiaomi":    ("Xiaomi",              ["MX"]),
    "vivo":      ("Vivo_(technology_company)", ["MX"]),
    "OPPO":      ("Oppo",                ["MX"]),
    "LG":        ("LG_Electronics",      ["VD", "DA"]),
    "TCL":       ("TCL_Technology",      ["VD"]),
    "Hisense":   ("Hisense",             ["VD"]),
    "Whirlpool": ("Whirlpool_Corporation",["DA"]),
    "Bosch":     ("BSH_Hausger\u00e4te", ["DA"]),
}
RETENTION_DAYS = 730     # how much history to keep in the final series (2 years)
BACKFILL_MIN_DAYS = 700  # if a brand has fewer days than this, treat as "not yet backfilled"
INCREMENTAL_DAYS = 10    # daily fetch window once backfilled (buffer for publish lag)

def fetch(article, start, end):
    # quote() handles non-ASCII article titles too (e.g. BSH Hausgeräte's "ä")
    safe_article = urllib.parse.quote(article, safe="")
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
           f"en.wikipedia/all-access/user/{safe_article}/daily/{start}/{end}")
    req = urllib.request.Request(url, headers={"User-Agent":"scom-external-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.loads(r.read().decode())
    out = []
    for it in data.get("items", []):
        ts = it["timestamp"][:8]  # YYYYMMDD
        out.append({"date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", "views": it["views"]})
    return out

def merge_and_trim(existing, fresh, retention_days, today):
    """Merge fresh points into existing (by date, fresh wins on conflict —
    Wikimedia sometimes revises recent counts), then drop anything older
    than the retention window."""
    by_date = {p["date"]: p["views"] for p in existing}
    for p in fresh:
        by_date[p["date"]] = p["views"]
    cutoff = (today - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    merged = sorted(({"date": d, "views": v} for d, v in by_date.items() if d >= cutoff),
                     key=lambda p: p["date"])
    return merged

def main():
    try:
        prev = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        prev = {"series": {}}
    prev_series = prev.get("series", {})

    end = datetime.now(timezone.utc)
    result = {"updated": end.strftime("%Y-%m-%d %H:%M UTC"),
              "divisions": {b: BRANDS[b][1] for b in BRANDS}, "series": {}}

    for brand, (article, _divs) in BRANDS.items():
        existing = prev_series.get(brand, [])
        backfilling = len(existing) < BACKFILL_MIN_DAYS
        days_to_fetch = RETENTION_DAYS if backfilling else INCREMENTAL_DAYS
        start = end - timedelta(days=days_to_fetch)
        s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        mode = "backfill (full 2y)" if backfilling else f"incremental ({INCREMENTAL_DAYS}d)"
        try:
            fresh = fetch(article, s, e)
            merged = fresh if backfilling else merge_and_trim(existing, fresh, RETENTION_DAYS, end)
            result["series"][brand] = merged
            print(f"  {brand}: {mode} — fetched {len(fresh)}, total {len(merged)} days")
        except urllib.error.HTTPError as ex:
            print(f"  {brand}: HTTP {ex.code} — keeping previous {len(existing)} days")
            result["series"][brand] = existing
        except Exception as ex:
            print(f"  {brand}: error {ex} — keeping previous {len(existing)} days")
            result["series"][brand] = existing

    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("wiki views saved:", OUT)

if __name__ == "__main__":
    main()
