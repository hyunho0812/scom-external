#!/usr/bin/env python3
"""
Inter-rater reliability — do the three judges agree with each other?

Every number the dashboard shows is built on labels a single LLM produced:
impact_direction, impact_strength, axis. The chain picks whichever provider
answers first, so the SAME article can be labelled by Gemini today and Mistral
tomorrow. If those two would have disagreed, the labels are partly noise — and
no amount of downstream statistics can recover from noisy labels.

Nothing measured this. This script does: it re-judges a sample of recent
articles with all three providers INDEPENDENTLY (not the fallback chain) and
reports how often they agree. That agreement rate is a ceiling on how much the
labels can be trusted, and it belongs next to any credibility claim.

RAW AGREEMENT IS NOT THE ANSWER — READ THE KAPPA (2026-08-28)
The first three runs reported raw rates only, and they read far better than
they were. Two judges drawing labels independently out of a hat, in the
proportions the ledger already uses, would agree this often by luck alone:

    axis               0.675   (376 of 469 events are demand)
    strength_within_1  0.864   (58% of events are strength 3)
    confidence         0.520   (low is used 3 times in 469)
    strength (exact)   0.409
    direction          0.381

So an observed axis agreement of 0.625 is BELOW chance, and the docstring's
old advice — "within_1 is the useful number" — pointed at the single most
inflated figure on the sheet: 0.875 against a 0.864 baseline is nothing.
This is the same mistake `strength_calibration.convergence` already fixed by
reporting `random_gap` next to `mean_gap`, made a second time.

Every field now carries `chance` (expected agreement from the observed label
mix) and `kappa` = (observed - chance) / (1 - chance):

    kappa ~ 0     the judges agree no more than luck — the label is noise
    kappa < 0     they agree LESS than luck
    kappa > 0.4   the label carries real shared signal

Judge on kappa. The raw rate is kept only because it is what a reader
expects to see, and because kappa is meaningless without it.

Reading the fields:
  direction  — the load-bearing label. Near-zero kappa here means the axis
               percentages are largely reshuffling noise.
  axis       — decides which bucket an event lands in. Low kappa means the
               3-axis split is arbitrary.
  strength   — exact match on a 1-5 scale is harsh; within_1 is nearly
               free, so only its kappa says anything.
  confidence — weights every event's pressure. Low kappa here means the
               weighting is noise, whatever direction does.

A single run samples 10 articles, which is far too few to read on its own —
one run's kappa swings between -1 and 1 on chance alone. `pooled` re-derives
the same statistics over every stored run at once, and that is the figure to
quote. It is recomputed on each run from the raw per-provider labels, which
records now keep (`labels`), so the pooling never depends on rounded rates
and any disagreement can be re-examined later. The three legacy runs stored
before 2026-08-28 kept rates only and cannot join the pool; `pooled.runs`
says how many did.

Cost: one batch request per provider (BATCH items each), so a full run is
usually 3 requests. Runs daily — that fits every free tier we use, and a
weekly sample of 10 accumulates evidence far too slowly to be conclusive.

Env: same three keys as the collectors. Providers without a key are skipped.
"""
import os, sys, json, argparse, random
from collections import Counter
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
from llm_common import EVENTS_FILE, LLM_AGREEMENT_FILE, read_json, write_json
import llm_common as L

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=SAMPLE)
    args = ap.parse_args()

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
    L.diag_summary("check_llm_agreement")


if __name__ == "__main__":
    main()
