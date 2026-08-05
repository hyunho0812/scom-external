#!/usr/bin/env python3
"""
Shared LLM judgement chain (Gemini -> Groq -> Mistral) used by BOTH
collect_news.py (NewsAPI/GDELT) and collect_feeds.py (first-party RSS).

Both collectors judge items the exact same way: a cheap keyword pre-filter
first (each collector keeps its own, since the keyword lists differ), then
this shared rich judgement — relevance, category, phenomenon-start date,
country/division scope, KPI, impact direction/strength/confidence — via
whichever of the three free LLMs is currently available. Centralizing this
means a Gemini quota outage never degrades either collector's classification
to hardcoded guesses; Groq or Mistral judge it for real, using the identical
prompt/schema, so results stay consistent regardless of which model answered.

Env (set as GitHub Secrets):
  GEMINI_API_KEY, GEMINI_MODEL   — aistudio.google.com/apikey (free, no card)
  GROQ_API_KEY, GROQ_MODEL       — console.groq.com/keys (free, no card)
  MISTRAL_API_KEY, MISTRAL_MODEL — console.mistral.ai (free, no card)

Also the single home for small pieces of config shared by 3+ scripts, so they
don't drift out of sync the way the old per-collector keyword lists did:
MARKETS, load_queries()/load_queries_tagged() (queries.txt), load_kw_file()
(kw_news.txt/kw_feeds.txt), has_korean(), clip_sentence().
"""
import os, json, time, urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(__file__)

# Countries the dashboard tracks (no GLOBAL scope value; MX_C=Mexico, since
# the division code MX is reserved for the mobile/phones business unit).
MARKETS = ["US", "GB", "DE", "FR", "ES", "PT", "BR", "MX_C", "AU", "IN", "TR", "KR"]

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
MISTRAL_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")

_gemini_off = {"flag": False}
_groq_off = {"flag": False}
_mistral_off = {"flag": False}

# Per-provider telemetry for one run, persisted to data/llm_usage.json by
# save_usage(). These counters used to be three {ok, off, error} dicts printed
# to stdout and then lost with the Actions log, which made two things
# impossible to answer after the fact: how many requests each free tier
# actually consumed, and WHY the chain fell through to a later provider.
# The fields below separate the failure modes that matter for that:
#   attempt    - HTTP requests actually sent (what burns the free-tier quota)
#   ok         - returned a verdict the chain accepted
#   ko_reject  - returned a verdict, but title/impact/description weren't in
#                Korean, so _korean_fields_ok discarded it and the chain moved
#                on. Costs FULL tokens and yields nothing — the expensive
#                failure, and invisible in the old counters (they scored it
#                "ok" because the call itself succeeded).
#   empty      - responded, but with no usable output to parse
#   http_429   - rate/quota limited (sets the provider's off flag for the run)
#   http_auth  - 401/403 (also sets the off flag)
#   http_other - any other HTTP error
#   exception  - transport/parse failure
#   skipped_off- not called at all: no API key, or already disabled this run.
#                Costs nothing; this is why fallback is a per-RUN cost, not a
#                per-item one — after the first 429 the chain stops retrying
#                that provider entirely.
_STAT_FIELDS = ("attempt", "ok", "ko_reject", "empty", "http_429", "http_auth",
                "http_other", "exception", "skipped_off")
_STATS = {p: dict.fromkeys(_STAT_FIELDS, 0) for p in ("gemini", "groq", "mistral")}


def _bump(provider, field, n=1):
    _STATS[provider][field] += n


def has_korean(s):
    return any('\uac00' <= c <= '\ud7a3' for c in (s or ""))


# axis: which of the 3-axis-panel buckets (demand/share/supply) an event
# mainly acts through \u2014 see FILTER_SYSTEM below for the full definitions the
# LLM is given. clean_axis() guards against a malformed/missing value from
# the LLM; the collectors store "" in that case, and build.py's axisOf()
# falls back to its own keyword heuristic for any event with axis=="" (this
# is also what makes it a safe upgrade for the 90+ events collected before
# this field existed).
VALID_AXES = {"demand", "share", "supply"}
def clean_axis(v):
    v = (v or "").strip().lower()
    return v if v in VALID_AXES else ""


def clip_sentence(text, limit=400):
    """Trim to <= limit chars without cutting mid-word.
    Prefer ending at the last sentence boundary; otherwise the last word."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    if cut >= limit * 0.5:
        return head[:cut + 1].strip()
    sp = head.rfind(" ")
    return (head[:sp].strip() if sp > 0 else head.strip()) + "…"


# --- Priority topics (interests.txt) — folded into the judgement prompt so
# both collectors treat these subjects as especially relevant if related. ---
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


# --- queries.txt ('category | query text') — shared by collect_news.py,
# collect_gdelt.py and optimize.py so all three read the exact same file the
# exact same way. ---
def load_queries_tagged(path=None):
    """Returns [(category, query_text), ...] in file order."""
    path = path or os.path.join(HERE, "..", "queries.txt")
    out = []
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cat, q = [p.strip() for p in line.split("|", 1)] if "|" in line else ("other", line)
            if q:
                out.append((cat, q))
    except Exception:
        pass
    return out

def load_queries(path=None):
    """Query text only (category tag stripped) — for collectors that just
    fetch with these queries and don't need the category (optimize.py is the
    only caller that needs load_queries_tagged() directly, for tuning)."""
    out = [q for _, q in load_queries_tagged(path)]
    return out or ["samsung", "samsung galaxy", "smartphone market", "ecommerce"]


# --- kw_news.txt / kw_feeds.txt ('KEEP' lines, then a '# ---DROP---' marker
# line, then 'DROP' lines) — shared by collect_news.py, collect_feeds.py and
# optimize.py. ---
def load_kw_file(path):
    keep, drop, in_drop = [], [], False
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if "---DROP---" in line:
                    in_drop = True
                continue
            (drop if in_drop else keep).append(line.lower())
    except Exception:
        return [], []
    return keep, drop

FILTER_SYSTEM = (
 "Judge if this news item could plausibly affect samsung.com web traffic or "
 "revenue (direct or indirect). Reject generic PR, gossip, stock noise, "
 "unrelated same-name entities.\n"
 "RULES:\n"
 "1) Keep SPECIFIC dated events (launch, regulation, named report, "
 "supply-chain/market shift) AND general/gradual trend analysis backed by "
 "REALIZED data (e.g. a market-research firm's report on a structural shift "
 "that has ALREADY happened/been measured), even without one single anchor "
 "date. Recurring seasonal topics (holiday shopping, back-to-school) are "
 "fine too if there's a real data point or finding attached, not just a "
 "generic mention.\n"
 "2) REJECT forecasts/projections/predictions about the future (\"expected "
 "to grow to X by 2030\", \"market forecast to reach Y\", analyst/industry "
 "outlook pieces) and REJECT rumors/leaks/unconfirmed reports about a "
 "not-yet-official product (leaked pricing, leaked launch date, \"sources "
 "say\"). Reasoning like \"this forecast/leak means traffic is already "
 "shifting in anticipation\" is too speculative to keep. This does NOT "
 "apply to a company's own OFFICIAL confirmed announcement of a future "
 "launch/event (e.g. Samsung officially announcing a product ships on a "
 "specific date) — that's a real, dated corporate action and should be kept.\n"
 "3) 'date' = when the event/phenomenon ACTUALLY began/took effect (not the "
 "article's publish date) if there is one. For general trend analysis with "
 "no single event date, use the report's publish date instead.\n"
 "4) KEEP dated stats/surveys on how people discover/research/buy electronics "
 "(retail-channel share, brand-site vs marketplace behavior, social product "
 "discovery, AI-shopping adoption, market research reports) — as long as "
 "they report REALIZED findings, not a forward projection (see rule 2).\n"
 "Respond with ONLY this JSON, no markdown:\n"
 '{"relevant":true|false,"date":"YYYY-MM-DD","category":"culture|marketing|'
 'platform|holiday|economy|social_issue|geopolitics|AI|company|regulation",'
 '"scope":[country codes from US,GB,DE,FR,ES,PT,BR,MX_C,AU,IN,TR,KR; full '
 'list if worldwide],"divisions":[MX=mobile/phones (Apple,Xiaomi,vivo,OPPO-relevant),'
 'VD=TV/display (LG,TCL,Hisense-relevant),DA=home appliances (LG,Whirlpool,'
 'Bosch-relevant); empty if none],"kpi":[from Impression,Click,Traffic,Order,CVR,Revenue,AOV],'
 '"title":"<=12 words","impact":"one line: what shifts -> which KPIs, how",'
 '"description":"2 Korean sentences ending in plain 다/했다/이다 style (NOT '
 'polite 요/습니다 endings), in SIMPLE everyday words a non-expert would use '
 '(avoid stiff/formal or technical jargon; write like explaining to a '
 'colleague, not a report). First sentence: what happened. Second sentence: '
 'specifically how this could affect samsung.com WEB TRAFFIC itself (more/'
 'fewer visits, how people find/reach the site, session behavior) — NOT a '
 'general statement about purchase decisions or consumer behavior.",'
 '"impact_direction":'
 '"+|-|neutral|unknown","impact_horizon":"immediate|weeks|months",'
 '"impact_strength":1-5 (5=huge effect on samsung.com web traffic),'
 '"confidence":"high|med|low — YOUR CERTAINTY that this impact_direction/'
 'impact_strength judgement is correct (NOT the article\'s factual accuracy, '
 'NOT consistency with any traffic trend). high = direct, well-established '
 'causal link (e.g. a confirmed product launch or regulation). med = plausible '
 'but indirect or partly inferred. low = speculative or weak link.",'
 '"metric":"traffic|revenue|both",'
 '"axis":"demand|share|supply — WHICH of 3 causal buckets this event mainly '
 'acts through. demand = a MARKET-WIDE shift in overall interest/search '
 'volume/traffic pool that affects everyone in the category roughly equally, '
 'not specific to samsung.com vs one named rival (e.g. AI Overviews cutting '
 'click-through industry-wide, a memory-price macro shock, a holiday '
 'shopping surge, a broad social-commerce trend). share = REDISTRIBUTES '
 'visibility/traffic specifically BETWEEN samsung.com and a NAMED competitor '
 '(e.g. a competitor product launch/price move, an algorithm change that '
 'favors a named rival over Samsung). supply = about samsung.com\'s OWN site '
 '(indexing, crawling, outage, performance/Core Web Vitals) — never about a '
 'third party. When torn between demand and share, pick demand UNLESS a '
 'specific competitor is named as directly gaining at Samsung\'s expense."}\n'
 'title/impact/description IN KOREAN (한국어). If not relevant: {"relevant":false}.'
)


def _build_filter_prompt(article):
    interest_note = ("\n\nPRIORITY TOPICS (treat as especially relevant if related): "
                     + ", ".join(INTERESTS)) if INTERESTS else ""
    # Most article summaries are already short (NewsAPI/RSS truncate their
    # own way), but clip defensively — an occasional long one would otherwise
    # bloat every judgement call's token cost for no benefit to the verdict.
    return (FILTER_SYSTEM + interest_note + "\n\nITEM:\nTITLE: " + article["title"] +
            "\nSUMMARY: " + clip_sentence(article["desc"], 400) + "\nSOURCE: " + article["source"])


def call_openai_chat_json(url, api_key, model, prompt, max_tokens=600, temperature=0,
                          timeout=30, extra=None):
    """POST to an OpenAI-compatible /chat/completions endpoint (Groq, Mistral).
    Returns the raw parsed JSON dict (any schema), or None on empty output.

    extra: provider-specific body fields (e.g. Groq's reasoning_effort). Kept
    separate so an unsupported field can be dropped and the call retried."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature, "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if extra:
        payload.update(extra)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}",
                 "User-Agent": "scom-external/1.0 (+https://github.com/hyunho0812/scom-external)"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    out = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "").strip()
    out = out.replace("```json", "").replace("```", "").strip()
    if not out:
        return None
    return json.loads(out)


def gemini_filter(article):
    """1st choice. Full relevance/category/date/impact judgement via Gemini's
    free tier. Returns verdict dict, or None if unavailable."""
    if not GEMINI_KEY or _gemini_off["flag"]:
        _bump("gemini", "skipped_off")
        return None
    _bump("gemini", "attempt")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}")
    body = json.dumps({
        "contents": [{"parts": [{"text": _build_filter_prompt(article)}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 600,
                              "responseMimeType": "application/json",
                              "thinkingConfig": {"thinkingBudget": 0}},
    }).encode()
    try:
        req = urllib.request.Request(url, data=body,
              headers={"Content-Type": "application/json",
                       "User-Agent": "scom-external/1.0 (+https://github.com/hyunho0812/scom-external)"},
              method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content", {}) or {}).get("parts", [{}])
        text = "".join(p.get("text", "") for p in parts).strip()
        text = text.replace("```json", "").replace("```", "").strip()
        time.sleep(6.0)  # avoid per-minute limit (~10/min)
        if not text:
            print(f"  Gemini returned empty text (finishReason={cand.get('finishReason')}) "
                  f"— treating as unavailable for this item.")
            _bump("gemini", "empty")
            return None
        verdict = json.loads(text)
        _bump("gemini", "ok")
        return verdict
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if e.code == 429:
            print("  Gemini quota hit (429) — falling back to Groq.")
            _gemini_off["flag"] = True
            _bump("gemini", "http_429")
        elif e.code in (401, 403):
            print(f"  Gemini auth/permission error {e.code} — {body} "
                  f"— disabling Gemini for the rest of this run.")
            _gemini_off["flag"] = True
            _bump("gemini", "http_auth")
        else:
            print(f"  Gemini error {e.code} — {body}")
            _bump("gemini", "http_other")
        return None
    except Exception as e:
        print("  Gemini parse error:", e)
        _bump("gemini", "exception")
        return None


# Groq's default model (openai/gpt-oss-120b) is a REASONING model: it emits
# reasoning tokens before the answer, and those count against max_tokens. At
# the shared max_tokens=600 the reasoning can consume the whole budget, so
# `choices[0].message.content` comes back empty, call_openai_chat_json returns
# None, and the chain silently falls through to Mistral.
#
# That matches the observed record exactly: Groq entered the chain on
# 2026-07-06 already on gpt-oss-120b and has produced ZERO kept events since,
# while check_model.py keeps reporting it "ok" (that check is a metadata GET —
# it never generates, so it cannot see this). It is the same failure the
# project already fixed for Gemini with thinkingConfig.thinkingBudget=0; the
# equivalent was simply never applied to Groq.
#
# So: cap the reasoning with reasoning_effort and give the call enough room for
# reasoning AND the JSON verdict. reasoning_effort is Groq-specific, so if this
# Groq account/model rejects it (HTTP 400), _groq_no_extra latches and every
# later call drops the field instead of failing outright.
GROQ_MAX_TOKENS = int(os.environ.get("GROQ_MAX_TOKENS", "1500"))
GROQ_REASONING_EFFORT = os.environ.get("GROQ_REASONING_EFFORT", "low")
_groq_no_extra = {"flag": False}


def _groq_extra():
    """Groq-only body fields, or None once the endpoint has rejected them."""
    if _groq_no_extra["flag"] or not GROQ_REASONING_EFFORT:
        return None
    if "gpt-oss" not in GROQ_MODEL and "reason" not in GROQ_MODEL:
        return None  # not a reasoning model — nothing to cap
    return {"reasoning_effort": GROQ_REASONING_EFFORT}


def groq_filter(article):
    """2nd choice. Same judgement as gemini_filter, served by Groq. Used only
    when Gemini is unavailable, so a Gemini outage no longer degrades
    classification to hardcoded defaults."""
    if not GROQ_KEY or _groq_off["flag"]:
        _bump("groq", "skipped_off")
        return None
    _bump("groq", "attempt")
    try:
        verdict = call_openai_chat_json(
            "https://api.groq.com/openai/v1/chat/completions", GROQ_KEY, GROQ_MODEL,
            _build_filter_prompt(article),
            max_tokens=GROQ_MAX_TOKENS, extra=_groq_extra())
        time.sleep(2.0)  # 30 RPM free limit
        # A falsy verdict here means the call succeeded but produced nothing
        # usable. That used to increment no counter at all, so the run looked
        # like Groq had never been asked.
        _bump("groq", "ok" if verdict else "empty")
        return verdict
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if e.code == 400 and _groq_extra():
            # The reasoning_effort field isn't accepted here. Latch it off and
            # retry this same item plainly, so adding the field can never make
            # Groq worse than it was without it.
            print(f"  Groq rejected reasoning_effort (400) — {body} "
                  f"— retrying without it and dropping it for this run.")
            _groq_no_extra["flag"] = True
            try:
                verdict = call_openai_chat_json(
                    "https://api.groq.com/openai/v1/chat/completions", GROQ_KEY,
                    GROQ_MODEL, _build_filter_prompt(article), max_tokens=GROQ_MAX_TOKENS)
                time.sleep(2.0)
                _bump("groq", "ok" if verdict else "empty")
                return verdict
            except Exception as e2:
                print("  Groq retry without reasoning_effort failed:", e2)
                _bump("groq", "exception")
                return None
        if e.code == 429:
            print("  Groq quota hit (429) — falling back to Mistral.")
            _groq_off["flag"] = True
            _bump("groq", "http_429")
        elif e.code in (401, 403):
            print(f"  Groq auth/permission error {e.code} — {body} "
                  f"— disabling Groq for the rest of this run.")
            _groq_off["flag"] = True
            _bump("groq", "http_auth")
        else:
            print(f"  Groq filter error {e.code} — {body}")
            _bump("groq", "http_other")
        return None
    except Exception as e:
        print("  Groq filter failed:", e)
        _bump("groq", "exception")
        return None


def mistral_filter(article):
    """3rd choice (last resort). Same judgement as gemini_filter/groq_filter,
    served by Mistral. Note: Mistral's free Experiment-tier requests may be
    used to train their models — fine here since this only ever handles
    public news/RSS text."""
    if not MISTRAL_KEY or _mistral_off["flag"]:
        _bump("mistral", "skipped_off")
        return None
    _bump("mistral", "attempt")
    try:
        verdict = call_openai_chat_json(
            "https://api.mistral.ai/v1/chat/completions", MISTRAL_KEY, MISTRAL_MODEL,
            _build_filter_prompt(article))
        time.sleep(31.0)  # Mistral free tier: 2 req/min — 31s gives a safety margin
        _bump("mistral", "ok" if verdict else "empty")
        return verdict
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if e.code == 429:
            print("  Mistral quota hit (429) — no LLM judge left this run.")
            _mistral_off["flag"] = True
            _bump("mistral", "http_429")
        elif e.code in (401, 403):
            print(f"  Mistral auth/permission error {e.code} — {body} "
                  f"— disabling Mistral for the rest of this run.")
            _mistral_off["flag"] = True
            _bump("mistral", "http_auth")
        else:
            print(f"  Mistral filter error {e.code} — {body}")
            _bump("mistral", "http_other")
        return None
    except Exception as e:
        print("  Mistral filter failed:", e)
        _bump("mistral", "exception")
        return None


def _korean_fields_ok(verdict):
    """The prompt requires title/impact/description IN KOREAN. Mistral in
    particular has been observed to comply for title/description but slip
    English into 'impact' — silently storing that would violate the
    no-English-text policy, so treat it the same as a failed judgement and
    let the chain fall through to the next LLM."""
    if not verdict.get("relevant", True):
        return True  # nothing to check when the item was judged not relevant
    for field in ("title", "impact", "description"):
        val = verdict.get(field)
        if val and not has_korean(val):
            return False
    return True


def llm_filter(article):
    """Run the full judgement chain: Gemini -> Groq -> Mistral. Returns
    (verdict_dict, model_name) or (None, "") if all three are unavailable —
    only then should the caller skip the item rather than store it with
    English text or guessed classification."""
    for fn, model, prov in ((gemini_filter, GEMINI_MODEL, "gemini"),
                            (groq_filter, GROQ_MODEL, "groq"),
                            (mistral_filter, MISTRAL_MODEL, "mistral")):
        verdict = fn(article)
        if verdict is not None and not _korean_fields_ok(verdict):
            print(f"  {model} returned non-Korean title/impact/description — "
                  f"treating as a failed judgement, trying next LLM.")
            # Re-attribute: the provider already scored an "ok" for answering,
            # but the chain is throwing that answer away. Without this the
            # counters would report a healthy provider that in fact produces
            # nothing usable while burning a full prompt's worth of tokens.
            _bump(prov, "ok", -1)
            _bump(prov, "ko_reject")
            verdict = None
        if verdict is not None:
            return verdict, model
    return None, ""


USAGE_FILE = os.path.join(HERE, "..", "data", "llm_usage.json")
USAGE_KEEP_DAYS = 30
_ORDER = (("gemini", "1st"), ("groq", "2nd"), ("mistral", "3rd"))


def diag_summary(label=""):
    """Print [diag] lines for all three providers' usage this run, then persist
    them via save_usage(). Call once at the end of a collector's main()."""
    prefix = f"[{label}] " if label else ""
    for prov, rank in _ORDER:
        s = _STATS[prov]
        print(f"{prefix}[diag] {prov} ({rank}) attempt: {s['attempt']}, ok: {s['ok']}, "
              f"ko_reject: {s['ko_reject']}, empty: {s['empty']}, "
              f"429: {s['http_429']}, auth: {s['http_auth']}, "
              f"other: {s['http_other']}, exc: {s['exception']}, "
              f"skipped_off: {s['skipped_off']}")
    if label:
        save_usage(label)


def save_usage(stage):
    """Append this run's per-provider counters to data/llm_usage.json.

    One record per collector run (stage = "collect_news" / "collect_feeds"),
    keyed by UTC date so a day with both collectors yields two records. Kept to
    the last USAGE_KEEP_DAYS days' worth. Never raises: telemetry must not be
    able to fail a collection run that otherwise succeeded.
    """
    from datetime import datetime, timezone
    try:
        rec = {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "stage": stage,
            "providers": {p: dict(_STATS[p]) for p, _ in _ORDER},
            # Total HTTP requests this run. This is the number that actually
            # drains the free tiers — and it is NOT items x 3: once a provider
            # 429s, its off flag skips it for the remainder of the run, so the
            # fallback is paid once per run rather than once per item.
            "total_attempts": sum(_STATS[p]["attempt"] for p, _ in _ORDER),
        }
        try:
            hist = json.load(open(USAGE_FILE, encoding="utf-8"))
            if not isinstance(hist, list):
                hist = [hist]
        except Exception:
            hist = []
        hist.append(rec)
        cutoff = sorted({r.get("date", "") for r in hist})[-USAGE_KEEP_DAYS:]
        hist = [r for r in hist if r.get("date", "") in cutoff]
        json.dump(hist, open(USAGE_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"  llm usage saved: {USAGE_FILE} ({rec['total_attempts']} API requests this run)")
    except Exception as e:
        print("  llm usage not saved:", e)

