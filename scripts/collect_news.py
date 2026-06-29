#!/usr/bin/env python3
import re
"""
Layer 1 — news collection with a FREE hybrid filter.

Pipeline:
  1. Pull recent articles from a news API (broad — includes noise).
  2. KEYWORD pre-filter: cheaply drop obvious noise, keep plausible candidates.
  3. GEMINI free-tier filter: the survivors get a precise relevance judgement
     from Gemini (Google AI Studio free tier — no cost, no credit card).
  4. If Gemini has no key or the daily free quota is exhausted (HTTP 429),
     FALL BACK to the keyword decision so the pipeline never stalls.
  5. Append passing events to data/events.json (deduped by title+date).

Everything here is free: news API free tier + Gemini free tier. The hybrid
order (keyword first) keeps Gemini calls low so you stay inside the free quota.

Env (set as GitHub Secrets):
  NEWS_API_KEY     — newsapi.org free tier (or adapt to another source)
  GEMINI_API_KEY   — from aistudio.google.com/apikey (free, no card)
  GEMINI_MODEL     — optional; defaults to gemini-2.5-flash
"""
import os, json, time, hashlib, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data", "events.json")
NEWS_KEY   = os.environ.get("NEWS_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

MARKETS = ["US","GB","DE","FR","ES","PT","BR","MX_C","AU","IN","TR","KR"]  # no GLOBAL; MX_C=Mexico (division MX is Apple)
DIVISIONS = {"MX":"Apple","VD":"LG","DA":"Whirlpool"}

def load_queries():
    """Load shared search queries from queries.txt (used by both news + GDELT)."""
    path = os.path.join(HERE, "..", "queries.txt")
    out = []
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    except Exception:
        pass
    # Safe defaults if the file is missing or empty
    return out or ["samsung", "samsung galaxy", "smartphone market", "ecommerce"]

QUERIES = load_queries()

# --- Interest keywords (loaded from interests.txt) ---
def load_interests():
    path = os.path.join(HERE, "..", "interests.txt")
    out = []
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    except Exception:
        pass
    return out

INTERESTS = load_interests()
# Interest keywords are NOT added as separate search queries (to save NewsAPI
# requests); they only feed the keyword dictionary (KW_KEEP) and the Gemini prompt.

# --- keyword pre-filter (free) ---
# --- keyword pre-filter (free) ---
# Prefer data/kw_filters.json (refreshed daily by optimize.py); else use defaults below.
_DEFAULT_KEEP = [
    "samsung","galaxy","smartphone","electronics","iphone","apple","foldable",
    "chatgpt","gemini","ai search","ad","advertis","gdpr","privacy","regulation",
    "oil","inflation","economy","tariff","holiday","sale","ecommerce","retail",
    "search","ranking","platform","tiktok","social","aging","consumer","tv","appliance",
]
_DEFAULT_DROP = ["football","cricket","soccer","obituary","horoscope","celebrity gossip"]
def _load_kw_filters():
    path = os.path.join(HERE, "..", "data", "kw_filters.json")
    try:
        d = json.load(open(path, encoding="utf-8"))
        keep = [k.lower() for k in d.get("KW_KEEP",[]) if k.strip()]
        drop = [k.lower() for k in d.get("KW_DROP",[]) if k.strip()]
        if keep and drop:
            return keep, drop
    except Exception:
        pass
    return list(_DEFAULT_KEEP), list(_DEFAULT_DROP)
KW_KEEP, KW_DROP = _load_kw_filters()
# Add interest keywords to the keep list (lowercased)
for _kw in INTERESTS:
    if _kw.lower() not in KW_KEEP:
        KW_KEEP.append(_kw.lower())

FILTER_SYSTEM = (
 "You filter news for relevance to samsung.com (Samsung's e-commerce/brand site). "
 "Decide if an item could plausibly affect samsung.com web traffic or online revenue, "
 "directly or indirectly. Be selective; ignore generic PR, sports, gossip, stock noise, "
 "and unrelated same-name entities.\n"
 "TWO EXTRA RULES (reject if either fails):\n"
 "1) SPECIFIC EVENT ONLY: keep only a specific, dated event or development (e.g. a product "
 "launch, a regulation, a named report/announcement, a concrete supply-chain or market shift). "
 "REJECT recurring/seasonal generalities that happen every year (e.g. 'Christmas shopping "
 "season', 'summer appliance demand', 'back-to-school', 'year-end slowdown') — these are not "
 "datable news events and must return relevant:false.\n"
 "2) PHENOMENON-START DATE: set 'date' to when the event/phenomenon ACTUALLY began or took "
 "effect per the article, NOT the article's publication date. For an ongoing phenomenon, use "
 "the date its real impact started (e.g. a rule's effective date, a launch date, when a "
 "disruption began). If the article only gives a publish date and no event date, use the "
 "event date implied by the content.\n"
 "ENCOURAGED — DATED STATISTICS/RESEARCH: actively KEEP statistics, surveys, and market-research "
 "findings about how people discover, research, and buy electronics — these are valuable. "
 "Examples: retail-channel share (Amazon/Walmart/Best Buy/Coupang/Naver), brand-site vs "
 "marketplace purchase behavior, research-vs-buy intent on brand sites, social-platform usage for "
 "product discovery (YouTube/Instagram/TikTok), social-commerce or live-commerce milestones, "
 "AI-shopping adoption. BUT keep such an item ONLY IF it has a datable anchor: a report's "
 "publication date, or a specific period record (e.g. 'BFCM 4-day sales', 'Q3 share', 'September "
 "ranking'). Use that anchor as 'date'. If a statistic is a vague always-true state with no "
 "report date or period (e.g. 'most people shop on mobile'), return relevant:false.\n"
 "Respond with ONLY a JSON object, no markdown:\n"
 '{\"relevant\":true|false,\"date\":\"YYYY-MM-DD (phenomenon-start date, see rule 2)\",'
 '\"category\":\"culture|marketing|platform|holiday|economy|'
 'social_issue|geopolitics|AI|company|regulation\",'
 '\"scope\":[country codes from US,GB,DE,FR,ES,PT,BR,MX_C,AU,IN,TR,KR that this affects; '
 'use the full list if it is worldwide],'
 '\"divisions\":[any of MX,VD,DA that this relates to — MX=Apple-relevant, VD=LG-relevant, '
 'DA=Whirlpool/home-appliance-relevant; empty if none],'
 '\"kpi\":[which samsung.com KPIs it likely affects, from '
 'Impression,Click,Traffic,Order,CVR,Revenue,AOV],'
 '\"title\":\"<=12 words\",'
 '\"impact\":\"one-line plain-language summary: what shifts -> which samsung.com KPIs move how\",'
 '\"description\":\"2-3 easy sentences a non-expert understands, naming the KPIs in context\",'
 '\"impact_direction\":\"+|-|neutral|unknown\",\"impact_horizon\":\"immediate|weeks|months\",'
 '\"impact_strength\":1-5 (1=negligible, 5=very large; size of the effect on '
 'samsung.com traffic/revenue),'
 '\"confidence\":\"high|med|low\",\"metric\":\"traffic|revenue|both\"}\n'
 'Write title, impact, and description IN KOREAN (한국어). If not relevant return {\"relevant\":false}.'
)

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

# Gemini quota state for this run: once we see 429, stop calling and fall back.
_gemini_exhausted = {"flag": False}

def gemini_filter(article):
    """Precise relevance via Gemini free tier. Returns dict, or None if Gemini
    is unavailable (caller then uses the keyword decision)."""
    if not GEMINI_KEY or _gemini_exhausted["flag"]:
        return None
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}")
    interest_note = ("\n\nPRIORITY TOPICS (treat as especially relevant if related): "
                     + ", ".join(INTERESTS)) if INTERESTS else ""
    prompt = (FILTER_SYSTEM + interest_note + "\n\nITEM:\nTITLE: " + article["title"] +
              "\nSUMMARY: " + article["desc"] + "\nSOURCE: " + article["source"])
    body = json.dumps({
        "contents":[{"parts":[{"text":prompt}]}],
        "generationConfig":{"temperature":0,"maxOutputTokens":300,
                            "responseMimeType":"application/json"},
    }).encode()
    try:
        data,_ = http_json(url, headers={"Content-Type":"application/json"},
                           data=body, method="POST")
        parts = (data.get("candidates",[{}])[0].get("content",{}) or {}).get("parts",[{}])
        text = "".join(p.get("text","") for p in parts).strip()
        text = text.replace("```json","").replace("```","").strip()
        time.sleep(6.0)  # avoid per-minute limit (~10/min), generous for up to 200 items
        return json.loads(text)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("  Gemini free quota hit (429) — falling back to keyword filter for the rest.")
            _gemini_exhausted["flag"] = True
        else:
            print("  Gemini error", e.code)
        return None
    except Exception as e:
        print("  Gemini parse error:", e); return None

def to_event(article, verdict, via):
    DEF_SCOPE = ";".join(MARKETS)
    # Prefer the phenomenon-start date Gemini extracted; fall back to publish date, then today.
    _today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _vdate = (verdict.get("date","") if verdict else "") or ""
    event_date = _vdate if re.match(r"^\d{4}-\d{2}-\d{2}$", _vdate) else (article["date"] or _today)
    return {
        "event_id":"A"+hashlib.md5((article["title"]+event_date).encode()).hexdigest()[:8],
        "date":event_date,
        "captured_date":_today,
        "scope":";".join(verdict.get("scope") or MARKETS) if verdict else DEF_SCOPE,
        "divisions":";".join(verdict.get("divisions",[])) if verdict else "",
        "kpi":";".join(verdict.get("kpi",[])) if verdict else "Traffic",
        "category":verdict.get("category","economy") if verdict else "economy",
        "title":(verdict.get("title") if verdict else article["title"])[:140],
        "impact":(verdict.get("impact","") if verdict else ""),
        "description":(verdict.get("description","") if verdict else
                       article["desc"][:200]),
        "impact_direction":verdict.get("impact_direction","unknown") if verdict else "unknown",
        "impact_horizon":verdict.get("impact_horizon","weeks") if verdict else "weeks",
        "impact_strength":(verdict.get("impact_strength",2) if verdict else 1),
        "confidence":(verdict.get("confidence","low") if verdict else "low"),
        "metric":verdict.get("metric","traffic") if verdict else "traffic",
        "source":article["source"] or article["url"],
        # Keep English originals (not shown on dashboard; available if needed)
        "raw_title":article.get("title",""),
        "raw_desc":article.get("desc",""),
        "raw_url":article.get("url",""),
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
    added = 0
    # Per-query performance: raw (fetched), dup (duplicates), kept (passed Gemini)
    perf = {}
    def bump(q, field):
        if not q: q = "(none)"
        perf.setdefault(q, {"raw":0,"dup":0,"kept":0})
        perf[q][field] += 1
    # Merge NewsAPI + GDELT into the same keyword->Gemini pipeline
    all_articles = fetch_news() + load_gdelt()
    for art in all_articles:
        q = art.get("query","")
        bump(q, "raw")
        key = (art["title"].lower(), art["date"])
        if not art["title"] or key in seen:
            bump(q, "dup")
            continue
        seen.add(key)  # dedup within this run
        text = art["title"] + " " + art["desc"]
        # Step 2: keyword pre-filter
        kw = keyword_verdict(text)
        if not kw:
            continue  # obvious noise, never reaches Gemini
        # Step 3: Gemini precise judgement (free)
        verdict = gemini_filter(art)
        if verdict is not None:
            if not verdict.get("relevant"):
                continue  # Gemini says no
            ev = to_event(art, verdict, via="gemini")
        else:
            # Step 4: fallback — keyword said keep, Gemini unavailable
            ev = to_event(art, None, via="keyword-fallback")
        events.append(ev); seen.add(key); added += 1; bump(q, "kept")
        print("  + kept:", ev["title"])
    # Events accumulate permanently (no pruning)
    json.dump(events, open(DATA,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    # Save per-query performance (optimize.py uses it next day)
    total_raw = sum(p["raw"] for p in perf.values())
    total_dup = sum(p["dup"] for p in perf.values())
    statrec = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
               "total_raw": total_raw, "total_dup": total_dup, "total_kept": added,
               "per_query": perf}
    try:
        hist = json.load(open(os.path.join(HERE,"..","data","query_performance.json"),encoding="utf-8"))
        if not isinstance(hist, list): hist = [hist]
    except Exception:
        hist = []
    hist.append(statrec); hist = hist[-30:]  # keep last 30 days only
    json.dump(hist, open(os.path.join(HERE,"..","data","query_performance.json"),"w",encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"layer1 done. added {added}, total {len(events)} | raw {total_raw}, dup {total_dup}")

if __name__ == "__main__":
    main()
