#!/usr/bin/env python3
"""
Model health check — records which LLM the filter uses and whether it's alive.

Writes data/model_status.json, which the dashboard reads to show a badge:
  - model name in use
  - status: "ok" (responds), "retired" (404 / not found), "unknown" (no key),
            "error" (other failure)
  - last_checked timestamp
  - note for humans

Run daily (the workflow calls it before collection). If status is "retired",
the dashboard shows a red warning so you know to swap GEMINI_MODEL for a current
free Flash model. Collection still runs meanwhile via keyword fallback.
"""
import os, json, urllib.request, urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
OUT  = os.path.join(HERE, "..", "data", "model_status.json")
GEMINI_KEY   = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

def check():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not GEMINI_KEY:
        return {"model": GEMINI_MODEL, "status": "unknown", "last_checked": now,
                "note": "No GEMINI_API_KEY set — Layer 1 runs on keyword filter only."}
    # Ask the models endpoint about this specific model — cheap, no generation.
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}?key={GEMINI_KEY}")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as r:
            info = json.loads(r.read().decode())
        methods = info.get("supportedGenerationMethods", [])
        if "generateContent" in methods or not methods:
            return {"model": GEMINI_MODEL, "status": "ok", "last_checked": now,
                    "note": "Model responds and supports generateContent."}
        return {"model": GEMINI_MODEL, "status": "error", "last_checked": now,
                "note": "Model exists but may not support generateContent — verify."}
    except urllib.error.HTTPError as e:
        if e.code in (404, 400):
            return {"model": GEMINI_MODEL, "status": "retired", "last_checked": now,
                    "note": f"Model not found (HTTP {e.code}). It was likely retired — "
                            f"update GEMINI_MODEL to a current free Flash model."}
        return {"model": GEMINI_MODEL, "status": "error", "last_checked": now,
                "note": f"Check failed (HTTP {e.code})."}
    except Exception as e:
        return {"model": GEMINI_MODEL, "status": "error", "last_checked": now,
                "note": f"Check failed: {e}"}

def main():
    status = check()
    json.dump(status, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("model status:", status["status"], "-", status["model"])

if __name__ == "__main__":
    main()
