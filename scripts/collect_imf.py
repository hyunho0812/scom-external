#!/usr/bin/env python3
"""
Layer 3 — IMF monthly macro indicators (free, no key). World Bank fully removed;
IMF is now the sole macro-stats source for the country-statistics tab.

We request the CSV representation (Accept: text/csv) of IMF's SDMX 3.0 API, which
avoids the deeply-nested SDMX-JSON and keeps parsing simple/robust.

Indicators (monthly where available), chosen for relevance to samsung.com demand:
  - cpi_all      : overall CPI (purchasing power / general price level)
  - cpi_furn     : furnishings/appliances CPI (directly tied to DA products)
  - cpi_housing  : housing/energy CPI (cost-of-living pressure -> big-ticket affordability)
  - cpi_comm     : communications CPI (COICOP 08 - mobile / MX products)
  - cpi_recr     : recreation/electronics CPI (COICOP 09 - TV/AV / VD products)
  - retail       : retail sales index (how much people actually spend)
  - lfpr         : labor force participation (structural income/spending signal)

IMF SDMX gotcha: each dataflow has its OWN codelists, so exact keys vary and can
change. We try a small set of candidate (dataflow, key) combos per indicator and
keep whichever returns rows. If none work, that indicator is simply absent and the
dashboard shows a "no data" state until codes are updated.

Schedule: run on the LAST day of each month to collect the PREVIOUS month's data
(IMF has no single fixed release date; month-end is a safe, conservative window).

Output: data/imf_series.json
  data[country][indicator_code] = [["2024-01", value], ...]
"""
import os, json, csv, io, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "..", "data", "imf_series.json")

# Our market codes -> ISO3
ISO3 = {"US":"USA","GB":"GBR","DE":"DEU","FR":"FRA","ES":"ESP","PT":"PRT",
        "BR":"BRA","MX_C":"MEX","AU":"AUS","IN":"IND","TR":"TUR","KR":"KOR"}
MARKET_KO = {"US":"미국","GB":"영국","DE":"독일","FR":"프랑스","ES":"스페인","PT":"포르투갈",
           "BR":"브라질","MX_C":"멕시코","AU":"호주","IN":"인도","TR":"튀르키예","KR":"한국"}

BASE = "https://api.imf.org/external/sdmx/3.0/data/dataflow/"

# Each indicator: label/unit + candidate (agency, dataflow, key-template) combos.
# {iso} is replaced with ISO3. Candidates are tried in order; first success wins.
INDICATORS = {
    "cpi_all": {
        "label": "소비자물가지수 (전체)", "unit": "지수",
        "candidates": [("IMF.STA","CPI","{iso}.CPI._T.IX.M")],
    },
    "cpi_furn": {
        "label": "가구·가전 물가지수", "unit": "지수",
        "candidates": [
            ("IMF.STA","CPI","{iso}.CPI.CP05.IX.M"),   # COICOP 05: furnishings & household appliances
        ],
    },
    "cpi_housing": {
        "label": "주거·에너지 물가지수", "unit": "지수",
        "candidates": [
            ("IMF.STA","CPI","{iso}.CPI.CP04.IX.M"),   # COICOP 04: housing, water, electricity, gas
        ],
    },
    "cpi_comm": {
        "label": "통신 물가지수", "unit": "지수",
        "candidates": [
            ("IMF.STA","CPI","{iso}.CPI.CP08.IX.M"),   # COICOP 08: communications (mobile / MX)
        ],
    },
    "cpi_recr": {
        "label": "여가·문화·전자기기 물가지수", "unit": "지수",
        "candidates": [
            ("IMF.STA","CPI","{iso}.CPI.CP09.IX.M"),   # COICOP 09: recreation & culture (TV/AV / VD)
        ],
    },
    "retail": {
        "label": "소매판매지수", "unit": "지수",
        # UNVERIFIED: could not confirm IMF publishes a monthly per-country retail
        # sales index under api.imf.org/external/sdmx/3.0. IMF's strength is CPI/
        # GDP/trade/monetary stats; retail sales is more often an OECD/national-
        # statistics-office series. If this stays empty after a real run, it may
        # need to be dropped or sourced elsewhere (e.g. OECD MEI, also free).
        "candidates": [
            ("IMF.STA","IFS","{iso}.RETAIL_IX.M"),
            ("IMF.STA","IFS","M.{iso}.AIPMA_RT_IX"),
        ],
    },
    "lfpr": {
        "label": "경제활동참가율", "unit": "%",
        # UNVERIFIED: same caveat as retail — could not confirm this exact key
        # against IMF's SDMX 3.0 codelists. Keep an eye on whether this fills in.
        "candidates": [
            ("IMF.STA","LFS","{iso}.LFPR._T._T.M"),
            ("IMF.STA","LFS","{iso}.LFPR.M"),
        ],
    },
}

def fetch_csv(agency, flow, key, start, verbose=False):
    url = f"{BASE}{agency}/{flow}/~/{key}?c[TIME_PERIOD]=ge:{start}"
    req = urllib.request.Request(url, headers={"Accept":"text/csv",
                                               "User-Agent":"scom-tracker/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8","replace")
    except urllib.error.HTTPError as e:
        if verbose:
            body = ""
            try:
                body = e.read().decode("utf-8","replace")[:200]
            except Exception:
                pass
            print(f"    [diag] {key}: HTTP {e.code} — {body}")
        return ""   # wrong code usually 404/400 -> try next candidate
    except Exception as e:
        if verbose:
            print(f"    [diag] {key}: {type(e).__name__}: {str(e)[:150]}")
        return ""

def parse_rows(csv_text):
    out = []
    if not csv_text or "," not in csv_text:
        return out
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            t = row.get("TIME_PERIOD") or row.get("TIME") or row.get("time_period")
            v = row.get("OBS_VALUE") or row.get("value") or row.get("OBS")
            if t and v not in (None,"","NaN"):
                try:
                    out.append([t.replace("-M","-"), float(v)])
                except ValueError:
                    continue
    except Exception:
        return []
    out.sort()
    return out

def collect_indicator(iso, spec, start, verbose=False):
    """Try candidate keys in order; return the first non-empty series."""
    for agency, flow, keytmpl in spec["candidates"]:
        key = keytmpl.format(iso=iso)
        pts = parse_rows(fetch_csv(agency, flow, key, start, verbose=verbose))
        if pts:
            return pts
        time.sleep(0.5)
    return []

def main():
    print("IMF monthly collect start (sole macro source)")
    # ~2 years back, with margin
    start = (datetime.now(timezone.utc) - timedelta(days=365*2+40)).strftime("%Y-M%m")
    series = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
              "countries": MARKET_KO,
              "indicators": {c:{"label":v["label"],"unit":v["unit"]}
                             for c,v in INDICATORS.items()},
              "data": {}}
    first_country = next(iter(ISO3))
    for our, iso in ISO3.items():
        series["data"].setdefault(our, {})
        for code, spec in INDICATORS.items():
            pts = collect_indicator(iso, spec, start, verbose=(our == first_country))
            if pts:
                series["data"][our][code] = pts
                print(f"  + {our} {code}: {len(pts)} pts")
            elif our == first_country:
                print(f"  - {our} {code}: no data (see [diag] lines above)")
        time.sleep(1)
    json.dump(series, open(OUT,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    filled = sum(1 for c in series["data"].values() for _ in c)
    print(f"IMF monthly done. {filled} country-indicator series saved.")

if __name__ == "__main__":
    main()
