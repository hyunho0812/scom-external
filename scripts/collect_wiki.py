#!/usr/bin/env python3
"""
Company traffic proxy — Wikipedia daily pageviews (FREE, no key).

Draws the trend graph lines. For each tracked brand we pull daily pageviews of
its Wikipedia article and store a compact time series in data/wiki_series.json.
Samsung is always included (baseline); Apple/LG/Whirlpool map to divisions
MX/VD/DA. These are interest/attention proxies, NOT real company web traffic.

Official Wikimedia REST API — no token, no rate-limit worries at this volume.
"""
import os, json, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(__file__)
OUT  = os.path.join(HERE, "..", "data", "wiki_series.json")

# brand -> (Wikipedia article, division). Samsung division "ALL" = always shown.
BRANDS = {
    "Samsung":   ("Samsung_Electronics", "ALL"),
    "Apple":     ("Apple_Inc.",          "MX"),
    "LG":        ("LG_Electronics",       "VD"),
    "Whirlpool": ("Whirlpool_Corporation","DA"),
}
DAYS_BACK = 730  # last 2 years

def fetch(article, start, end):
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
           f"en.wikipedia/all-access/user/{article}/daily/{start}/{end}")
    req = urllib.request.Request(url, headers={"User-Agent":"scom-external-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.loads(r.read().decode())
    out = []
    for it in data.get("items", []):
        ts = it["timestamp"][:8]  # YYYYMMDD
        out.append({"date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", "views": it["views"]})
    return out

def main():
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=DAYS_BACK)
    s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    result = {"updated": end.strftime("%Y-%m-%d %H:%M UTC"),
              "divisions": {b: BRANDS[b][1] for b in BRANDS}, "series": {}}
    for brand, (article, _div) in BRANDS.items():
        try:
            result["series"][brand] = fetch(article, s, e)
            print(f"  {brand}: {len(result['series'][brand])} days")
        except urllib.error.HTTPError as ex:
            print(f"  {brand}: HTTP {ex.code} — skipped")
            result["series"][brand] = []
        except Exception as ex:
            print(f"  {brand}: error {ex} — skipped")
            result["series"][brand] = []
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("wiki views saved:", OUT)

if __name__ == "__main__":
    main()
