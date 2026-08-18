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
import os, json, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta

import sys
HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
from llm_common import WIKI_FILE, read_json, write_json   # shared paths + JSON I/O
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

# Wikimedia's API etiquette REQUIRES a User-Agent that identifies the tool AND
# carries contact info; requests without one are throttled harder or blocked.
# This used to send a bare "scom-external-tracker/1.0" (no contact URL) — the
# only script in the project that didn't use the standard UA below.
UA = "scom-external/1.0 (+https://github.com/hyunho0812/scom-external)"
RETRIES = 2            # transient failures get 2 retries...
RETRY_WAIT = 3         # ...at 3s, then 6s (short: 10 brands x long waits adds up)
BRAND_GAP = 1.0        # polite pause between brands, per Wikimedia's etiquette guidance
LAG_DAYS = 2           # Wikimedia publishes pageviews ~1-2 days behind, so the
                       # newest days aren't "gaps" — don't chase them
MAX_GAP_RANGES = 2     # gap-fill requests per brand per run (bounds extra load:
                       # worst case 10 brands x 2 = 20 extra requests)

def fetch(article, start, end):
    # quote() handles non-ASCII article titles too (e.g. BSH Hausgeräte's "ä")
    safe_article = urllib.parse.quote(article, safe="")
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
           f"en.wikipedia/all-access/user/{safe_article}/daily/{start}/{end}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    # Wikimedia intermittently rejects individual requests in a rapid burst
    # (observed: a random 1-3 of the 10 brands failing per run, rotating daily
    # — never the same brand consistently, so it's throttling, not a bad
    # article title). Retrying briefly clears it in most cases.
    last = None
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.loads(r.read().decode())
            break
        except (urllib.error.HTTPError, urllib.error.URLError) as ex:
            last = ex
            if attempt < RETRIES:
                wait = RETRY_WAIT * (attempt + 1)
                code = getattr(ex, "code", "?")
                print(f"    retry {attempt+1}/{RETRIES} after HTTP {code} — waiting {wait}s")
                time.sleep(wait)
    else:
        raise last
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


def find_gaps(series, cutoff, newest_wanted):
    """Missing dates within the retained window, grouped into contiguous
    (start, end) ranges, NEWEST FIRST.

    Why this exists: the daily INCREMENTAL_DAYS window only heals holes in the
    last 10 days. A longer outage (or a brand that 404'd for a stretch) leaves
    a permanent hole further back that nothing would ever revisit — the
    len(existing) < BACKFILL_MIN_DAYS check doesn't catch it either, since a
    series can be well over that count and still be full of holes.

    The scan deliberately starts at the series' OWN earliest date (not the
    hard retention cutoff): dates before a brand's first data point may simply
    predate the article, and chasing those would burn requests every single
    run forever. Ends at newest_wanted (today minus Wikimedia's publish lag)
    so the not-yet-published newest days aren't mistaken for gaps.
    """
    have = {p["date"] for p in series}
    if not have:
        return []
    start = max(cutoff, min(have))
    d = datetime.strptime(start, "%Y-%m-%d").date()
    last = datetime.strptime(newest_wanted, "%Y-%m-%d").date()
    gaps, cur = [], None
    while d <= last:
        ds = d.isoformat()
        if ds in have:
            if cur:
                gaps.append(tuple(cur)); cur = None
        else:
            if cur is None: cur = [ds, ds]
            else: cur[1] = ds
        d += timedelta(days=1)
    if cur:
        gaps.append(tuple(cur))
    gaps.sort(reverse=True)  # newest gaps first — most relevant to the dashboard
    return gaps

def main():
    prev = read_json(WIKI_FILE, {"series": {}})
    prev_series = prev.get("series", {})

    end = datetime.now(timezone.utc)
    cutoff = (end - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
    newest_wanted = (end - timedelta(days=LAG_DAYS)).strftime("%Y-%m-%d")
    result = {"updated": end.strftime("%Y-%m-%d %H:%M UTC"),
              "divisions": {b: BRANDS[b][1] for b in BRANDS}, "series": {}}

    for brand, (article, _divs) in BRANDS.items():
        existing = prev_series.get(brand, [])
        backfilling = len(existing) < BACKFILL_MIN_DAYS
        days_to_fetch = RETENTION_DAYS if backfilling else INCREMENTAL_DAYS
        start = end - timedelta(days=days_to_fetch)
        s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        mode = "backfill (full 2y)" if backfilling else f"incremental ({INCREMENTAL_DAYS}d)"
        ok = False
        try:
            fresh = fetch(article, s, e)
            merged = fresh if backfilling else merge_and_trim(existing, fresh, RETENTION_DAYS, end)
            ok = True
            print(f"  {brand}: {mode} — fetched {len(fresh)}, total {len(merged)} days")
        except urllib.error.HTTPError as ex:
            print(f"  {brand}: HTTP {ex.code} — keeping previous {len(existing)} days")
            merged = existing
        except Exception as ex:
            print(f"  {brand}: error {ex} — keeping previous {len(existing)} days")
            merged = existing

        # Backfill any older holes the 10-day window can't reach. Skipped when
        # backfilling (the full 2y fetch already covers everything) and when
        # this brand's fetch just failed (firing more requests at a source
        # that's currently rejecting us would only make throttling worse).
        if ok and not backfilling:
            for gs, ge in find_gaps(merged, cutoff, newest_wanted)[:MAX_GAP_RANGES]:
                try:
                    time.sleep(BRAND_GAP)
                    extra = fetch(article, gs.replace("-", ""), ge.replace("-", ""))
                    if extra:
                        merged = merge_and_trim(merged, extra, RETENTION_DAYS, end)
                        print(f"    gap-filled {gs}~{ge}: +{len(extra)} days (total {len(merged)})")
                    else:
                        # Wikimedia genuinely has no data for that stretch;
                        # capped retries mean this costs at most a request/run.
                        print(f"    gap {gs}~{ge}: no data available")
                except Exception as ex:
                    print(f"    gap {gs}~{ge} fetch failed ({ex}) — will retry next run")

        result["series"][brand] = merged
        time.sleep(BRAND_GAP)  # don't fire all 10 brands back-to-back

    write_json(WIKI_FILE, result, indent=None)   # ~30k daily points
    print("wiki views saved:", WIKI_FILE)

if __name__ == "__main__":
    main()
