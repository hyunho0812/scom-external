#!/usr/bin/env python3
"""
Merge past-event JSON arrays collected from multiple AI accounts into a single
events.json seed. Validates/cleans each record against the dashboard schema.

Usage:
  1) Save each AI's JSON-array output as a file, e.g. ai1.json, ai2.json, ...
     (put them in a folder, default: ./past_events/)
  2) Run:  python merge_past_events.py ./past_events  data/events.json
     - arg1: folder containing the AI JSON files (default ./past_events)
     - arg2: output path (default data/events.json)

It re-numbers event_id (E101, E102, ...), sorts by date, fixes category/scope
values to the allowed sets, and drops malformed records.
"""
import os, sys, json, glob, re

sys.path.insert(0, os.path.dirname(__file__))
from llm_common import MARKETS  # single source of truth for the 12 tracked countries

ALLOWED_CAT = {"culture","marketing","platform","holiday","economy",
               "social_issue","geopolitics","AI","company","regulation"}
ALLOWED_SCOPE = set(MARKETS)
ALLOWED_DIV = {"MX","VD","DA"}
ALLOWED_KPI = {"Impression","Click","Traffic","Order","CVR","Revenue","AOV"}
ALLOWED_DIR = {"+","-","neutral","unknown"}
ALLOWED_HOR = {"immediate","weeks","months"}
ALLOWED_CONF = {"high","med","low"}
ALLOWED_METRIC = {"traffic","revenue","both"}
# common fixes for category values AIs might emit
CAT_FIX = {"competitor":"company","ai":"AI","ecommerce":"economy",
           "tech":"company","environment":"geopolitics","politics":"geopolitics"}
SCOPE_FIX = {"UK":"GB","MX":"MX_C","USA":"US","KOR":"KR","GBR":"GB"}

def clean_list(val, allowed, fixes=None):
    if isinstance(val, list):
        items = val
    else:
        items = re.split(r"[;,]", str(val or ""))
    out = []
    for it in items:
        it = it.strip()
        if fixes and it.upper() in fixes: it = fixes[it.upper()]
        if it in allowed and it not in out:
            out.append(it)
    return out

def clean_record(r):
    try:
        date = str(r.get("date","")).strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            return None
        cat = str(r.get("category","economy")).strip()
        cat = CAT_FIX.get(cat, cat)
        if cat not in ALLOWED_CAT: cat = "economy"
        scope = clean_list(r.get("scope"), ALLOWED_SCOPE, SCOPE_FIX) or list(ALLOWED_SCOPE)
        divs = clean_list(r.get("divisions"), ALLOWED_DIV)
        kpi = clean_list(r.get("kpi"), ALLOWED_KPI) or ["Traffic"]
        d = str(r.get("impact_direction","unknown")).strip()
        if d not in ALLOWED_DIR: d = "unknown"
        hor = str(r.get("impact_horizon","weeks")).strip()
        if hor not in ALLOWED_HOR: hor = "weeks"
        conf = str(r.get("confidence","low")).strip()
        if conf not in ALLOWED_CONF: conf = "low"
        metric = str(r.get("metric","traffic")).strip()
        if metric not in ALLOWED_METRIC: metric = "traffic"
        try: strength = int(r.get("impact_strength",2))
        except (ValueError, TypeError): strength = 2
        strength = max(1, min(5, strength))
        title = str(r.get("title","")).strip()
        if not title: return None
        return {
            "event_id": "TMP",
            "date": date,
            "captured_date": str(r.get("captured_date", date)).strip() or date,
            "scope": ";".join(scope),
            "divisions": ";".join(divs),
            "kpi": ";".join(kpi),
            "category": cat,
            "title": title,
            "description": str(r.get("description","")).strip(),
            "impact_direction": d,
            "impact_horizon": hor,
            "confidence": conf,
            "metric": metric,
            "source": str(r.get("source","")).strip(),
            "impact": str(r.get("impact","")).strip(),
            "impact_strength": strength,
        }
    except Exception:
        return None

def load_array(path):
    txt = open(path, encoding="utf-8").read().strip()
    # tolerate code fences or leading prose
    txt = txt.replace("```json","").replace("```","").strip()
    i = txt.find("["); j = txt.rfind("]")
    if i>=0 and j>i: txt = txt[i:j+1]
    return json.loads(txt)

def main():
    folder = sys.argv[1] if len(sys.argv)>1 else "past_events"
    out = sys.argv[2] if len(sys.argv)>2 else "data/events.json"
    files = sorted(glob.glob(os.path.join(folder,"*.json")))
    if not files:
        print(f"No JSON files in {folder}/ — save each AI output as a .json file there.")
        return
    records = []
    for f in files:
        try:
            arr = load_array(f)
        except Exception as e:
            print(f"  skip {f}: parse error {e}"); continue
        kept = 0
        for r in (arr or []):
            c = clean_record(r)
            if c: records.append(c); kept += 1
        print(f"  {os.path.basename(f)}: {kept} valid records")
    # dedup by (date,title), sort by date, renumber
    seen=set(); uniq=[]
    for r in sorted(records, key=lambda x:(x["date"], x["title"])):
        key=(r["date"], r["title"][:40])
        if key in seen: continue
        seen.add(key); uniq.append(r)
    for i,r in enumerate(uniq, start=101):
        r["event_id"] = f"E{i}"
    json.dump(uniq, open(out,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nMerged {len(uniq)} events -> {out}")
    print(f"Date range: {uniq[0]['date'] if uniq else '-'} ~ {uniq[-1]['date'] if uniq else '-'}")

if __name__ == "__main__":
    main()
