#!/usr/bin/env python3
"""
Layer 0 — daily search-query & keyword-filter optimizer (free, Gemini).

Runs BEFORE collection each day. It looks at how the current queries performed
(pass-rate and duplicate-rate, recorded by collect_news.py in data/query_performance.json)
plus a sample of recently-kept events, and asks Gemini to PROPOSE an improved set:
  - up to 10 search queries (hard cap), optimizing for:
      * relevance to samsung.com traffic & revenue
      * minimal duplicate collection (distinct angles, not near-synonyms)
  - KW_KEEP / KW_DROP keyword lists, optimizing for samsung.com relevance.

IMPORTANT — gradual change: we keep the query count at 10 and replace AT MOST 3
queries per day, preferring to drop the worst performers (low pass-rate, high dup).
This keeps collection stable and avoids Gemini churning the whole set daily.

Optimization basis = NEWS pipeline only (Gemini-judged). First-party feeds are NOT
used as a basis (they skip Gemini, so they'd pollute the signal).

Writes:
  - queries.txt            (the 10 search queries; shared by collect_news.py + collect_gdelt.py)
  - data/kw_filters.json   ({"KW_KEEP":[...], "KW_DROP":[...]}; read by collect_news.py)
  - data/optimize_log.json (audit trail of changes)

If Gemini is unavailable (no key / quota), the script leaves everything unchanged.
"""
import os, json, time, urllib.request, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
QFILE = os.path.join(HERE, "..", "queries.txt")
KWFILE = os.path.join(HERE, "..", "data", "kw_filters.json")
STATFILE = os.path.join(HERE, "..", "data", "query_performance.json")
EVFILE = os.path.join(HERE, "..", "data", "events.json")
LOGFILE = os.path.join(HERE, "..", "data", "optimize_log.json")

MAX_QUERIES = 10
MAX_REPLACE = 3   # max queries replaced per day (gradual)
MAX_BRAND = 4     # max queries that directly contain "samsung" or "galaxy"
BRAND_TERMS = ("samsung", "galaxy")

def brand_count(queries):
    return sum(1 for q in queries if any(b in q.lower() for b in BRAND_TERMS))

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

def load_queries():
    out = []
    try:
        for line in open(QFILE, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    except Exception:
        pass
    return out

def write_queries(qs):
    header = ("# News search queries — shared by NewsAPI and GDELT (refreshed daily by optimize.py)\n"
              "# One per line. '#' comments and blank lines ignored. Max 10.\n\n")
    open(QFILE, "w", encoding="utf-8").write(header + "\n".join(qs) + "\n")

def load_kw():
    try:
        d = json.load(open(KWFILE, encoding="utf-8"))
        return d.get("KW_KEEP", []), d.get("KW_DROP", [])
    except Exception:
        return None, None

def recent_perf():
    """Aggregate per-query performance over recent days -> {query: {raw,dup,kept,pass_rate,dup_rate}}."""
    try:
        hist = json.load(open(STATFILE, encoding="utf-8"))
        if isinstance(hist, dict): hist = [hist]
    except Exception:
        return {}
    agg = {}
    for rec in hist[-7:]:  # last 7 days
        for q, p in (rec.get("per_query") or {}).items():
            a = agg.setdefault(q, {"raw":0,"dup":0,"kept":0})
            a["raw"] += p.get("raw",0); a["dup"] += p.get("dup",0); a["kept"] += p.get("kept",0)
    for q, a in agg.items():
        a["pass_rate"] = round(a["kept"]/a["raw"], 3) if a["raw"] else 0.0
        a["dup_rate"]  = round(a["dup"]/a["raw"], 3) if a["raw"] else 0.0
    return agg

def recent_kept_titles(n=25):
    try:
        ev = json.load(open(EVFILE, encoding="utf-8"))
    except Exception:
        return []
    ev = [e for e in ev if e.get("category") != "company" or e.get("source")]  # tend to skip seeds
    titles = [e.get("raw_title") or e.get("title","") for e in ev[-n:]]
    return [t for t in titles if t][:n]

def gemini(prompt):
    if not GEMINI_KEY:
        return None
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}")
    body = json.dumps({"contents":[{"parts":[{"text":prompt}]}]}).encode()
    try:
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type":"application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
        parts = (data.get("candidates",[{}])[0].get("content",{}) or {}).get("parts",[{}])
        text = "".join(p.get("text","") for p in parts).strip()
        return text.replace("```json","").replace("```","").strip()
    except Exception as e:
        print("  optimize gemini error:", e)
        return None

def main():
    cur_q = load_queries()
    perf = recent_perf()
    kept = recent_kept_titles()
    cur_keep, cur_drop = load_kw()

    perf_lines = []
    for q in cur_q:
        p = perf.get(q, {"raw":0,"kept":0,"pass_rate":0,"dup_rate":0})
        perf_lines.append(f'- "{q}": raw={p.get("raw",0)}, kept={p.get("kept",0)}, '
                          f'pass={p.get("pass_rate",0)}, dup={p.get("dup_rate",0)}')
    perf_txt = "\n".join(perf_lines) if perf_lines else "(no performance data yet)"
    kept_txt = "\n".join(f"- {t}" for t in kept) if kept else "(no recently kept articles)"

    prompt = (
        "You optimize news collection for a samsung.com external-factors tracker.\n"
        "Goal: improve relevance to samsung.com traffic/revenue and minimize duplicate\n"
        "article collection by refining the NewsAPI/GDELT search queries and keyword filters.\n\n"
        f"[Current query performance (last 7 days)]\n{perf_txt}\n\n"
        f"[Sample of recently kept (relevant) article titles]\n{kept_txt}\n\n"
        f"[Current queries] {cur_q}\n"
        f"[Current KW_KEEP] {cur_keep}\n"
        f"[Current KW_DROP] {cur_drop}\n\n"
        "Rules:\n"
        f"1) Exactly {MAX_QUERIES} queries, in English. Overly broad words (e.g. 'AI',"
        " 'economy') attract noise — pair them with 'Samsung' or make them more specific."
        " Avoid near-synonym queries to reduce duplicate collection.\n"
        f"2) AT MOST {MAX_BRAND} queries may directly contain 'samsung' or 'galaxy'. The"
        f" remaining {MAX_QUERIES-MAX_BRAND}+ must track the EXTERNAL environment (competitors"
        " like Apple/LG, smartphone/electronics/ecommerce market, economy, AI-search/platform"
        " shifts, regulation). This is an EXTERNAL-factors tracker, not a Samsung-news feed.\n"
        "3) Prefer replacing poor performers (low pass-rate, high dup-rate). For stability,"
        f" change at most {MAX_REPLACE} queries vs. the current set; keep the rest.\n"
        "4) New queries are welcome (emerging products/events/competitor keywords seen"
        " in recent articles).\n"
        "5) KW_KEEP: lowercase keep-keywords for judging samsung.com relevance. KW_DROP:"
        " obvious noise.\n\n"
        "Output ONLY this JSON (no explanation, no markdown). Write 'rationale' in Korean:\n"
        '{"queries":["..x10.."],"KW_KEEP":["..."],"KW_DROP":["..."],"rationale":"one-line summary"}'
    )

    raw = gemini(prompt)
    if not raw:
        print("optimize: Gemini unavailable - no change")
        return
    try:
        prop = json.loads(raw)
    except Exception as e:
        print("optimize: JSON parse failed - no change:", e)
        return

    new_q = [q.strip() for q in (prop.get("queries") or []) if q.strip()][:MAX_QUERIES]
    if len(new_q) < MAX_QUERIES:
        print("optimize: too few proposed queries - no change")
        return

    # Enforce gradual change: if more than MAX_REPLACE differ from current, revert the excess
    if cur_q:
        kept_same = [q for q in new_q if q in cur_q]
        changed = [q for q in new_q if q not in cur_q]
        if len(changed) > MAX_REPLACE:
            # Assign replacement slots starting from the worst-performing current queries
            worst = sorted(cur_q, key=lambda q: (perf.get(q,{}).get("pass_rate",0),
                                                 -perf.get(q,{}).get("dup_rate",0)))
            drop_slots = worst[:MAX_REPLACE]                 # current slots allowed to change
            keep_old = [q for q in cur_q if q not in drop_slots]
            new_q = (keep_old + changed[:MAX_REPLACE])[:MAX_QUERIES]
            # Fill any shortfall from the proposal
            for q in (kept_same + changed):
                if len(new_q) >= MAX_QUERIES: break
                if q not in new_q: new_q.append(q)
            new_q = new_q[:MAX_QUERIES]

    # Enforce brand cap: at most MAX_BRAND queries may contain samsung/galaxy.
    # If exceeded, drop the surplus brand queries and backfill with external
    # queries (prefer the current set's external queries, then generic fallbacks).
    if brand_count(new_q) > MAX_BRAND:
        brand_qs = [q for q in new_q if any(b in q.lower() for b in BRAND_TERMS)]
        other_qs = [q for q in new_q if q not in brand_qs]
        kept_brand = brand_qs[:MAX_BRAND]
        result = []
        for q in new_q:  # preserve order, keep only allowed brand queries
            if q in brand_qs and q not in kept_brand:
                continue
            result.append(q)
        # backfill to MAX_QUERIES with external queries not already present
        EXTERNAL_FALLBACK = ["smartphone market","consumer electronics market",
            "ecommerce market","ai search","apple smartphone","online retail",
            "ai shopping","tech market"]
        pool = [q for q in cur_q if not any(b in q.lower() for b in BRAND_TERMS)] + EXTERNAL_FALLBACK
        for q in pool:
            if len(result) >= MAX_QUERIES: break
            if q not in result: result.append(q)
        new_q = result[:MAX_QUERIES]
        print(f"optimize: brand cap applied -> {brand_count(new_q)} brand queries")
    new_keep = [k.strip().lower() for k in (prop.get("KW_KEEP") or []) if k.strip()]
    new_drop = [k.strip().lower() for k in (prop.get("KW_DROP") or []) if k.strip()]

    # Save
    write_queries(new_q)
    if new_keep and new_drop:
        json.dump({"KW_KEEP":new_keep, "KW_DROP":new_drop},
                  open(KWFILE,"w",encoding="utf-8"), ensure_ascii=False, indent=1)

    # Audit log
    try:
        log = json.load(open(LOGFILE, encoding="utf-8"))
        if not isinstance(log, list): log = [log]
    except Exception:
        log = []
    log.append({"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "old_queries": cur_q, "new_queries": new_q,
                "rationale": prop.get("rationale","")})
    log = log[-60:]
    json.dump(log, open(LOGFILE,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    print("optimize done. queries:", new_q)
    print("  rationale:", prop.get("rationale",""))

if __name__ == "__main__":
    main()
