#!/usr/bin/env python3
"""
Supply-axis signal — Chrome UX Report (CrUX) History API (FREE key, no card).

Feeds the "supply" card of the 3-axis diagnosis panel with a quantitative
series: real-user Core Web Vitals for the samsung.com origin, measured by
Chrome users worldwide. A performance regression that coincides with a
ranking/traffic drop points at a supply-side (site) cause; a flat CWV line
lets supply be ruled out so analysis can focus on demand/share.

API: https://developer.chrome.com/docs/crux/history-api
  POST https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord
  Returns ~40 weekly points per metric; each point is a 28-day rolling
  aggregate ending that week (so this is a SLOW signal — weekly regression
  detection, not day-of incident detection).

Env (set as GitHub Secrets):
  CRUX_API_KEY — Google Cloud API key with "Chrome UX Report API" enabled
                 (free tier, no billing account needed). If missing, this
                 script SKIPS quietly — same principle as the other
                 collectors: never write guessed/empty data.

Output schema (data/crux_series.json):
{
 "updated": "YYYY-MM-DD HH:MM UTC",
 "origin": "https://www.samsung.com",
 "form_factor": "PHONE",
 "metrics": {
   "lcp_ms":  [{"date": "YYYY-MM-DD", "p75": 2500}, ...],   # ms
   "inp_ms":  [{"date": "YYYY-MM-DD", "p75": 200}, ...],    # ms
   "cls":     [{"date": "YYYY-MM-DD", "p75": 0.1}, ...]     # unitless
 }
}
"date" is the collection period's END date. PHONE form factor is used since
the majority of samsung.com organic traffic is mobile; switch or add
DESKTOP later if needed.
"""
import os, json, time, urllib.request, urllib.error

HERE = os.path.dirname(__file__)
OUT  = os.path.join(HERE, "..", "data", "crux_series.json")

API_KEY = os.environ.get("CRUX_API_KEY", "")
ORIGIN = "https://www.samsung.com"
FORM_FACTOR = "PHONE"
API = "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord"
UA = "scom-external/1.0 (+https://github.com/hyunho0812/scom-external)"

# CrUX metric name -> (our key, value scale)
METRICS = {
    "largest_contentful_paint": ("lcp_ms", 1),
    "interaction_to_next_paint": ("inp_ms", 1),
    "cumulative_layout_shift":   ("cls",    1),
}


def fetch_history():
    body = json.dumps({
        "origin": ORIGIN,
        "formFactor": FORM_FACTOR,
        "metrics": list(METRICS.keys()),
    }).encode()
    req = urllib.request.Request(
        f"{API}?key={API_KEY}", data=body,
        headers={"Content-Type": "application/json", "User-Agent": UA},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def period_end_date(p):
    d = p.get("lastDate", {})
    return f"{d.get('year',0):04d}-{d.get('month',0):02d}-{d.get('day',0):02d}"


def main():
    if not API_KEY:
        print("CRUX_API_KEY not set — skipping CrUX collection (add the key "
              "to GitHub Secrets AND the workflow step's env: block).")
        return
    data = None
    for attempt in (1, 2):
        try:
            data = fetch_history()
            break
        except urllib.error.HTTPError as e:
            body = ""
            try: body = e.read().decode("utf-8", "replace")[:200]
            except Exception: pass
            print(f"CrUX API error {e.code} — {body}")
            if e.code == 429 and attempt == 1:
                time.sleep(10); continue
            return  # keep the previous snapshot; never write partial guesses
        except Exception as e:
            print("CrUX fetch failed:", e)
            return
    record = (data or {}).get("record", {})
    periods = record.get("collectionPeriods", [])
    dates = [period_end_date(p) for p in periods]
    out_metrics = {}
    for crux_name, (key, scale) in METRICS.items():
        ts = (record.get("metrics", {}).get(crux_name, {})
              .get("percentilesTimeseries", {}).get("p75s", []))
        series = []
        for i, v in enumerate(ts):
            if v is None or i >= len(dates):
                continue
            try:
                series.append({"date": dates[i], "p75": float(v) * scale})
            except (TypeError, ValueError):
                continue
        out_metrics[key] = series
    if not any(out_metrics.values()):
        print("CrUX returned no usable series — keeping previous snapshot.")
        return
    from datetime import datetime, timezone
    json.dump({
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "origin": ORIGIN,
        "form_factor": FORM_FACTOR,
        "metrics": out_metrics,
    }, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("CrUX series saved:",
          {k: len(v) for k, v in out_metrics.items()}, "weekly points")


if __name__ == "__main__":
    main()
