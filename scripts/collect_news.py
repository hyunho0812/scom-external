#!/usr/bin/env python3
"""
Layer 1 — news collection with a FREE hybrid filter.

Pipeline:
  1. Pull recent articles from a news API (broad — includes noise).
  2. KEYWORD pre-filter: cheaply drop obvious noise, keep plausible candidates.
  3. LLM judgement chain — the survivors get a precise relevance/category/date/
     impact judgement from Gemini first, then Groq if Gemini's daily quota is
     exhausted, then Mistral if Groq also fails (all free, no card). All three
     use the exact same judgement prompt/schema, so a Gemini outage no longer
     degrades classification to hardcoded defaults — Groq or Mistral judge it
     for real.
  4. Only if ALL THREE LLMs are unavailable/fail is the item skipped rather
     than stored with English text or guessed classification.
  5. Append passing events to data/events.json (deduped by title+date).

Everything here is free: news API free tier + Gemini + Groq + Mistral free
tiers. The hybrid order (keyword first) keeps LLM calls low so you stay
inside the free quota.

Env (set as GitHub Secrets):
  NEWS_API_KEY     — newsapi.org free tier (or adapt to another source)
  GEMINI_API_KEY   — from aistudio.google.com/apikey (free, no card)
  GEMINI_MODEL     — optional; defaults to gemini-2.5-flash
  GROQ_API_KEY     — from console.groq.com/keys (free, no card); 2nd choice,
                     used only when Gemini's daily quota is exhausted
  GROQ_MODEL       — optional; defaults to openai/gpt-oss-120b
  MISTRAL_API_KEY  — from console.mistral.ai (free "Experiment" tier, no card);
                     3rd choice (last resort), used only when both Gemini and
                     Groq are unavailable. Note: Experiment-tier requests may
                     be used by Mistral to train their models — fine here
                     since this only handles public news/RSS text.
  MISTRAL_MODEL    — optional; defaults to mistral-small-latest
"""
import os, sys, json, time, hashlib, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
from llm_common import (llm_filter_batch, diag_summary, INTERESTS, SCOPE_ALL,
                        load_queries, load_kw_file, clean_axis, clean_scope, clean_date_ex, BATCH,
                        DupIndex, DEDUP_WINDOW_DAYS)

DATA = os.path.join(HERE, "..", "data", "events.json")
NEWS_KEY = os.environ.get("NEWS_API_KEY", "")

QUERIES = load_queries()

# --- keyword pre-filter (free) ---
# kw_news.txt is refreshed daily by optimize.py; collect_feeds.py has its own
# SEPARATE kw_feeds.txt (feed items differ in language/style — e.g. the
# Samsung newsroom KR feed needs Korean keywords news articles never do).
_DEFAULT_KEEP = [
    "samsung","galaxy","smartphone","electronics","iphone","apple","foldable",
    "xiaomi","vivo","oppo","tcl","hisense","bosch",
    "chatgpt","gemini","ai search","ad","advertis","gdpr","privacy","regulation",
    "oil","inflation","economy","tariff","holiday","sale","ecommerce","retail",
    "search","ranking","platform","tiktok","social","aging","consumer","tv","appliance",
]
_DEFAULT_DROP = ["obituary","horoscope","celebrity gossip"]
KW_KEEP, KW_DROP = load_kw_file(os.path.join(HERE, "..", "kw_news.txt"))
if not (KW_KEEP and KW_DROP):
    KW_KEEP, KW_DROP = list(_DEFAULT_KEEP), list(_DEFAULT_DROP)
# Add interest keywords to the keep list (lowercased)
for _kw in INTERESTS:
    if _kw.lower() not in KW_KEEP:
        KW_KEEP.append(_kw.lower())

def http_json(url, headers=None, data=None, method="GET"):
    req = urllib.request.Request(url, headers=headers or {}, data=data, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode()), r.status

def fetch_news():
    if not NEWS_KEY:
        print("No NEWS_API_KEY — skipping news collection (dedup still runs).")
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    out = []
    rate_limited = False
    for q in QUERIES:
        if rate_limited:
            print("  rate-limited earlier — skipping remaining query:", q)
            continue
        url = "https://newsapi.org/v2/everything?" + urllib.parse.urlencode({
            "q": q, "from": since, "language": "en", "sortBy": "relevancy",
            "pageSize": 10, "apiKey": NEWS_KEY})
        ok = False
        for attempt in range(2):  # on 429, wait once and retry
            try:
                data,_ = http_json(url)
                for a in data.get("articles", []):
                    out.append({"title":a.get("title","") or "","desc":a.get("description","") or "",
                                "url":a.get("url","") or "","date":(a.get("publishedAt","") or "")[:10],
                                "source":(a.get("source",{}) or {}).get("name",""),"query":q})
                ok = True
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    if attempt == 0:
                        print("  429 (Too Many Requests) on", q, "— waiting 8s and retrying once...")
                        time.sleep(8)
                        continue
                    # Second 429 -> daily limit hit; skip remaining queries (keep what we have)
                    print("  429 again — NewsAPI daily limit likely reached; keeping",
                          len(out), "articles, skipping the rest.")
                    rate_limited = True
                    break
                else:
                    print("news fetch error", q, e)
                    break
            except Exception as e:
                print("news fetch error", q, e)
                break
        if ok:
            time.sleep(1.5)  # small gap between successful calls to ease rate pressure
    print("collected", len(out), "raw articles")
    return out

def keyword_verdict(text):
    t = text.lower()
    if any(k in t for k in KW_DROP): return False
    return any(k in t for k in KW_KEEP)

def to_event(article, verdict, llm_used):
    # Prefer the phenomenon-start date the LLM extracted; fall back to publish date, then today.
    _today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # NewsAPI/GDELT give us the real publish date — pass it as ground truth so
    # clean_date() can fall back to it instead of trusting a bogus LLM date.
    event_date, date_source = clean_date_ex(
        (verdict.get("date","") if verdict else ""),
        published=article.get("date"), today=_today)
    title_ko = verdict.get("title") if verdict else ""
    desc_ko = verdict.get("description", "") if verdict else ""
    return {
        "event_id":"A"+hashlib.md5((article["title"]+event_date).encode()).hexdigest()[:8],
        "date":event_date,
        # Where `date` came from — llm / url (publish date) / capture. The
        # scorer needs it to keep a capture-derived date out of the foreknown
        # bucket; without it every new event defaults to "seed".
        "date_source":date_source,
        "captured_date":_today,
        # clean_scope, not a bare join: the models answer this field with
        # "WW"/"worldwide" (and once with the instruction text itself), none of
        # which the dashboard filter can match.
        "scope":clean_scope(verdict.get("scope")) if verdict else SCOPE_ALL,
        "divisions":";".join(verdict.get("divisions",[])) if verdict else "",
        "kpi":";".join(verdict.get("kpi",[])) if verdict else "Traffic",
        "category":verdict.get("category","economy") if verdict else "economy",
        "title":(title_ko or article["title"])[:140],
        "impact":(verdict.get("impact","") if verdict else "samsung.com 노출·유입에 영향 가능"),
        "description":(desc_ko or ""),
        "impact_direction":verdict.get("impact_direction","unknown") if verdict else "unknown",
        "impact_horizon":verdict.get("impact_horizon","weeks") if verdict else "weeks",
        "impact_strength":(verdict.get("impact_strength",2) if verdict else 1),
        "confidence":(verdict.get("confidence","low") if verdict else "low"),
        "metric":verdict.get("metric","traffic") if verdict else "traffic",
        "axis":clean_axis(verdict.get("axis","")) if verdict else "",  # demand|share|supply|"" (build.py falls back to a heuristic if empty)
        "llm":llm_used,  # which model produced this judgement, for the dashboard badge
        "source":article["source"] or article["url"],
        # Keep English originals (not shown on dashboard; available if needed)
        "raw_title":article.get("title",""),
        "raw_desc":article.get("desc",""),
        "raw_url":article.get("url",""),
        "raw_date":article.get("date",""),  # source publish date, kept so a bad event_date stays repairable
    }

def load_gdelt():
    """Load the GDELT pool (gdelt_pool.json) into the same shape as NewsAPI items."""
    path = os.path.join(HERE, "..", "data", "gdelt_pool.json")
    try:
        items = json.load(open(path, encoding="utf-8"))
    except Exception:
        return []
    out = []
    for it in items:
        out.append({"title": it.get("title","") or "", "desc": "",
                    "url": it.get("url","") or "", "date": it.get("date","") or "",
                    "source": it.get("domain","") or "gdelt",
                    "query": it.get("query","")})
    print(f"loaded {len(out)} GDELT articles from raw pool")
    return out

def main():
    try: events = json.load(open(DATA, encoding="utf-8"))
    except Exception: events = []
    seen = {(e.get("title","").lower(), e.get("date","")) for e in events}
    # Near-duplicate suppression: NewsAPI, GDELT and the feeds all carry the
    # same story under different headlines, so exact-id dedup never caught it.
    # Within DEDUP_WINDOW_DAYS only the first source of a story is stored.
    dup_index = DupIndex(events)
    added = 0
    # Per-query performance: raw (fetched) -> dup (already seen) -> kw_pass
    # (survived the keyword pre-filter, i.e. the item actually reached an LLM)
    # -> kept (an LLM judged it relevant). kw_pass is the ONLY field that
    # reveals LLM call volume for this collector — without it, the pipeline's
    # single biggest token consumer can only be guessed at from collect_feeds'
    # rate. It also splits "query is off-topic" (low kw_pass) from "query is
    # on-topic but its articles get judged out" (kw_pass high, kept low), the
    # same diagnosis split collect_feeds.py already gives per source.
    perf = {}
    def bump(q, field):
        if not q: q = "(none)"
        perf.setdefault(q, {"raw":0,"dup":0,"dup_near":0,"kw_pass":0,"kept":0})
        perf[q][field] += 1
    # Merge NewsAPI + GDELT into the same keyword->LLM pipeline
    all_articles = fetch_news() + load_gdelt()
    # Step 2: keyword pre-filter first, for EVERY article, so the survivors can
    # then be judged in batches. (Judging one-at-a-time re-sent the ~1.1k-token
    # instruction block per article; batching amortises it across BATCH items
    # and cuts the request count by the same factor.)
    candidates = []
    for art in all_articles:
        q = art.get("query","")
        bump(q, "raw")
        key = (art["title"].lower(), art["date"])
        if not art["title"] or key in seen:
            bump(q, "dup")
            continue
        seen.add(key)  # dedup within this run
        # Checked BEFORE the keyword filter and the LLM: a story we already
        # have from another source should cost zero requests. The anchor is
        # the article's own publish date, which is what its event date will
        # be built from.
        hit = dup_index.find(raw_title=art["title"], url=art["url"],
                             anchor=art.get("date") or None)
        if hit:
            bump(q, "dup_near")
            print(f"  - dup ({hit[1]} {hit[2]}) of: {hit[0].get('title','')[:50]}")
            continue
        if not keyword_verdict(art["title"] + " " + art["desc"]):
            continue  # obvious noise, never reaches any LLM
        bump(q, "kw_pass")  # counted BEFORE the chain: 1 kw_pass = 1 item judged
        candidates.append(art)
    # Step 3: precise judgement via Gemini -> Groq -> Mistral, BATCH at a time.
    for i in range(0, len(candidates), BATCH):
        chunk = candidates[i:i+BATCH]
        for art, (verdict, llm_used) in zip(chunk, llm_filter_batch(chunk)):
            q = art.get("query","")
            if verdict is None:
                # Step 4: all three LLMs unavailable/failed. Keyword said keep,
                # but with no LLM left we can't get real classification or
                # Korean text — skip rather than store an English,
                # hardcoded-low-confidence stub.
                print("  - skip (no LLM available for judgement):", art["title"][:50])
                continue
            if not verdict.get("relevant"):
                continue  # the judging LLM says this isn't relevant
            ev = to_event(art, verdict, llm_used)
            # Second pass, on the Korean title the LLM just wrote: it is the
            # only thing that matches a Korean-language source against English
            # coverage of the same story. Higher bar (DEDUP_KO_SIM) because
            # the model's stock phrasing makes unrelated events look alike.
            hit = dup_index.find(ko_title=ev["title"], anchor=ev["date"])
            if hit:
                bump(q, "dup_near")
                print(f"  - dup ({hit[1]} {hit[2]}) of: {hit[0].get('title','')[:50]}")
                continue
            dup_index.add(ev)
            events.append(ev); added += 1; bump(q, "kept")
            print("  + kept:", ev["title"])
    # Events accumulate permanently (no pruning). New events are appended
    # above with whatever date the LLM extracted (often in the past relative
    # to today, e.g. a phenomenon-start date) — re-sort by date every write so
    # the file-level invariant (CLAUDE.md's integrity checklist) never breaks.
    events.sort(key=lambda e: e.get("date", ""))
    json.dump(events, open(DATA,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    # Save per-query performance (optimize.py uses it next day)
    total_raw = sum(p["raw"] for p in perf.values())
    total_dup = sum(p["dup"] for p in perf.values())
    total_dup_near = sum(p["dup_near"] for p in perf.values())
    total_kw = sum(p["kw_pass"] for p in perf.values())
    statrec = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
               "total_raw": total_raw, "total_dup": total_dup,
               "total_dup_near": total_dup_near,
               "total_kw_pass": total_kw, "total_kept": added,
               "per_query": perf}
    try:
        hist = json.load(open(os.path.join(HERE,"..","data","query_performance.json"),encoding="utf-8"))
        if not isinstance(hist, list): hist = [hist]
    except Exception:
        hist = []
    hist.append(statrec); hist = hist[-30:]  # keep last 30 days only
    json.dump(hist, open(os.path.join(HERE,"..","data","query_performance.json"),"w",encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"layer1 done. added {added}, total {len(events)} | "
          f"raw {total_raw}, dup {total_dup}, near-dup {total_dup_near} "
          f"(<={DEDUP_WINDOW_DAYS}d), kw_pass {total_kw} (= LLM calls)")
    diag_summary("collect_news")

if __name__ == "__main__":
    main()
