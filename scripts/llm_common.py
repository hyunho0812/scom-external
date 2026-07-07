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
"""
import os, json, time, urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(__file__)

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
MISTRAL_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")

_gemini_off = {"flag": False}
_gemini_stats = {"ok": 0, "off": 0, "error": 0}
_groq_off = {"flag": False}
_groq_stats = {"ok": 0, "off": 0, "error": 0}
_mistral_off = {"flag": False}
_mistral_stats = {"ok": 0, "off": 0, "error": 0}


def has_korean(s):
    return any('\uac00' <= c <= '\ud7a3' for c in (s or ""))


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

FILTER_SYSTEM = (
 "Judge if this news item could plausibly affect samsung.com web traffic or "
 "revenue (direct or indirect). Reject generic PR, gossip, stock noise, "
 "unrelated same-name entities.\n"
 "RULES:\n"
 "1) Keep SPECIFIC dated events (launch, regulation, named report, "
 "supply-chain/market shift) AND general/gradual trend analysis backed by "
 "real data or research (e.g. a market-research firm's periodic report on a "
 "structural shift), even without one single anchor date. Recurring seasonal "
 "topics (holiday shopping, back-to-school) are fine too if there's a real "
 "data point or finding attached, not just a generic mention.\n"
 "2) 'date' = when the event/phenomenon ACTUALLY began/took effect (not the "
 "article's publish date) if there is one. For general trend analysis with "
 "no single event date, use the report's publish date instead.\n"
 "3) KEEP dated stats/surveys on how people discover/research/buy electronics "
 "(retail-channel share, brand-site vs marketplace behavior, social product "
 "discovery, AI-shopping adoption, market research reports).\n"
 "Respond with ONLY this JSON, no markdown:\n"
 '{"relevant":true|false,"date":"YYYY-MM-DD","category":"culture|marketing|'
 'platform|holiday|economy|social_issue|geopolitics|AI|company|regulation",'
 '"scope":[country codes from US,GB,DE,FR,ES,PT,BR,MX_C,AU,IN,TR,KR; full '
 'list if worldwide],"divisions":[MX=mobile/phones (Apple,Xiaomi,vivo,OPPO-relevant),'
 'VD=TV/display (LG,TCL,Hisense-relevant),DA=home appliances (LG,Whirlpool,'
 'Bosch-relevant); empty if none],"kpi":[from Impression,Click,Traffic,Order,CVR,Revenue,AOV],'
 '"title":"<=12 words","impact":"one line: what shifts -> which KPIs, how",'
 '"description":"2-3 plain sentences naming the KPIs, in SIMPLE everyday '
 'Korean words a non-expert would use (avoid stiff/formal or technical '
 'jargon; write like explaining to a colleague, not a report)",'
 '"impact_direction":'
 '"+|-|neutral|unknown","impact_horizon":"immediate|weeks|months",'
 '"impact_strength":1-5 (5=huge effect on samsung.com web traffic),'
 '"confidence":"high|med|low — YOUR CERTAINTY that this impact_direction/'
 'impact_strength judgement is correct (NOT the article\'s factual accuracy, '
 'NOT consistency with any traffic trend). high = direct, well-established '
 'causal link (e.g. a confirmed product launch or regulation). med = plausible '
 'but indirect or partly inferred. low = speculative or weak link.",'
 '"metric":"traffic|revenue|both"}\n'
 'title/impact/description IN KOREAN (한국어). If not relevant: {"relevant":false}.'
)


def _build_filter_prompt(article):
    interest_note = ("\n\nPRIORITY TOPICS (treat as especially relevant if related): "
                     + ", ".join(INTERESTS)) if INTERESTS else ""
    return (FILTER_SYSTEM + interest_note + "\n\nITEM:\nTITLE: " + article["title"] +
            "\nSUMMARY: " + article["desc"] + "\nSOURCE: " + article["source"])


def call_openai_chat_json(url, api_key, model, prompt, max_tokens=600, temperature=0, timeout=30):
    """POST to an OpenAI-compatible /chat/completions endpoint (Groq, Mistral).
    Returns the raw parsed JSON dict (any schema), or None on empty output."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature, "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
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
        _gemini_stats["off"] += 1
        return None
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
              headers={"Content-Type": "application/json"}, method="POST")
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
            return None
        verdict = json.loads(text)
        _gemini_stats["ok"] += 1
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
        elif e.code in (401, 403):
            print(f"  Gemini auth/permission error {e.code} — {body} "
                  f"— disabling Gemini for the rest of this run.")
            _gemini_off["flag"] = True
        else:
            print(f"  Gemini error {e.code} — {body}")
        _gemini_stats["error"] += 1
        return None
    except Exception as e:
        print("  Gemini parse error:", e)
        _gemini_stats["error"] += 1
        return None


def groq_filter(article):
    """2nd choice. Same judgement as gemini_filter, served by Groq. Used only
    when Gemini is unavailable, so a Gemini outage no longer degrades
    classification to hardcoded defaults."""
    if not GROQ_KEY or _groq_off["flag"]:
        _groq_stats["off"] += 1
        return None
    try:
        verdict = call_openai_chat_json(
            "https://api.groq.com/openai/v1/chat/completions", GROQ_KEY, GROQ_MODEL,
            _build_filter_prompt(article))
        time.sleep(2.0)  # 30 RPM free limit
        if verdict:
            _groq_stats["ok"] += 1
        return verdict
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if e.code == 429:
            print("  Groq quota hit (429) — falling back to Mistral.")
            _groq_off["flag"] = True
        elif e.code in (401, 403):
            print(f"  Groq auth/permission error {e.code} — {body} "
                  f"— disabling Groq for the rest of this run.")
            _groq_off["flag"] = True
        else:
            print(f"  Groq filter error {e.code} — {body}")
        _groq_stats["error"] += 1
        return None
    except Exception as e:
        print("  Groq filter failed:", e)
        _groq_stats["error"] += 1
        return None


def mistral_filter(article):
    """3rd choice (last resort). Same judgement as gemini_filter/groq_filter,
    served by Mistral. Note: Mistral's free Experiment-tier requests may be
    used to train their models — fine here since this only ever handles
    public news/RSS text."""
    if not MISTRAL_KEY or _mistral_off["flag"]:
        _mistral_stats["off"] += 1
        return None
    try:
        verdict = call_openai_chat_json(
            "https://api.mistral.ai/v1/chat/completions", MISTRAL_KEY, MISTRAL_MODEL,
            _build_filter_prompt(article))
        time.sleep(31.0)  # Mistral free tier: 2 req/min — 31s gives a safety margin
        if verdict:
            _mistral_stats["ok"] += 1
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
        elif e.code in (401, 403):
            print(f"  Mistral auth/permission error {e.code} — {body} "
                  f"— disabling Mistral for the rest of this run.")
            _mistral_off["flag"] = True
        else:
            print(f"  Mistral filter error {e.code} — {body}")
        _mistral_stats["error"] += 1
        return None
    except Exception as e:
        print("  Mistral filter failed:", e)
        _mistral_stats["error"] += 1
        return None


def llm_filter(article):
    """Run the full judgement chain: Gemini -> Groq -> Mistral. Returns
    (verdict_dict, model_name) or (None, "") if all three are unavailable —
    only then should the caller skip the item rather than store it with
    English text or guessed classification."""
    for fn, model in ((gemini_filter, GEMINI_MODEL), (groq_filter, GROQ_MODEL),
                      (mistral_filter, MISTRAL_MODEL)):
        verdict = fn(article)
        if verdict is not None:
            return verdict, model
    return None, ""


def diag_summary(label=""):
    """Print [diag] lines for all three providers' usage this run. Call once
    at the end of a collector's main()."""
    prefix = f"[{label}] " if label else ""
    print(f"{prefix}[diag] Gemini (1st) ok: {_gemini_stats['ok']}, "
          f"unavailable: {_gemini_stats['off']}, error: {_gemini_stats['error']}")
    print(f"{prefix}[diag] Groq (2nd) ok: {_groq_stats['ok']}, "
          f"unavailable: {_groq_stats['off']}, error: {_groq_stats['error']}")
    print(f"{prefix}[diag] Mistral (3rd) ok: {_mistral_stats['ok']}, "
          f"unavailable: {_mistral_stats['off']}, error: {_mistral_stats['error']}")

