#!/usr/bin/env python3
"""
Daily probes — is the machinery working, and can its labels be trusted?

Two subcommands, both diagnostics: they write a status JSON, print a verdict,
and never fail the run or touch events.json.

  health     Are the three LLM providers reachable, and does every feed in
             feeds.txt still parse into items?
             → data/model_status.json, data/feed_health.json
  agreement  Re-judge a sample of recent articles with all three providers
             INDEPENDENTLY and measure how often they agree. That agreement is
             a ceiling on how much any label can be trusted.
             → data/llm_agreement.json

They were check_health.py and check_llm_agreement.py; before that the health
half was check_model.py + check_feeds.py. Same consolidation as maintenance.py:
one file per job the pipeline actually has, subcommands for the variants.

⚠️ `health` reads model METADATA; it does NOT generate. A provider can answer
"ok" here while returning empty content for every real judgement — that is
exactly what Groq did, unnoticed, for a month. Whether a provider is actually
working is only visible in data/llm_usage.json (ok / empty / ko_reject).

⚠️ `agreement` reports kappa, not the raw agreement rate. Two judges drawing
labels out of this ledger's own mix agree 0.86 of the time on strength-within-1
and 0.68 on axis by luck alone, so the raw rate flatters itself badly. See the
kappa notes on chance() below.
"""
import os, sys, json, argparse, random, urllib.request, urllib.error
from collections import Counter
from datetime import datetime, timezone, timedelta

import llm_common as L


# ============================================================ health



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

def run_health(args):
    check_models()
    print()
    check_feed_sources()



# ============================================================ agreement


SAMPLE = int(os.environ.get("AGREEMENT_SAMPLE", "10"))
KEEP_RUNS = 90          # daily cadence — ~3 months of history
POOL_DAYS = 21          # sample from this much recent history, not just the tail

FIELDS = ("relevant", "direction", "axis", "strength", "strength_within_1", "confidence")


def already_measured():
    """event_ids this check has already judged, from the stored history."""
    hist = read_json(LLM_AGREEMENT_FILE, [])
    if isinstance(hist, dict):
        hist = [hist]
    seen = set()
    for rec in hist or []:
        seen.update(rec.get("event_ids") or [])
    return seen


def recent_articles(n):
    """Sample collector-shaped articles from recent stored events.

    Re-judging real items keeps the measurement on the same distribution the
    pipeline actually sees; a synthetic set would flatter the agreement.

    Running daily, taking the n most recent every time would re-measure the
    same articles on quiet days, which inflates the comparison count without
    adding information. So prefer items this check has never judged, drawn
    from a POOL_DAYS window rather than the tail, and only fall back to
    already-measured ones if that is not enough to fill the sample.
    """
    ev = read_json(EVENTS_FILE, [])
    seen = already_measured()
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=POOL_DAYS)).isoformat()

    def shape(e):
        return {"title": e.get("raw_title") or "",
                "desc": e.get("raw_desc") or "",
                "source": e.get("source") or "",
                "date": e.get("raw_date") or e.get("date") or "",
                "event_id": e.get("event_id")}

    pool = [e for e in ev if (e.get("raw_title") or "")
            and (e.get("captured_date") or e.get("date") or "") >= cutoff]
    if len(pool) < n:                       # quiet stretch — widen to the tail
        pool = [e for e in ev if e.get("raw_title")][-max(n * 4, 40):]

    fresh = [e for e in pool if e.get("event_id") not in seen]
    random.shuffle(fresh)
    picked = fresh[:n]
    if len(picked) < n:
        rest = [e for e in pool if e.get("event_id") in seen]
        random.shuffle(rest)
        picked += rest[:n - len(picked)]
    return [shape(e) for e in picked]


def judge_all(articles):
    """{provider: [verdict|None, ...]} — each provider judges independently."""
    prompt = L._build_batch_prompt(articles)
    cap = 300 + 320 * len(articles)
    results = {}
    for fn, model, name in L._chain():
        # Reset the per-run off flags so one provider's 429 cannot silently
        # skip the next — each judge must get a real chance to answer.
        for flag in (L._gemini_off, L._groq_off, L._mistral_off):
            flag["flag"] = False
        out = fn(prompt, cap)
        if isinstance(out, dict):
            vals = [v for v in out.values() if isinstance(v, list)]
            out = vals[0] if len(vals) == 1 else None
        if not isinstance(out, list) or len(out) != len(articles):
            print(f"  {name}: 배치 형태 불일치 — 이 provider는 제외")
            continue
        results[name] = [v if isinstance(v, dict) else None for v in out]
        print(f"  {name} ({model}): {sum(1 for v in results[name] if v)}건 판정")
    return results


def keep_labels(results):
    """Trim each verdict to the labels this check compares, for storage.

    Storing the raw labels (not just the rates they produce) is what lets
    `pooled` be recomputed exactly over all history, lets the chance baseline
    be derived from what the judges actually said, and lets a specific
    disagreement be looked at months later. Rounded rates support none of that.
    """
    out = {}
    for name, verdicts in results.items():
        row = []
        for v in verdicts:
            if not isinstance(v, dict):
                row.append(None)
                continue
            rec = {"relevant": bool(v.get("relevant"))}
            if rec["relevant"]:
                rec["impact_direction"] = (v.get("impact_direction") or "").strip() or None
                rec["impact_strength"] = v.get("impact_strength")
                rec["confidence"] = (v.get("confidence") or "").strip().lower() or None
                rec["axis"] = L.clean_axis(v.get("axis")) or None
            row.append(rec)
        out[name] = row
    return out


def _norm(v):
    """A stored label row -> comparable values per field, or None if absent.

    Returns None for the whole row when the provider returned nothing; a field
    is None when that provider left it blank, and a None never enters a
    comparison (a missing label is not a disagreement).
    """
    if not isinstance(v, dict):
        return None
    rel = bool(v.get("relevant"))
    out = {"relevant": rel, "direction": None, "axis": None,
           "confidence": None, "strength": None}
    if not rel:
        return out              # labels only exist for items judged relevant
    out["direction"] = (v.get("impact_direction") or "").strip() or None
    out["axis"] = L.clean_axis(v.get("axis")) or None
    out["confidence"] = (v.get("confidence") or "").strip().lower() or None
    try:
        s = int(v.get("impact_strength") or 0)
    except (TypeError, ValueError):
        s = 0
    out["strength"] = s or None
    return out


def tally(runs):
    """Count agreements over any number of runs.

    runs: [{provider: [stored label row | None, ...]}, ...]
    Returns (hits, marginals, per_pair) where hits[field] = [agree, n] and
    marginals[field] is every individual label value that entered a
    comparison — the chance baseline is estimated from those, so it describes
    the judges' own label mix rather than an assumed uniform one.
    """
    hits = {k: [0, 0] for k in FIELDS}
    marg = {k: [] for k in FIELDS}
    per_pair = {}

    for labels in runs:
        names = sorted(labels)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                pp = per_pair.setdefault(f"{a}|{b}", {k: [0, 0] for k in FIELDS})

                def add(field, x, y, agree=None):
                    if x is None or y is None:
                        return
                    ok = (x == y) if agree is None else agree(x, y)
                    for d in (hits[field], pp[field]):
                        d[0] += bool(ok)
                        d[1] += 1
                    marg[field].extend([x, y])

                for va, vb in zip(labels[a], labels[b]):
                    na, nb = _norm(va), _norm(vb)
                    if na is None or nb is None:
                        continue
                    add("relevant", na["relevant"], nb["relevant"])
                    if not (na["relevant"] and nb["relevant"]):
                        continue
                    for f in ("direction", "axis", "confidence"):
                        add(f, na[f], nb[f])
                    add("strength", na["strength"], nb["strength"])
                    add("strength_within_1", na["strength"], nb["strength"],
                        lambda x, y: abs(x - y) <= 1)
    return hits, marg, per_pair


def chance(field, values):
    """Agreement two judges would reach by luck, given the observed label mix.

    Sum of p^2 over the label distribution — the probability that two draws
    from it land on the same value. `strength_within_1` scores a hit whenever
    the values are one apart, so its baseline sums every such pair, which is
    why it comes out near 0.86 and why its raw rate says almost nothing.
    """
    if not values:
        return None
    n = len(values)
    p = {k: c / n for k, c in Counter(values).items()}
    if field == "strength_within_1":
        return sum(p[a] * p[b] for a in p for b in p if abs(a - b) <= 1)
    return sum(v * v for v in p.values())


def summarize(hits, marg):
    """rate / counts / chance / kappa per field, plus the comparison total."""
    rate, counts, ch, kap = {}, {}, {}, {}
    for f in FIELDS:
        agree, n = hits[f]
        counts[f] = [agree, n]
        rate[f] = round(agree / n, 3) if n else None
        pe = chance(f, marg[f])
        ch[f] = round(pe, 3) if pe is not None else None
        # kappa is undefined when chance agreement is total (every judge used
        # one label) — report None rather than a division blow-up.
        kap[f] = (round((agree / n - pe) / (1 - pe), 3)
                  if n and pe is not None and pe < 1 - 1e-9 else None)
    return {"rate": rate, "counts": counts, "chance": ch, "kappa": kap,
            "n_comparisons": hits["relevant"][1]}


def pooled(history):
    """Re-derive the statistics over every stored run that kept raw labels.

    One run of 10 articles cannot support a kappa, so this is the number to
    quote. Runs written before labels were stored contribute nothing and are
    counted out in `runs`/`runs_skipped` so the sample size stays honest.
    """
    runs = [r.get("labels") for r in history if isinstance(r.get("labels"), dict)]
    out = {"runs": len(runs), "runs_skipped": len(history) - len(runs)}
    if not runs:
        return out
    hits, marg, per_pair = tally(runs)
    out.update(summarize(hits, marg))
    out["pairwise"] = {k: {f: (round(v[f][0] / v[f][1], 3) if v[f][1] else None)
                           for f in FIELDS} | {"n": v["relevant"][1]}
                       for k, v in per_pair.items()}
    dated = [r.get("checked") for r in history if isinstance(r.get("labels"), dict)]
    if dated:
        out["from"], out["to"] = dated[0], dated[-1]
    return out


def run_agreement(args):
    articles = recent_articles(args.sample)
    if len(articles) < 2:
        print("재판정할 기사가 부족합니다 (raw_title 보유 이벤트 없음)")
        return
    print(f"최근 기사 {len(articles)}건을 3개 provider에 독립 판정 요청")

    results = judge_all(articles)
    if len(results) < 2:
        print("2개 이상의 provider 응답이 없어 일치도를 계산할 수 없습니다")
        return

    labels = keep_labels(results)
    hits, marg, per_pair = tally([labels])
    run = summarize(hits, marg)

    rec = {
        "checked": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sample": len(articles),
        # Stored so the next run can prefer articles it has not judged yet.
        "event_ids": [a.get("event_id") for a in articles if a.get("event_id")],
        "providers": sorted(results),
        # Kept flat for readers that predate the chance baseline.
        "overall": dict(run["rate"], n_comparisons=run["n_comparisons"]),
        "chance": run["chance"],
        "kappa": run["kappa"],
        "counts": run["counts"],
        "pairwise": {k: {f: (round(v[f][0] / v[f][1], 3) if v[f][1] else None)
                         for f in FIELDS} | {"n": v["relevant"][1]}
                     for k, v in per_pair.items()},
        "labels": labels,
        "note": ("Agreement is a ceiling on label trustworthiness: the chain uses "
                 "whichever provider answers first, so disagreement here is noise "
                 "already present in events.json. Read kappa, not the raw rate — "
                 "chance agreement is 0.86 on strength_within_1 and 0.68 on axis. "
                 "A single 10-article run is far too small; quote `pooled`."),
    }

    hist = read_json(LLM_AGREEMENT_FILE, [])
    if not isinstance(hist, list):
        hist = [hist]
    hist.append(rec)
    hist = hist[-KEEP_RUNS:]
    # Pooled is stored on the newest record so the dashboard, which reads the
    # last run, gets the accumulated figure without recomputing anything —
    # the screen and the file cannot disagree.
    rec["pooled"] = pooled(hist)
    write_json(LLM_AGREEMENT_FILE, hist)

    p = rec["pooled"]
    print(f"\n이번 런 (비교쌍 {run['n_comparisons']}건) — 관측 / 우연 / kappa:")
    for k in FIELDS:
        print(f"  {k:18s} {run['rate'][k]}  /  {run['chance'][k]}  /  {run['kappa'][k]}")
    if p.get("runs"):
        print(f"\n누적 {p['runs']}회 (비교쌍 {p['n_comparisons']}건):")
        for k in FIELDS:
            print(f"  {k:18s} {p['rate'][k]}  /  {p['chance'][k]}  /  {p['kappa'][k]}")
    print("saved:", LLM_AGREEMENT_FILE)
    # Telemetry label kept at its old spelling on purpose: llm_usage.json
    # groups 30 days of runs by this string, and renaming it would split the
    # history into two series that neither the file nor a reader can rejoin.
    L.diag_summary("check_llm_agreement")



def main():
    ap = argparse.ArgumentParser(description="daily diagnostics")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("health", help="LLM provider reachability + feed parsing")
    p.set_defaults(func=run_health)
    p = sub.add_parser("agreement", help="inter-rater reliability of the labels")
    p.add_argument("--sample", type=int, default=SAMPLE)
    p.set_defaults(func=run_agreement)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
