#!/usr/bin/env python3
"""
Layer 2 — first-party feed monitor (FREE, no API calls).

Small platform changes (a minor ChatGPT UI tweak, a quiet policy edit) move
samsung.com traffic but stay below the press's threshold. So watch the SOURCE
directly: official blogs / release notes / RSS.

Filtering here is FREE keyword rules — no LLM, no paid API. First-party sources
are already trustworthy, so a light keyword gate is enough: keep entries whose
text hints at a change that could touch traffic/discovery/checkout, tag them by
simple rules, and log them. Tune KEYWORDS / NEGATIVE below to taste.

Feeds are read from feeds.txt (edit that file to add/remove sources).
"""
import os, json, time, hashlib, urllib.request, urllib.parse, urllib.error, re
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

HERE = os.path.dirname(__file__)

# --- Gemini free-tier one-line Korean summary (preferred) ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
_gemini_off = {"flag": False}   # set once quota is hit, to stop hammering
_sum_cache = {}
_sum_stats = {"ok": 0, "off": 0}  # diagnostics

SUMMARY_SYSTEM = (
 "You write a single-sentence Korean summary of a news item for a samsung.com "
 "traffic-monitoring dashboard. Summarize the MAIN point in ONE natural Korean "
 "sentence (<=60 Korean characters), focused on what could affect samsung.com "
 "web traffic or online sales. No quotes, no markdown, no preamble — output only "
 "the Korean sentence. If the item is not in English, still summarize in Korean."
)

def gemini_summary(title, summary):
    """Return a one-line Korean summary, or None if Gemini is unavailable."""
    if not GEMINI_KEY or _gemini_off["flag"]:
        _sum_stats["off"] += 1
        return None
    key = (title or "") + "||" + (summary or "")
    if key in _sum_cache:
        return _sum_cache[key]
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}")
    prompt = SUMMARY_SYSTEM + "\n\nTITLE: " + (title or "") + "\nBODY: " + (summary or "")
    body = json.dumps({
        "contents":[{"parts":[{"text":prompt}]}],
        "generationConfig":{"temperature":0.2,"maxOutputTokens":200,
                            "thinkingConfig":{"thinkingBudget":0}},
    }).encode()
    try:
        req = urllib.request.Request(url, data=body,
              headers={"Content-Type":"application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content",{}) or {}).get("parts",[{}])
        out = "".join(p.get("text","") for p in parts).strip()
        out = out.replace("```","").strip()
        time.sleep(6.0)  # stay under ~10 req/min free limit
        if not out:
            print(f"  Gemini summary empty (finishReason={cand.get('finishReason')})")
        if out:
            _sum_cache[key] = out
            _sum_stats["ok"] += 1
            return out
        return None
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("  Gemini quota hit (429) — feeds fall back to translation.")
            _gemini_off["flag"] = True
        else:
            print("  Gemini summary error", e.code)
        return None
    except Exception as e:
        print("  Gemini summary failed:", e); return None

# --- MyMemory free translation (no key; anonymous ~5,000 words/day) — fallback only ---
def clip_sentence(text, limit=400):
    """Trim to <= limit chars without cutting mid-word.
    Prefer ending at the last sentence boundary; otherwise the last space."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    if cut >= limit * 0.5:
        return head[:cut + 1].strip()
    sp = head.rfind(" ")
    return (head[:sp].strip() if sp > 0 else head.strip()) + "…"

# Translate first-party title/summary to Korean. On failure, return the original
# (English originals are always preserved separately in raw_* fields).
_tr_cache = {}
_tr_stats = {"ok": 0, "warning": 0, "exception": 0, "empty": 0}  # diagnostics

def translate_ko(text):
    text = (text or "").strip()
    if not text:
        return ""
    if text in _tr_cache:
        return _tr_cache[text]
    # If the text already contains Korean, leave it as-is
    if any('\uac00' <= c <= '\ud7a3' for c in text):
        _tr_cache[text] = text
        return text
    snippet = clip_sentence(text, 480)  # respect MyMemory per-request length limit, no mid-word cut
    try:
        url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(
            {"q": snippet, "langpair": "en|ko"})
        req = urllib.request.Request(url, headers={"User-Agent": "scom-tracker/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
        raw_out = (data.get("responseData", {}) or {}).get("translatedText", "")
        # MyMemory returns an error string (not a translation) when the daily quota
        # is exhausted or the request is invalid. Detect and log it explicitly.
        if not raw_out:
            _tr_stats["empty"] += 1
            print("  [translate] empty response from MyMemory")
            out = text
        elif "MYMEMORY WARNING" in raw_out or "INVALID" in raw_out.upper() \
                or data.get("quotaFinished"):
            _tr_stats["warning"] += 1
            print("  [translate] MyMemory quota/limit:", raw_out[:80])
            out = text
        else:
            _tr_stats["ok"] += 1
            out = raw_out
        _tr_cache[text] = out
        time.sleep(0.4)  # ease rate limit
        return out
    except Exception as e:
        _tr_stats["exception"] += 1
        print("  [translate] MyMemory request failed:", type(e).__name__, str(e)[:80])
        _tr_cache[text] = text
        return text

DATA  = os.path.join(HERE, "..", "data", "events.json")
STATE = os.path.join(HERE, "..", "data", "feed_state.json")


FEEDS_FILE = os.path.join(HERE, "..", "feeds.txt")

# Keep an entry if its text contains any of these (relevance gate).
KEYWORDS = [
    "launch","release","update","rollout","feature","redesign","ui","interface",
    "policy","privacy","ads","advertising","citation","search","ranking","price",
    "pricing","discount","store","checkout","payment","shopping","subscription",
    "region","country","available","deprecat","shutdown","sunset","partnership",
    "model","gpt","gemini","claude","copilot","perplexity","foldable","galaxy",
    "iphone","appliance","fridge","washer","tv","smartphone","tariff","regulation",
]
# Drop an entry if it's clearly irrelevant noise.
NEGATIVE = ["job","hiring","career","obituary","sponsorship of","charity run"]

# Simple category guesser by keyword.
def guess_category(label, text):
    t = (label + " " + text).lower()
    if any(k in t for k in ["gpt","gemini","claude","copilot","perplexity","model","ai "]):
        return "AI"
    if any(k in t for k in ["apple","lg ","whirlpool","iphone","galaxy","appliance"]):
        return "company"
    if any(k in t for k in ["privacy","policy","regulation","gdpr","ads","advertising"]):
        return "regulation" if "privacy" in t or "regulation" in t or "gdpr" in t else "marketing"
    if any(k in t for k in ["search","ranking","citation","social"]):
        return "platform"
    return "platform"

MARKETS = ["US","GB","DE","FR","ES","PT","BR","MX_C","AU","IN","TR","KR"]

def guess_divisions(label, text):
    t=(label+" "+text).lower(); out=[]
    if any(k in t for k in ["apple","iphone","ipad","mac","siri","ios"]): out.append("MX")
    if any(k in t for k in ["lg ","lg.","oled tv","lg electronics"]): out.append("VD")
    if any(k in t for k in ["whirlpool","washer","dryer","refrigerator","appliance","fridge"]): out.append("DA")
    return ";".join(out)

def guess_kpi(text):
    t=text.lower(); out=[]
    if any(k in t for k in ["search","citation","ranking","seo","visibility","ai answer","social"]):
        out += ["Impression","Click","Traffic"]
    if any(k in t for k in ["price","pricing","discount","inflation","tariff","economy","oil"]):
        out += ["CVR","Order","AOV","Revenue"]
    if any(k in t for k in ["launch","product","foldable","model","feature","release"]):
        out += ["Traffic","Order","Revenue"]
    if any(k in t for k in ["privacy","gdpr","regulation","tracking","consent"]):
        out += ["Traffic","CVR"]
    seen=[]; [seen.append(x) for x in out if x not in seen]
    return ";".join(seen) if seen else "Traffic"

def guess_direction(text):
    t = text.lower()
    if any(k in t for k in ["deprecat","shutdown","sunset","remove","discontinu","price increase"]):
        return "-"
    if any(k in t for k in ["launch","new ","expand","available","improve","faster"]):
        return "+"
    return "neutral"

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
    if any(n in t for n in NEGATIVE):
        return False
    return any(k in t for k in KEYWORDS)

def main():
    try: events = json.load(open(DATA, encoding="utf-8"))
    except Exception: events = []
    try: state = json.load(open(STATE, encoding="utf-8"))
    except Exception: state = {}
    existing_ids = {e.get("event_id") for e in events}
    feeds = load_feeds()
    print(f"loaded {len(feeds)} feeds from feeds.txt")
    added = 0
    for label, url in feeds.items():
        seen_links = set(state.get(label, []))
        try:
            items = parse_feed(http(url))
        except Exception as e:
            print("  feed error", label, e); continue
        fresh = [it for it in items if it["link"] and it["link"] not in seen_links][:10]
        for it in fresh:
            text = it["title"] + " " + it["summary"]
            if not it["title"] or not relevant(text):
                continue
            eid = "FP" + hashlib.md5((label + it["title"]).encode()).hexdigest()[:8]
            if eid in existing_ids:
                continue
            cat = guess_category(label, text)
            # Prefer a one-line Korean summary of the FULL original via Gemini.
            # Fall back to MyMemory translation of the (clipped) text if Gemini is unavailable.
            summary_ko = gemini_summary(it["title"], it["summary"])
            if summary_ko:
                title_ko = translate_ko(it["title"][:128])  # short title still translated
            else:
                title_ko = translate_ko(it["title"][:128])
                summary_ko = translate_ko(clip_sentence(it["summary"], 400) or it["title"])
            # Skip the item entirely if we could not get Korean text (both summary
            # and translation failed → would otherwise store raw English). Better to
            # drop it than pollute the feed with untranslated English.
            def _has_ko(s):
                return any('\uac00' <= c <= '\ud7a3' for c in (s or ""))
            if not _has_ko(summary_ko) and not _has_ko(title_ko):
                print("  - skip (no Korean):", it["title"][:50])
                continue
            events.append({
                "event_id": eid,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "captured_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "scope": ";".join(MARKETS),
                "divisions": guess_divisions(label, text),
                "kpi": guess_kpi(text),
                "category": cat,
                "title": f"[{label}] " + title_ko,
                "impact": "samsung.com 노출·유입에 영향 가능",
                "description": summary_ko,
                "impact_direction": guess_direction(text),
                "impact_horizon": "weeks",
                "confidence": "low",   # keyword-filtered → mark low, review in quarterly check
                "metric": "traffic",
                "source": label,
                "raw_title": it["title"],
                "raw_desc": it.get("summary",""),
                "raw_url": it.get("link",""),
            })
            existing_ids.add(eid); added += 1
            print("  + kept:", it["title"][:60])
        state[label] = list({it["link"] for it in items if it["link"]})[:300]
    json.dump(events, open(DATA,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(state,  open(STATE,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"first-party (free) done. added {added}, total {len(events)}")
    # --- translation/summary diagnostics (visible in GitHub Actions logs) ---
    print(f"[diag] Gemini summaries ok: {_sum_stats['ok']}, "
          f"unavailable: {_sum_stats['off']}")
    print(f"[diag] MyMemory translate — ok: {_tr_stats['ok']}, "
          f"quota_warning: {_tr_stats['warning']}, "
          f"exception: {_tr_stats['exception']}, empty: {_tr_stats['empty']}")
    if _tr_stats['warning'] or _tr_stats['exception'] or _tr_stats['empty']:
        print("[diag] ⚠ MyMemory had failures above — feeds may contain untranslated "
              "English unless Gemini summaries covered them.")

if __name__ == "__main__":
    main()
