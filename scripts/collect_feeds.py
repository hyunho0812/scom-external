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

# --- MyMemory free translation (no key; anonymous ~5,000 words/day) ---
# Translate first-party title/summary to Korean. On failure, return the original
# (English originals are always preserved separately in raw_* fields).
_tr_cache = {}
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
    snippet = text[:480]  # respect MyMemory per-request length limit
    try:
        url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(
            {"q": snippet, "langpair": "en|ko"})
        req = urllib.request.Request(url, headers={"User-Agent": "scom-tracker/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
        out = (data.get("responseData", {}) or {}).get("translatedText", "") or text
        # Guard against the API returning an error string as the translation
        if "MYMEMORY WARNING" in out or "INVALID" in out.upper():
            out = text
        _tr_cache[text] = out
        time.sleep(0.4)  # ease rate limit
        return out
    except Exception:
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
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 tracker"})
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
            title_ko = translate_ko(it["title"][:128])
            summary_ko = translate_ko((it["summary"][:200] or it["title"]))
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

if __name__ == "__main__":
    main()
