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
from llm_common import (llm_filter_batch, diag_summary, INTERESTS,
                        EVENTS_FILE, FEED_STATE_FILE, FEED_PERF_FILE,
                        FEEDS_FILE, KW_FEEDS_FILE, read_json, write_json,
                        load_kw_file, clean_axis, clean_scope, clean_date_ex, BATCH,
                        DupIndex, DEDUP_WINDOW_DAYS)

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
KW_KEEP, KW_DROP = load_kw_file(KW_FEEDS_FILE)
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

_MONTHS = {m: i for i, m in enumerate(
    ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"], 1)}


def feed_date(raw):
    """Normalise an RSS pubDate / Atom updated stamp to YYYY-MM-DD, or "".

    Feeds carry the real publish date and this parser previously threw it
    away, so every feed event fell back to "today" and the LLM's (unanchored)
    guess was the only date on offer. RFC-822 ('Tue, 05 Aug 2026 09:12:00
    GMT') and ISO-8601 ('2026-08-05T09:12:00Z') cover every feed in feeds.txt.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)          # ISO-8601 / Atom
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})", s)  # RFC-822
    if m and m.group(2).lower() in _MONTHS:
        return f"{m.group(3)}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return ""


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
            "published": feed_date(it.findtext("pubDate")
                                   or it.findtext("{http://purl.org/dc/elements/1.1/}date")),
        })
    ns = "{http://www.w3.org/2005/Atom}"
    for it in root.iter(ns+"entry"):  # Atom
        link_el = it.find(ns+"link")
        items.append({
            "title": (it.findtext(ns+"title") or "").strip(),
            "link":  (link_el.get("href") if link_el is not None else "") or "",
            "summary": re.sub("<[^>]+>"," ",(it.findtext(ns+"summary") or it.findtext(ns+"content") or "")).strip()[:600],
            "published": feed_date(it.findtext(ns+"published") or it.findtext(ns+"updated")),
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
    events = read_json(EVENTS_FILE, [])
    state = read_json(FEED_STATE_FILE, {})
    existing_ids = {e.get("event_id") for e in events}
    # Near-duplicate suppression — see llm_common.DupIndex. Seeded from the
    # file collect_news.py wrote minutes earlier in the same workflow, so a
    # story already taken from the news APIs is not re-stored from a feed.
    dup_index = DupIndex(events)
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
        perf.setdefault(label, {"raw": 0, "dup_near": 0, "kw_pass": 0, "kept": 0})
        perf[label][field] += 1
    # Pass 1: fetch every feed and keyword-filter it, collecting the survivors
    # across ALL feeds. Judging happens afterwards in batches, so the ~1.1k-token
    # instruction block is sent once per BATCH items instead of once per item
    # (and the request count — what the free tiers actually ration — drops by
    # the same factor). Feed state is still recorded per feed, exactly as before.
    candidates = []
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
            # Before the LLM: another source already told this story.
            hit = dup_index.find(raw_title=it["title"], url=it.get("link"),
                                 anchor=it.get("published") or None)
            if hit:
                bump(label, "dup_near")
                print(f"  - dup ({hit[1]} {hit[2]}) of: {hit[0].get('title','')[:50]}")
                continue
            bump(label, "kw_pass")
            eid = "FP" + hashlib.md5((label + it["title"]).encode()).hexdigest()[:8]
            if eid in existing_ids:
                continue
            existing_ids.add(eid)  # guard against duplicates within this run too
            candidates.append((label, it, eid))
        state[label] = list({it["link"] for it in items if it["link"]})[:300]

    # Pass 2: same rich judgement as collect_news.py (Gemini -> Groq -> Mistral),
    # BATCH items per request.
    for i in range(0, len(candidates), BATCH):
        chunk = candidates[i:i+BATCH]
        articles = [{"title": it["title"], "desc": it["summary"], "source": label}
                    for label, it, _ in chunk]
        for (label, it, eid), (verdict, llm_used) in zip(chunk, llm_filter_batch(articles)):
            if verdict is None:
                # All three LLMs unavailable/failed — skip rather than store
                # English text or keyword-guessed classification.
                print("  - skip (no LLM available for judgement):", it["title"][:50])
                continue
            if not verdict.get("relevant"):
                continue  # the judging LLM says this isn't relevant after all
            _today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            event_date, date_source = clean_date_ex(
                verdict.get("date", ""),
                published=it.get("published"), today=_today)
            title_ko = (verdict.get("title") or it["title"])[:60]
            # Second pass on the Korean title — the only comparison that can
            # match Samsung KR newsroom posts against English coverage of the
            # same launch. `label` is stripped by norm_title(), so the stored
            # "[source] title" form compares against a bare one correctly.
            hit = dup_index.find(ko_title=title_ko, anchor=event_date)
            if hit:
                bump(label, "dup_near")
                print(f"  - dup ({hit[1]} {hit[2]}) of: {hit[0].get('title','')[:50]}")
                continue
            events.append({
                "event_id": eid,
                "date": event_date,
                # Provenance of `date` — llm / url (feed pubDate) / capture.
                # See collect_news.to_event(); the scorer splits on this.
                "date_source": date_source,
                "captured_date": _today,
                "scope": clean_scope(verdict.get("scope")),  # see collect_news
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
                "raw_date": it.get("published", ""),  # feed pubDate, kept so a bad event_date stays repairable
            })
            dup_index.add(events[-1])
            added += 1; bump(label, "kept")
            print("  + kept:", events[-1]["title"])
    # New events are appended above with whatever date the LLM extracted
    # (often in the past relative to today) — re-sort by date every write so
    # the file-level invariant (CLAUDE.md's integrity checklist) never breaks.
    events.sort(key=lambda e: e.get("date", ""))
    write_json(EVENTS_FILE, events)
    write_json(FEED_STATE_FILE, state)
    statrec = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
               "total_raw": sum(p["raw"] for p in perf.values()),
               "total_dup_near": sum(p["dup_near"] for p in perf.values()),
               "total_kept": added, "per_feed": perf}
    hist = read_json(FEED_PERF_FILE, [])
    if not isinstance(hist, list): hist = [hist]
    hist.append(statrec); hist = hist[-30:]  # keep last 30 days only
    write_json(FEED_PERF_FILE, hist)
    print(f"first-party (free) done. added {added}, total {len(events)} | "
          f"near-dup {sum(p['dup_near'] for p in perf.values())} (<={DEDUP_WINDOW_DAYS}d)")
    diag_summary("collect_feeds")

if __name__ == "__main__":
    main()
