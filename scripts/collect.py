#!/usr/bin/env python3
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

COUNTRIES = ["US","GB","DE","FR","ES","PT","BR","MX_C","AU","IN","TR","KR"]  # no GLOBAL; MX_C=Mexico (division MX is Apple)
DIVISIONS = {"MX":"Apple","VD":"LG","DA":"Whirlpool"}

QUERIES = [
    "Samsung", "Galaxy smartphone", "Apple iPhone", "smartphone market",
    "consumer electronics demand", "ChatGPT search", "AI shopping",
    "oil price economy", "GDPR ecommerce", "foldable phone",
]

# --- keyword pre-filter (free) ---
KW_KEEP = [
    "samsung","galaxy","smartphone","electronics","iphone","apple","foldable",
    "chatgpt","gemini","ai search","ad","advertis","gdpr","privacy","regulation",
    "oil","inflation","economy","tariff","holiday","sale","ecommerce","retail",
    "search","ranking","platform","tiktok","social","aging","consumer","tv","appliance",
]
KW_DROP = ["football","cricket","soccer","obituary","horoscope","celebrity gossip"]

FILTER_SYSTEM = (
 "You filter news for relevance to samsung.com (Samsung's e-commerce/brand site). "
 "Decide if an item could plausibly affect samsung.com web traffic or online revenue, "
 "directly or indirectly. Be selective; ignore generic PR, sports, gossip, stock noise, "
 "and unrelated same-name entities. Respond with ONLY a JSON object, no markdown:\n"
 '{\"relevant\":true|false,\"category\":\"culture|marketing|platform|holiday|economy|'
 'social_issue|geopolitics|AI|competitor|regulation\",'
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
 '\"confidence\":\"high|med|low\",\"metric\":\"traffic|revenue|both\"}\n'
 'If not relevant return {\"relevant\":false}.'
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
    for q in QUERIES:
        url = "https://newsapi.org/v2/everything?" + urllib.parse.urlencode({
            "q": q, "from": since, "language": "en", "sortBy": "relevancy",
            "pageSize": 10, "apiKey": NEWS_KEY})
        try:
            data,_ = http_json(url)
            for a in data.get("articles", []):
                out.append({"title":a.get("title","") or "","desc":a.get("description","") or "",
                            "url":a.get("url","") or "","date":(a.get("publishedAt","") or "")[:10],
                            "source":(a.get("source",{}) or {}).get("name","")})
            time.sleep(1)
        except Exception as e:
            print("news fetch error", q, e)
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
    prompt = (FILTER_SYSTEM + "\n\nITEM:\nTITLE: " + article["title"] +
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
    DEF_SCOPE = ";".join(COUNTRIES)
    return {
        "event_id":"A"+hashlib.md5((article["title"]+article["date"]).encode()).hexdigest()[:8],
        "date":article["date"] or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "captured_date":datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "scope":";".join(verdict.get("scope") or COUNTRIES) if verdict else DEF_SCOPE,
        "divisions":";".join(verdict.get("divisions",[])) if verdict else "",
        "kpi":";".join(verdict.get("kpi",[])) if verdict else "Traffic",
        "category":verdict.get("category","economy") if verdict else "economy",
        "title":(verdict.get("title") if verdict else article["title"])[:140],
        "impact":(verdict.get("impact","") if verdict else ""),
        "description":(verdict.get("description","") if verdict else
                       article["desc"][:200]) + f"  [filter: {via}]",
        "impact_direction":verdict.get("impact_direction","unknown") if verdict else "unknown",
        "impact_horizon":verdict.get("impact_horizon","weeks") if verdict else "weeks",
        "confidence":(verdict.get("confidence","low") if verdict else "low"),
        "metric":verdict.get("metric","traffic") if verdict else "traffic",
        "source":article["source"] or article["url"],
    }

def main():
    try: events = json.load(open(DATA, encoding="utf-8"))
    except Exception: events = []
    seen = {(e.get("title","").lower(), e.get("date","")) for e in events}
    added = 0
    for art in fetch_news():
        key = (art["title"].lower(), art["date"])
        if not art["title"] or key in seen:
            continue
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
        events.append(ev); seen.add(key); added += 1
        print("  + kept:", ev["title"])
        time.sleep(0.3)
    json.dump(events, open(DATA,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"layer1 done. added {added}, total {len(events)}")

if __name__ == "__main__":
    main()
