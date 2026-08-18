#!/usr/bin/env python3
"""
Daily health probes — are the three LLM providers reachable, and does every
feed in feeds.txt still parse into items?

Both ran as their own script (check_model.py, check_feeds.py) doing the same
job at the same point in the workflow: fetch something cheap, write a status
JSON, print a one-line verdict. One file, one workflow step.

Neither touches events.json, and neither is allowed to fail the run: a probe
that cannot answer records "error" and the pipeline carries on.

⚠️ The model probe reads metadata; it does NOT generate. A provider can answer
"ok" here while returning empty content for every real judgement — that is
exactly what Groq did, unnoticed, for a month. Whether a provider is actually
working is only visible in data/llm_usage.json (ok / empty / ko_reject).

Writes data/model_status.json and data/feed_health.json.
"""
import os, sys, json, urllib.request, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
from llm_common import (GEMINI_KEY, GEMINI_MODEL, GROQ_KEY, GROQ_MODEL,
                        MISTRAL_KEY, MISTRAL_MODEL,
                        MODEL_STATUS_FILE, FEED_HEALTH_FILE, write_json)
from collect_feeds import http, parse_feed, load_feeds


# ============================================================ LLM providers
# Groq blocks the default Python-urllib UA (see llm_common.py's call_openai_chat_json).
# Without it here too, this health check reports Groq as down even on days
# collection successfully used Groq as a fallback.
UA = "scom-external/1.0 (+https://github.com/hyunho0812/scom-external)"


def check_gemini():
    if not GEMINI_KEY:
        return {"model": GEMINI_MODEL, "status": "unknown",
                "note": "No GEMINI_API_KEY set — Layer 1 falls further down the chain."}
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}?key={GEMINI_KEY}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            info = json.loads(r.read().decode())
        methods = info.get("supportedGenerationMethods", [])
        if "generateContent" in methods or not methods:
            return {"model": GEMINI_MODEL, "status": "ok",
                    "note": "Model responds and supports generateContent."}
        return {"model": GEMINI_MODEL, "status": "error",
                "note": "Model exists but may not support generateContent — verify."}
    except urllib.error.HTTPError as e:
        if e.code in (404, 400):
            return {"model": GEMINI_MODEL, "status": "retired",
                    "note": f"Model not found (HTTP {e.code}) — update GEMINI_MODEL."}
        return {"model": GEMINI_MODEL, "status": "error", "note": f"HTTP {e.code}."}
    except Exception as e:
        return {"model": GEMINI_MODEL, "status": "error", "note": f"Check failed: {e}"}


def check_groq():
    if not GROQ_KEY:
        return {"model": GROQ_MODEL, "status": "unknown",
                "note": "No GROQ_API_KEY set — 2nd fallback unavailable."}
    url = f"https://api.groq.com/openai/v1/models/{GROQ_MODEL}"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {GROQ_KEY}", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            info = json.loads(r.read().decode())
        if info.get("active", True):
            return {"model": GROQ_MODEL, "status": "ok", "note": "Model responds and is active."}
        return {"model": GROQ_MODEL, "status": "retired",
                "note": "Model exists but is marked inactive — update GROQ_MODEL."}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"model": GROQ_MODEL, "status": "retired",
                    "note": "Model not found (HTTP 404) — likely deprecated. "
                            "Check console.groq.com/docs/deprecations and update GROQ_MODEL."}
        return {"model": GROQ_MODEL, "status": "error", "note": f"HTTP {e.code}."}
    except Exception as e:
        return {"model": GROQ_MODEL, "status": "error", "note": f"Check failed: {e}"}


def check_mistral():
    if not MISTRAL_KEY:
        return {"model": MISTRAL_MODEL, "status": "unknown",
                "note": "No MISTRAL_API_KEY set — 3rd fallback unavailable."}
    # Mistral's free Experiment tier is 2 req/min; a model-list GET is a single
    # cheap call and won't meaningfully eat into that budget.
    url = "https://api.mistral.ai/v1/models"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {MISTRAL_KEY}", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            info = json.loads(r.read().decode())
        ids = [m.get("id") for m in info.get("data", [])]
        if MISTRAL_MODEL in ids:
            return {"model": MISTRAL_MODEL, "status": "ok",
                    "note": "Model found in the account's available model list."}
        return {"model": MISTRAL_MODEL, "status": "retired",
                "note": "Model not in the account's model list — update MISTRAL_MODEL."}
    except urllib.error.HTTPError as e:
        return {"model": MISTRAL_MODEL, "status": "error", "note": f"HTTP {e.code}."}
    except Exception as e:
        return {"model": MISTRAL_MODEL, "status": "error", "note": f"Check failed: {e}"}


def check_models():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    status = {
        "gemini": check_gemini(),
        "groq": check_groq(),
        "mistral": check_mistral(),
        "last_checked": now,
    }
    write_json(MODEL_STATUS_FILE, status)
    for name in ("gemini", "groq", "mistral"):
        s = status[name]
        print(f"{name} model status: {s['status']} - {s['model']}")


# ============================================================ RSS feeds
def check_one(label, url):
    try:
        raw = http(url)
    except urllib.error.HTTPError as e:
        return {"status": "error", "detail": f"HTTP {e.code}"}
    except Exception as e:
        return {"status": "error", "detail": f"{type(e).__name__}: {e}"}
    items = parse_feed(raw)
    if not items:
        # Could be a genuinely empty (but valid) feed, or unparsable content —
        # parse_feed() doesn't distinguish, so flag both as worth a human look.
        looks_like_xml = raw.strip()[:1] in (b"<",)
        detail = ("fetched OK but 0 items — parses as XML-ish but empty, or "
                   "not RSS/Atom at all" if looks_like_xml else
                   "fetched OK but 0 items — response doesn't look like XML "
                   "(likely a plain HTML page, not a feed)")
        return {"status": "empty", "detail": detail}
    return {"status": "ok", "detail": f"{len(items)} items"}


def check_feed_sources():
    feeds = load_feeds()
    results = {}
    for label, url in feeds.items():
        results[label] = check_one(label, url)
        icon = {"ok": "✓", "empty": "⚠", "error": "✗"}[results[label]["status"]]
        print(f"  {icon} {label}: {results[label]['detail']}")

    problems = {k: v for k, v in results.items() if v["status"] != "ok"}
    out = {"checked": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "feeds": results}
    write_json(FEED_HEALTH_FILE, out)

    print(f"\nfeed health: {len(results)-len(problems)}/{len(results)} OK")
    if problems:
        print(f"[diag] {len(problems)} feed(s) need attention: {list(problems.keys())}")

def main():
    check_models()
    print()
    check_feed_sources()


if __name__ == "__main__":
    main()
