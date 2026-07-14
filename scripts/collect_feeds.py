#!/usr/bin/env python3
"""
Layer 2 — first-party feed monitor (FREE, no paid API).

Small platform changes (a minor ChatGPT UI tweak, a quiet policy edit) move
samsung.com traffic but stay below the press's threshold. So watch the SOURCE
directly: official blogs / release notes / RSS.

A cheap keyword pre-filter first drops obvious noise (same two-stage design
as collect_news.py). Survivors then get the SAME rich LLM judgement as
regular news articles — relevance, category, phenomenon-start date, country/
division scope, KPI, impact direction/strength/confidence — via Gemini first,
Groq if Gemini's quota is exhausted, Mistral as last resort (all free, no
card, shared chain defined once in scripts/llm_common.py). If all three are
unavailable/fail, the item is skipped rather than stored with English text or
keyword-guessed classification.

Env (set as GitHub Secrets):
  GEMINI_API_KEY, GEMINI_MODEL   — aistudio.google.com/apikey (free, no card)
  GROQ_API_KEY, GROQ_MODEL       — console.groq.com/keys (free, no card)
  MISTRAL_API_KEY, MISTRAL_MODEL — console.mistral.ai (free, no card)

Feeds are read from feeds.txt (edit that file to add/remove sources).
"""
import os, sys, json, hashlib, urllib.request, urllib.parse, urllib.error, re
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
from llm_common import llm_filter, diag_summary, INTERESTS, MARKETS, load_kw_file, clean_axis

DATA = os.path.join(HERE, "..", "data", "events.json")
STATE = os.path.join(HERE, "..", "data", "feed_state.json")
FEEDS_FILE = os.path.join(HERE, "..", "feeds.txt")
PERF = os.path.join(HERE, "..", "data", "feed_performance.json")

# Keep an entry if its text contains any of these (cheap relevance gate,
# before spending an LLM call on it). Loaded from kw_feeds.txt (refreshed
# daily by optimize.py; collect_news.py has its own SEPARATE kw_news.txt,
# since feed items differ in language/style — e.g. the Samsung newsroom KR
# feed needs Korean keywords news articles never do). Same variable names
# (KW_KEEP/KW_DROP) as collect_news.py for consistency across both collectors.
_DEFAULT_KEEP = [
    "launch","release","update","rollout","feature","redesign","ui","interface",
    "policy","privacy","ads","advertising","citation","search","ranking","price",
    "pricing","discount","store","checkout","payment","shopping","subscription",
    "region","country","available","deprecat","shutdown","sunset","partnership",
    "model","gpt","gemini","claude","copilot","perplexity","foldable","galaxy",
    "iphone","appliance","fridge","washer","tv","smartphone","tariff","regulation",
    "xiaomi","vivo","oppo","tcl","hisense","bosch",
]
_DEFAULT_DROP = ["job","hiring","career","obituary","sponsorship of","charity run"]
KW_KEEP, KW_DROP = load_kw_file(os.path.join(HERE, "..", "kw_feeds.txt"))
if not (KW_KEEP and KW_DROP):
    KW_KEEP, KW_DROP = list(_DEFAULT_KEEP), list(_DEFAULT_DROP)
# Add interest keywords (interests.txt), same as collect_news.py does for its
# own KEEP list — previously only news got this boost, feeds did not.
for _kw in INTERESTS:
    if _kw.lower() not in KW_KEEP:
        KW_KEEP.append(_kw.lower())

def http(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()

def parse_feed(xml_bytes):
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return items
    for it in root.iter("item"):  # RSS
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "link":  (it.findtext("link") or "").strip(),
            "summary": re.sub("<[^>]+>"," ",(it.findtext("description") or "")).strip()[:600],
        })
    ns = "{http://www.w3.org/2005/Atom}"
    for it in root.iter(ns+"entry"):  # Atom
        link_el = it.find(ns+"link")
        items.append({
            "title": (it.findtext(ns+"title") or "").strip(),
            "link":  (link_el.get("href") if link_el is not None else "") or "",
            "summary": re.sub("<[^>]+>"," ",(it.findtext(ns+"summary") or it.findtext(ns+"content") or "")).strip()[:600],
        })
    return items

def load_feeds():
    feeds = {}
    try:
        for line in open(FEEDS_FILE, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            label, url = [p.strip() for p in line.split("|", 1)]
            if label and url:
                feeds[label] = url
    except FileNotFoundError:
        print("feeds.txt not found")
    return feeds

def relevant(text):
    t = text.lower()
    if any(n in t for n in KW_DROP):
        return False
    return any(k in t for k in KW_KEEP)


def main():
    try: events = json.load(open(DATA, encoding="utf-8"))
    except Exception: events = []
    try: state = json.load(open(STATE, encoding="utf-8"))
    except Exception: state = {}
    existing_ids = {e.get("event_id") for e in events}
    feeds = load_feeds()
    print(f"loaded {len(feeds)} feeds from feeds.txt")
    added = 0
    # Per-source performance: raw (fresh items seen) -> kw_pass (survived the
    # keyword pre-filter) -> kept (survived LLM judgement too). Lets a source
    # be diagnosed precisely: low kw_pass = wrong keywords or off-topic
    # source; kw_pass high but kept low = source is on-topic but its content
    # (e.g. forecasts) keeps getting judged out — see optimize.py, which uses
    # this file the same way it uses data/query_performance.json for news.
    perf = {}
    def bump(label, field):
        perf.setdefault(label, {"raw": 0, "kw_pass": 0, "kept": 0})
        perf[label][field] += 1
    for label, url in feeds.items():
        seen_links = set(state.get(label, []))
        try:
            items = parse_feed(http(url))
        except Exception as e:
            print("  feed error", label, e); continue
        fresh = [it for it in items if it["link"] and it["link"] not in seen_links][:10]
        for it in fresh:
            bump(label, "raw")
            text = it["title"] + " " + it["summary"]
            if not it["title"] or not relevant(text):
                continue  # obvious noise, never reaches any LLM
            bump(label, "kw_pass")
            eid = "FP" + hashlib.md5((label + it["title"]).encode()).hexdigest()[:8]
            if eid in existing_ids:
                continue
            # Same rich judgement as collect_news.py: Gemini -> Groq -> Mistral.
            article = {"title": it["title"], "desc": it["summary"], "source": label}
            verdict, llm_used = llm_filter(article)
            if verdict is None:
                # All three LLMs unavailable/failed — skip rather than store
                # English text or keyword-guessed classification.
                print("  - skip (no LLM available for judgement):", it["title"][:50])
                continue
            if not verdict.get("relevant"):
                continue  # the judging LLM says this isn't relevant after all
            _today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            _vdate = verdict.get("date", "") or ""
            event_date = _vdate if re.match(r"^\d{4}-\d{2}-\d{2}$", _vdate) else _today
            title_ko = (verdict.get("title") or it["title"])[:60]
            events.append({
                "event_id": eid,
                "date": event_date,
                "captured_date": _today,
                "scope": ";".join(verdict.get("scope") or MARKETS),
                "divisions": ";".join(verdict.get("divisions", [])),
                "kpi": ";".join(verdict.get("kpi", [])) or "Traffic",
                "category": verdict.get("category", "platform"),
                "title": f"[{label}] " + title_ko,
                "impact": verdict.get("impact", ""),
                "description": verdict.get("description", ""),
                "impact_direction": verdict.get("impact_direction", "unknown"),
                "impact_horizon": verdict.get("impact_horizon", "weeks"),
                "impact_strength": verdict.get("impact_strength", 2),
                "confidence": verdict.get("confidence", "med"),
                "metric": verdict.get("metric", "traffic"),
                "axis": clean_axis(verdict.get("axis", "")),  # demand|share|supply|"" (build.py falls back to a heuristic if empty)
                "llm": llm_used,  # which model judged/produced this, for the dashboard badge
                "source": label,
                "raw_title": it["title"],
                "raw_desc": it.get("summary", ""),
                "raw_url": it.get("link", ""),
            })
            existing_ids.add(eid); added += 1; bump(label, "kept")
            print("  + kept:", events[-1]["title"])
        state[label] = list({it["link"] for it in items if it["link"]})[:300]
    # New events are appended above with whatever date the LLM extracted
    # (often in the past relative to today) — re-sort by date every write so
    # the file-level invariant (CLAUDE.md's integrity checklist) never breaks.
    events.sort(key=lambda e: e.get("date", ""))
    json.dump(events, open(DATA,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(state,  open(STATE,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    statrec = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
               "total_raw": sum(p["raw"] for p in perf.values()),
               "total_kept": added, "per_feed": perf}
    try:
        hist = json.load(open(PERF, encoding="utf-8"))
        if not isinstance(hist, list): hist = [hist]
    except Exception:
        hist = []
    hist.append(statrec); hist = hist[-30:]  # keep last 30 days only
    json.dump(hist, open(PERF, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"first-party (free) done. added {added}, total {len(events)}")
    diag_summary("collect_feeds")

if __name__ == "__main__":
    main()
