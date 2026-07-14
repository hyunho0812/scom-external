#!/usr/bin/env python3
"""
Layer 0 — daily search-query & keyword-filter optimizer (free, Gemini).

Runs BEFORE collection each day. It looks at how the current queries performed
(pass-rate and duplicate-rate, recorded by collect_news.py in data/query_performance.json),
a sample of recently-kept news article titles, and a sample of recently-kept
first-party feed event titles — then asks Gemini to PROPOSE an improved set:
  - up to 10 search queries (hard cap), one of 5 categories each (samsung,
    galaxy, ecommerce, smartphone, other), optimizing for:
      * relevance to samsung.com traffic & revenue
      * minimal duplicate collection (distinct angles, not near-synonyms)
  - kw_news.txt KEEP/DROP keyword lists (news pre-filter)
  - kw_feeds.txt KEEP/DROP keyword lists (first-party feed pre-filter — a
    SEPARATE list from news, since feed items differ in language/style,
    e.g. the Samsung newsroom KR feed needs Korean keywords)

IMPORTANT — gradual, per-category change: the CATEGORY COMPOSITION of the 10
queries (how many belong to each category) never changes here — only the
query TEXT within a category can be swapped, and AT MOST 1 per category per
day. For samsung/galaxy/ecommerce/smartphone (not "other"), the category must
always retain at least 1 query that literally contains its own category name
as a word — if a proposal would violate that, that category's change is
reverted for the day. This keeps collection stable and avoids Gemini churning
the whole set daily.

Query-performance basis = NEWS pipeline (per-query stats in
data/query_performance.json). Feed keyword-list tuning uses the analogous
per-SOURCE stats in data/feed_performance.json (written by collect_feeds.py:
raw/kw_pass/kept per feed label) plus a sample of recently-kept feed event
titles — this distinguishes "wrong keywords" (low kw_pass_rate) from "source
is on-topic but its content keeps getting judged out" (low keep_rate, e.g. a
forecast-heavy trend source after the 2026-07-08 forecast-reject rule).

Writes:
  - queries.txt            (10 'category | query' lines; shared by
                             collect_news.py + collect_gdelt.py)
  - kw_news.txt             (news pre-filter KEEP/DROP; read by collect_news.py)
  - kw_feeds.txt            (feed pre-filter KEEP/DROP; read by collect_feeds.py)
  - data/optimize_log.json (audit trail of changes)

If Gemini is unavailable (no key / quota), the script leaves everything unchanged.
"""
import os, sys, json, time, urllib.request, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
from llm_common import load_queries_tagged as _load_queries_tagged_raw, load_kw_file

QFILE = os.path.join(HERE, "..", "queries.txt")
KW_NEWS_FILE = os.path.join(HERE, "..", "kw_news.txt")
KW_FEEDS_FILE = os.path.join(HERE, "..", "kw_feeds.txt")
STATFILE = os.path.join(HERE, "..", "data", "query_performance.json")
FEED_STATFILE = os.path.join(HERE, "..", "data", "feed_performance.json")
EVFILE = os.path.join(HERE, "..", "data", "events.json")
LOGFILE = os.path.join(HERE, "..", "data", "optimize_log.json")

MAX_QUERIES = 10
MAX_BRAND = 4     # max queries (across all categories) that directly contain "samsung" or "galaxy"
BRAND_TERMS = ("samsung", "galaxy")
CATEGORIES = ["samsung", "galaxy", "ecommerce", "smartphone", "other"]
# Category -> the literal word that category must always keep at least 1 query
# holding (not enforced for "other", which has no fixed theme).
CATEGORY_NAME = {"samsung": "samsung", "galaxy": "galaxy",
                  "ecommerce": "ecommerce", "smartphone": "smartphone"}

def brand_count(queries):
    return sum(1 for q in queries if any(b in q.lower() for b in BRAND_TERMS))

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


# ===== queries.txt (category | query) — parsing itself lives in llm_common.py
# (shared with collect_news.py/collect_gdelt.py); this just adds the
# unknown-category-falls-back-to-'other' coercion optimize.py's constraint
# logic below depends on. =====
def load_queries_tagged():
    return [(cat if cat in CATEGORIES else "other", q)
            for cat, q in _load_queries_tagged_raw(QFILE)]

def write_queries_tagged(items):
    header = (
        "# News search queries — shared by NewsAPI and GDELT (refreshed daily by optimize.py)\n"
        "# Format: category | query text\n"
        "# Categories: samsung, galaxy, ecommerce, smartphone, other (exactly these 5)\n"
        "# One per line. '#' comments and blank lines ignored. Max 10.\n"
        "# optimize.py replaces AT MOST 1 query per category per day (not 3 total), and\n"
        "# for samsung/galaxy/ecommerce/smartphone (not \"other\") always keeps at least\n"
        "# 1 query that literally contains the category's own name as a word.\n\n"
    )
    body = "\n".join(f"{cat} | {q}" for cat, q in items)
    open(QFILE, "w", encoding="utf-8").write(header + body + "\n")


# ===== kw_news.txt / kw_feeds.txt — reading is shared (llm_common.load_kw_file);
# only the write side is optimizer-specific. =====
def write_kw_file(path, header_lines, keep, drop):
    lines = list(header_lines) + [""] + keep + [
        "", "# ---DROP--- (everything below: reject if present, checked before KEEP)", ""] + drop
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")

KW_NEWS_HEADER = [
    "# News pre-filter keywords (refreshed daily by optimize.py) — cheap relevance",
    "# gate before spending an LLM call. Checked against lowercased title+summary.",
    "# KEEP (below, until the DROP marker): article passes if ANY of these appear",
    "# (plus interests.txt topics, folded in automatically at load time).",
    "# One keyword per line. '#' comments and blank lines ignored.",
]
KW_FEEDS_HEADER = [
    "# First-party feed pre-filter keywords (refreshed daily by optimize.py) —",
    "# cheap relevance gate before spending an LLM call. Checked against",
    "# lowercased title+summary. KEEP (below, until the DROP marker): item",
    "# passes if ANY of these appear (plus interests.txt topics, folded in",
    "# automatically at load time). Includes Korean keywords (삼성/갤럭시/비스포크)",
    "# for the Samsung newsroom KR feed — do not remove them, KR items have no",
    "# other way to pass this filter.",
    "# One keyword per line. '#' comments and blank lines ignored.",
]


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

def recent_feed_perf():
    """Aggregate per-feed-source performance over recent days (written by
    collect_feeds.py) -> {label: {raw,kw_pass,kept,kw_pass_rate,keep_rate}}.
    keep_rate = kept/kw_pass — a source that's on-topic (high kw_pass) but has
    a low keep_rate is one whose content keeps getting judged out by the LLM
    (e.g. a forecast-heavy trend source since the 2026-07-08 forecast-reject
    rule), worth a human look even though it's not "broken" like check_feeds.py
    would flag."""
    try:
        hist = json.load(open(FEED_STATFILE, encoding="utf-8"))
        if isinstance(hist, dict): hist = [hist]
    except Exception:
        return {}
    agg = {}
    for rec in hist[-7:]:  # last 7 days
        for label, p in (rec.get("per_feed") or {}).items():
            a = agg.setdefault(label, {"raw": 0, "kw_pass": 0, "kept": 0})
            a["raw"] += p.get("raw", 0); a["kw_pass"] += p.get("kw_pass", 0); a["kept"] += p.get("kept", 0)
    for label, a in agg.items():
        a["kw_pass_rate"] = round(a["kw_pass"]/a["raw"], 3) if a["raw"] else 0.0
        a["keep_rate"] = round(a["kept"]/a["kw_pass"], 3) if a["kw_pass"] else 0.0
    return agg

def recent_kept_titles(n=25, prefix=None):
    """Sample recent event titles. prefix='A' -> news-pipeline events only,
    prefix='FP' -> first-party-feed events only, None -> either."""
    try:
        ev = json.load(open(EVFILE, encoding="utf-8"))
    except Exception:
        return []
    ev = [e for e in ev if e.get("category") != "company" or e.get("source")]  # tend to skip seeds
    if prefix:
        ev = [e for e in ev if str(e.get("event_id","")).startswith(prefix)]
    titles = [e.get("raw_title") or e.get("title","") for e in ev[-n:]]
    return [t for t in titles if t][:n]


def gemini(prompt, retries=2):
    if not GEMINI_KEY:
        return None
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
    }).encode()
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body,
                                         headers={"Content-Type":"application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
            parts = (data.get("candidates",[{}])[0].get("content",{}) or {}).get("parts",[{}])
            text = "".join(p.get("text","") for p in parts).strip()
            return text.replace("```json","").replace("```","").strip()
        except urllib.error.HTTPError as e:
            # 503/500/502/504 = Gemini transiently overloaded; 429 = rate limit.
            # Both are usually resolved by a short wait, so retry before giving up.
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = 10 * (attempt + 1)
                print(f"  optimize gemini HTTP {e.code} — retrying in {wait}s "
                      f"({attempt+1}/{retries})")
                time.sleep(wait)
                continue
            print("  optimize gemini error: HTTP", e.code, "(gave up)")
            return None
        except Exception as e:
            print("  optimize gemini error:", e)
            return None
    return None


def apply_query_constraints(cur_tagged, prop_queries, perf):
    """Pure function (no I/O) so it's unit-testable. cur_tagged = current
    [(category, query), ...]. prop_queries = Gemini's proposed
    [{"category":..., "query":...}, ...]. Returns the new [(category, query), ...],
    enforcing: (1) category composition (counts per category) never changes,
    (2) at most 1 query text swapped per category per day, (3) for
    samsung/galaxy/ecommerce/smartphone, at least 1 query in that category
    must still literally contain the category name after any swap, (4) the
    global brand cap (MAX_BRAND queries containing samsung/galaxy), preferring
    to protect samsung/galaxy category slots (which the composition already
    guarantees stay within cap) over other categories' slots when trimming."""
    cur_by_cat = {}
    for cat, q in cur_tagged:
        cur_by_cat.setdefault(cat, []).append(q)

    prop_by_cat = {}
    for it in (prop_queries or []):
        cat = str(it.get("category", "other")).strip().lower()
        q = str(it.get("query", "")).strip()
        if cat not in CATEGORIES:
            cat = "other"
        if q:
            prop_by_cat.setdefault(cat, []).append(q)

    new_by_cat = {}
    for cat, cur_list in cur_by_cat.items():
        prop_list = prop_by_cat.get(cat, [])
        # Match the proposal to the SAME slot count as today (pad/truncate with current).
        prop_list = (prop_list + cur_list)[:len(cur_list)]
        changed_idx = [i for i in range(len(cur_list)) if prop_list[i] != cur_list[i]]
        if len(changed_idx) > 1:
            # Only the first proposed change for this category survives; revert the rest.
            result = list(cur_list)
            result[changed_idx[0]] = prop_list[changed_idx[0]]
        else:
            result = prop_list
        name = CATEGORY_NAME.get(cat)
        if name and not any(name in q.lower() for q in result):
            result = list(cur_list)  # revert entirely — the swap would drop the anchor keyword
        new_by_cat[cat] = result

    # Rebuild in original file order.
    cat_cursor = {c: 0 for c in new_by_cat}
    new_tagged = []
    for cat, _ in cur_tagged:
        idx = cat_cursor[cat]
        new_tagged.append((cat, new_by_cat[cat][idx]))
        cat_cursor[cat] += 1

    # Global brand cap: samsung/galaxy categories already guarantee their own
    # minimum brand-containing queries, which by construction never exceeds
    # MAX_BRAND on their own (see queries.txt's seed composition). If a
    # non-samsung/galaxy category's NEW wording happens to also mention
    # "samsung"/"galaxy" and that pushes the total over the cap, revert just
    # that slot back to its pre-swap value (protecting samsung/galaxy slots,
    # which are never touched here).
    flat = [q for _, q in new_tagged]
    over = brand_count(flat) - MAX_BRAND
    if over > 0:
        protected_cats = {"samsung", "galaxy"}
        cat_seen = {c: 0 for c in cur_by_cat}
        fixed = []
        for cat, q in new_tagged:
            slot_idx = cat_seen[cat]
            cat_seen[cat] += 1
            is_new_brand_mention = (cat not in protected_cats and any(b in q.lower() for b in BRAND_TERMS)
                                     and q != cur_by_cat[cat][slot_idx])
            if over > 0 and is_new_brand_mention:
                fixed.append((cat, cur_by_cat[cat][slot_idx]))  # revert this slot to today's value
                over -= 1
            else:
                fixed.append((cat, q))
        new_tagged = fixed
    return new_tagged


def main():
    cur_tagged = load_queries_tagged()
    cur_q = [q for _, q in cur_tagged]
    perf = recent_perf()
    feed_perf = recent_feed_perf()
    kept_news = recent_kept_titles(prefix="A")
    kept_feeds = recent_kept_titles(prefix="FP")
    cur_keep_news, cur_drop_news = load_kw_file(KW_NEWS_FILE)
    cur_keep_feeds, cur_drop_feeds = load_kw_file(KW_FEEDS_FILE)

    perf_lines = []
    for q in cur_q:
        p = perf.get(q, {"raw":0,"kept":0,"pass_rate":0,"dup_rate":0})
        perf_lines.append(f'- "{q}": raw={p.get("raw",0)}, kept={p.get("kept",0)}, '
                          f'pass={p.get("pass_rate",0)}, dup={p.get("dup_rate",0)}')
    perf_txt = "\n".join(perf_lines) if perf_lines else "(no performance data yet)"
    feed_perf_lines = [f'- "{label}": raw={p["raw"]}, kw_pass_rate={p["kw_pass_rate"]}, '
                        f'keep_rate={p["keep_rate"]} (kept/kw_pass — low means content is '
                        f'on-topic but often judged out, e.g. forecast-heavy)'
                        for label, p in feed_perf.items()]
    feed_perf_txt = "\n".join(feed_perf_lines) if feed_perf_lines else "(no feed performance data yet)"
    kept_news_txt = "\n".join(f"- {t}" for t in kept_news) if kept_news else "(no recently kept news articles)"
    kept_feeds_txt = "\n".join(f"- {t}" for t in kept_feeds) if kept_feeds else "(no recently kept feed items)"
    cur_q_txt = "\n".join(f"- [{cat}] {q}" for cat, q in cur_tagged)

    prompt = (
        "You optimize collection for a samsung.com external-factors tracker.\n"
        "Goal: improve relevance to samsung.com traffic/revenue and minimize duplicate\n"
        "collection by refining the NewsAPI/GDELT search queries and the two keyword\n"
        "pre-filters (news vs. first-party feeds — feeds include a Korean-language\n"
        "Samsung newsroom, so its keyword list must keep Korean terms).\n\n"
        f"[Current query performance (last 7 days)]\n{perf_txt}\n\n"
        f"[Current feed source performance (last 7 days)]\n{feed_perf_txt}\n\n"
        f"[Sample of recently kept news article titles]\n{kept_news_txt}\n\n"
        f"[Sample of recently kept first-party feed item titles]\n{kept_feeds_txt}\n\n"
        f"[Current queries, with category]\n{cur_q_txt}\n\n"
        f"[Current kw_news KEEP] {cur_keep_news}\n"
        f"[Current kw_news DROP] {cur_drop_news}\n"
        f"[Current kw_feeds KEEP] {cur_keep_feeds}\n"
        f"[Current kw_feeds DROP] {cur_drop_feeds}\n\n"
        "Rules:\n"
        f"1) Return exactly {MAX_QUERIES} queries in English, each tagged with its EXISTING\n"
        "   category (do not change how many queries belong to each category — only\n"
        "   propose new WORDING within a category if you think it would perform better).\n"
        f"2) AT MOST {MAX_BRAND} queries total may directly contain 'samsung' or 'galaxy'.\n"
        "   This is an EXTERNAL-factors tracker, not a Samsung-news feed.\n"
        "3) Prefer replacing poor performers (low pass-rate, high dup-rate). Only propose\n"
        "   a change for a category's query if you have a genuinely better wording — most\n"
        "   categories should stay unchanged most days (at most 1 change will be applied\n"
        "   per category regardless of how many you propose).\n"
        "4) For samsung/galaxy/ecommerce/smartphone categories, the query text you propose\n"
        "   should still relate to that theme; ideally contains the category's own word.\n"
        "5) kw_news KEEP/DROP: lowercase keywords for judging relevance of ENGLISH-language\n"
        "   news articles. kw_feeds KEEP/DROP: lowercase keywords for first-party feed items\n"
        "   (may include Korean — NEVER remove existing Korean keywords, they're required\n"
        "   for the Samsung newsroom KR feed to pass the filter at all).\n\n"
        "Output ONLY this JSON (no explanation, no markdown). Write 'rationale' in Korean:\n"
        '{"queries":[{"category":"samsung|galaxy|ecommerce|smartphone|other","query":"..."}, '
        '..x10 total..],"KW_NEWS_KEEP":["..."],"KW_NEWS_DROP":["..."],'
        '"KW_FEEDS_KEEP":["..."],"KW_FEEDS_DROP":["..."],"rationale":"one-line summary"}'
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

    prop_queries = prop.get("queries") or []
    if len(prop_queries) < MAX_QUERIES:
        print("optimize: too few proposed queries - no change")
        return

    new_tagged = apply_query_constraints(cur_tagged, prop_queries, perf)

    new_keep_news = [k.strip().lower() for k in (prop.get("KW_NEWS_KEEP") or []) if k.strip()]
    new_drop_news = [k.strip().lower() for k in (prop.get("KW_NEWS_DROP") or []) if k.strip()]
    new_keep_feeds = [k.strip().lower() for k in (prop.get("KW_FEEDS_KEEP") or []) if k.strip()]
    new_drop_feeds = [k.strip().lower() for k in (prop.get("KW_FEEDS_DROP") or []) if k.strip()]
    # Safety net: never let the Korean anchor keywords silently disappear from
    # kw_feeds (the Samsung KR feed has no other way to pass the pre-filter).
    for _kr in ("삼성", "갤럭시", "비스포크"):
        if new_keep_feeds and _kr not in new_keep_feeds:
            new_keep_feeds.append(_kr)

    # Save
    write_queries_tagged(new_tagged)
    if new_keep_news and new_drop_news:
        write_kw_file(KW_NEWS_FILE, KW_NEWS_HEADER, new_keep_news, new_drop_news)
    if new_keep_feeds and new_drop_feeds:
        write_kw_file(KW_FEEDS_FILE, KW_FEEDS_HEADER, new_keep_feeds, new_drop_feeds)

    # Audit log
    try:
        log = json.load(open(LOGFILE, encoding="utf-8"))
        if not isinstance(log, list): log = [log]
    except Exception:
        log = []
    new_q = [q for _, q in new_tagged]
    log.append({"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "old_queries": cur_q, "new_queries": new_q,
                "rationale": prop.get("rationale","")})
    log = log[-60:]
    json.dump(log, open(LOGFILE,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    print("optimize done. queries:", new_q)
    print("  rationale:", prop.get("rationale",""))

if __name__ == "__main__":
    main()
