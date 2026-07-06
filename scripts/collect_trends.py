#!/usr/bin/env python3
"""
Layer 1c — Google Trends search-interest collector (free, no key).

Wikipedia pageviews measure "people who looked Samsung up in an encyclopedia".
Google Trends measures "people who searched Samsung on Google" — a different,
complementary attention signal closer to commercial intent. Neither is real
samsung.com traffic, but together they triangulate interest better than one alone.

We call Google Trends' public (unofficial) endpoints directly:
  1) /api/explore  -> get a token for the query
  2) /api/widgetdata/multiline -> get the time series with that token
Returns a 0-100 relative-interest index over time (Google's normalization).

Output: data/trends.json
  {"series": {"Samsung": [["2026-06-01", 78], ...], "Galaxy": [...]}, "updated": "..."}

NOTE: This endpoint is unofficial and rate-limited; if Google blocks or changes it,
the collector logs and skips — the dashboard simply omits the Trends line until it
recovers. Wikipedia remains the baseline traffic proxy.
"""
import os, json, time, http.cookiejar, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "..", "data", "trends.json")

TERMS = ["Samsung"]   # single term — matches the line drawn on the chart
GEO = ""              # worldwide (use 'US', 'KR', etc. for a country)
TIMEFRAME = "today 24-m"   # last 24 months (2y) — aligned with wiki collection window

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
EXPLORE = "https://trends.google.com/trends/api/explore"
MULTILINE = "https://trends.google.com/trends/api/widgetdata/multiline"

# Google's unofficial API rejects cookie-less requests (returns 400) — a browser
# would first pick up session cookies by visiting the site. We replicate that with
# a shared cookie jar: one warm-up GET, then reuse the same opener for both calls.
_cookiejar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookiejar))

def _warm_up():
    """Visit the Trends homepage once to collect session cookies (incl. any EU
    consent cookie) before calling the private API — matches real browser flow."""
    try:
        req = urllib.request.Request("https://trends.google.com/", headers=HEADERS)
        _opener.open(req, timeout=20).read()
        return True
    except Exception as e:
        print("  trends warm-up failed:", e)
        return False

def _strip(s):
    # Google Trends responses are prefixed with ")]}'," — strip before parsing JSON
    i = s.find("{")
    return s[i:] if i >= 0 else s

def get_token(term):
    req_payload = {
        "comparisonItem": [{"keyword": term, "geo": GEO, "time": TIMEFRAME}],
        "category": 0, "property": "",
    }
    params = {"hl": "en-US", "tz": "0", "req": json.dumps(req_payload)}
    url = EXPLORE + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with _opener.open(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
        data = json.loads(_strip(raw))
        for w in data.get("widgets", []):
            if w.get("id") == "TIMESERIES":
                return w.get("token"), w.get("request")
        print("  trends token: no TIMESERIES widget in response for", term)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:150]
        except Exception:
            pass
        print(f"  trends token error {term}: HTTP {e.code} — {body}")
    except Exception as e:
        print("  trends token error", term, ":", e)
    return None, None

def get_series(token, request_obj):
    params = {"hl": "en-US", "tz": "0",
              "req": json.dumps(request_obj), "token": token}
    url = MULTILINE + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with _opener.open(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
        data = json.loads(_strip(raw))
        out = []
        for pt in data.get("default", {}).get("timelineData", []):
            t = pt.get("formattedAxisTime") or pt.get("time")
            vals = pt.get("value") or []
            v = vals[0] if vals else None
            # Convert epoch time to a date if present
            ds = None
            try:
                ds = datetime.utcfromtimestamp(int(pt.get("time"))).strftime("%Y-%m-%d")
            except Exception:
                ds = str(t)
            if v is not None:
                out.append([ds, v])
        return out
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:150]
        except Exception:
            pass
        print(f"  trends series error: HTTP {e.code} — {body}")
        return []
    except Exception as e:
        print("  trends series error:", e)
        return []

def main():
    print("Google Trends collect start")
    series = {}
    if not _warm_up():
        print("  could not establish a session — Google Trends likely unreachable "
              "or blocking this network; skipping this run.")
    for term in TERMS:
        token, reqobj = get_token(term)
        if not token:
            print("  no token for", term, "— skipping")
            continue
        time.sleep(1)
        pts = get_series(token, reqobj)
        if pts:
            series[term] = pts
            print(f"  + {term}: {len(pts)} points")
        time.sleep(2)
    payload = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
               "series": series}
    # If we got nothing but a file exists, keep it (protect against transient blocks)
    if not series and os.path.exists(OUT):
        print("Google Trends returned nothing — keeping previous trends.json")
        return
    json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"trends done. {len(series)} terms saved.")

if __name__ == "__main__":
    main()
