#!/usr/bin/env python3
"""
Model health check — checks all THREE free LLMs used in the fallback chain
(Gemini -> Groq -> Mistral) and records whether each is alive.

Each is checked cheaply (a GET on a model-info/list endpoint, not an actual
generation call) so this script itself barely touches anyone's daily quota.

Writes data/model_status.json:
  {
    "gemini":  {"model": ..., "status": ..., "note": ...},
    "groq":    {"model": ..., "status": ..., "note": ...},
    "mistral": {"model": ..., "status": ..., "note": ...},
    "last_checked": "..."
  }
status is one of:
  "ok"      — key present, model responds
  "retired" — key present, but the model name 404s (likely deprecated/renamed)
  "unknown" — no key set for that provider
  "error"   — key present but the check failed some other way (network, 5xx, etc.)

Run daily (the workflow calls it before collection). The dashboard shows a
badge per LLM; if any shows "retired", swap that provider's *_MODEL env var
for a current model. Collection still runs meanwhile via the next LLM in the
chain, or the keyword-only fallback if all three are down.
"""
import os, sys, json, urllib.request, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
from llm_common import (GEMINI_KEY, GEMINI_MODEL, GROQ_KEY, GROQ_MODEL,
                         MISTRAL_KEY, MISTRAL_MODEL)

OUT  = os.path.join(HERE, "..", "data", "model_status.json")


def check_gemini():
    if not GEMINI_KEY:
        return {"model": GEMINI_MODEL, "status": "unknown",
                "note": "No GEMINI_API_KEY set — Layer 1 falls further down the chain."}
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}?key={GEMINI_KEY}")
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as r:
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
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {GROQ_KEY}"})
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
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {MISTRAL_KEY}"})
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


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    status = {
        "gemini": check_gemini(),
        "groq": check_groq(),
        "mistral": check_mistral(),
        "last_checked": now,
    }
    json.dump(status, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for name in ("gemini", "groq", "mistral"):
        s = status[name]
        print(f"{name} model status: {s['status']} - {s['model']}")


if __name__ == "__main__":
    main()
