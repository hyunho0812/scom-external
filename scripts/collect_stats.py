#!/usr/bin/env python3
"""
Layer 2 — slow-trend collector.

News misses gradual shifts (aging, middle-class growth, smartphone penetration)
because they are STATES, not EVENTS. This pulls structured indicators from the
World Bank API (free, no key) on a slow cadence, compares the latest value to a
few years back, and emits an event ONLY when the change crosses a threshold.

Run this monthly (the workflow calls it but it self-throttles: it won't add a
duplicate trend event within the same quarter).

World Bank indicator codes used (extend freely):
  SP.POP.65UP.TO.ZS  population ages 65+ (% of total)   — aging
  NY.GDP.PCAP.KD.ZG  GDP per capita growth (annual %)    — economy
  IT.NET.USER.ZS     individuals using the internet (%)  — digital reach
"""
import os, json, urllib.request, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data", "events.json")

# market -> World Bank ISO. GLOBAL handled as 'WLD'.
WB_ISO = {"US":"USA","GB":"GBR","DE":"DEU","FR":"FRA","ES":"ESP","PT":"PRT",
          "BR":"BRA","MX_C":"MEX","AU":"AUS","IN":"IND","TR":"TUR","KR":"KOR"}

INDICATORS = {
    "SP.POP.65UP.TO.ZS": ("aging",   "social_issue", "65세 이상 인구 비중",   0.4),
    "NY.GDP.PCAP.KD.ZG": ("economy", "economy",      "1인당 GDP 성장률",      1.5),
    "IT.NET.USER.ZS":    ("digital", "marketing",    "인터넷 보급률",         1.5),
}
# 국가 코드 → 한글명 (title 표기용)
KO_NAME = {"US":"미국","GB":"영국","DE":"독일","FR":"프랑스","ES":"스페인","PT":"포르투갈",
           "BR":"브라질","MX_C":"멕시코","AU":"호주","IN":"인도","TR":"튀르키예","KR":"한국"}

def wb(iso, code):
    url = f"https://api.worldbank.org/v2/country/{iso}/indicator/{code}?format=json&per_page=8&mrv=6"
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"tracker"})
        d = json.loads(urllib.request.urlopen(req, timeout=30).read())
        pts = [(r["date"], r["value"]) for r in (d[1] or []) if r["value"] is not None]
        pts.sort()  # oldest -> newest
        return pts
    except Exception as e:
        print("  wb error", iso, code, e); return []

def load():
    try: return json.load(open(DATA, encoding="utf-8"))
    except Exception: return []

def quarter(dt): return f"{dt.year}Q{(dt.month-1)//3+1}"

def main():
    events = load()
    today = datetime.now(timezone.utc)
    q = quarter(today)
    # dedup: one trend event per (market, indicator, quarter)
    seen = {(e.get("scope",""), e.get("_indicator",""), e.get("_quarter",""))
            for e in events if e.get("_indicator")}
    added = 0
    for market, iso in WB_ISO.items():
        for code,(slug,cat,label,thr) in INDICATORS.items():
            key = (market, code, q)
            if key in seen:
                continue
            pts = wb(iso, code)
            if len(pts) < 2:
                continue
            (oy, ov), (ny, nv) = pts[0], pts[-1]
            change = nv - ov
            if abs(change) < thr:
                continue  # too small to matter — skip
            direction = "+" if change > 0 else "-"
            mname = KO_NAME.get(market, market)
            events.append({
                "event_id": f"WB-{market}-{slug}-{q}",
                "date": today.strftime("%Y-%m-%d"),
                "captured_date": today.strftime("%Y-%m-%d"),
                "scope": market,
                "divisions": "",
                "kpi": "CVR;Order;AOV;Revenue",
                "impact": f"{mname} {label} 추세 변화 → 해당 시장 구매력·전환·매출에 점진적 영향",
                "category": cat,
                "title": f"{mname} {label} 변화: {ov:.1f}→{nv:.1f} ({oy}~{ny})",
                "description": (f"World Bank 통계 기반 장기 추세 신호: {mname}의 {label}이(가) "
                               f"{oy}~{ny}년 동안 {change:+.1f}p 변동했습니다. 뉴스에 잘 드러나지 않는 "
                               f"점진적 구조 변화로, samsung.com 수요 구성에 영향을 줄 수 있습니다."),
                "impact_direction": "neutral",
                "impact_horizon": "months",
                "confidence": "med",
                "metric": "both",
                "source": "data.worldbank.org",
                "_indicator": code, "_quarter": q,
            })
            seen.add(key); added += 1
            print(f"  + trend: {market} {label} {ov:.1f}->{nv:.1f}")
    json.dump(events, open(DATA,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"stats done. added {added}, total {len(events)}")

if __name__ == "__main__":
    main()
