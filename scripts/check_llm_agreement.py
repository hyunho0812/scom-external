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

Reading the output:
  direction  — the load-bearing label. Below ~0.7 the axis percentages are
               largely reshuffling noise.
  axis       — decides which bucket an event lands in. Low agreement here means
               the 3-axis split is arbitrary.
  strength   — exact-match is a harsh test on a 1-5 scale; within_1 is the
               useful number.

Cost: one batch request per provider (BATCH items each), so a full run is
usually 3 requests. Runs weekly from the daily workflow, not every day.

Env: same three keys as the collectors. Providers without a key are skipped.
"""
import os, sys, json, argparse
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
from llm_common import EVENTS_FILE, LLM_AGREEMENT_FILE, read_json, write_json
import llm_common as L

SAMPLE = int(os.environ.get("AGREEMENT_SAMPLE", "10"))
KEEP_RUNS = 12


def recent_articles(n):
    """Rebuild collector-shaped articles from the most recent stored events.

    Re-judging real items keeps the measurement on the same distribution the
    pipeline actually sees; a synthetic set would flatter the agreement.
    """
    ev = read_json(EVENTS_FILE, [])
    out = []
    for e in reversed(ev):
        title = e.get("raw_title") or ""
        if not title:
            continue
        out.append({"title": title,
                    "desc": e.get("raw_desc") or "",
                    "source": e.get("source") or "",
                    "date": e.get("raw_date") or e.get("date") or "",
                    "event_id": e.get("event_id")})
        if len(out) >= n:
            break
    return out


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


def agreement(results, articles):
    """Pairwise agreement on the three labels that drive the dashboard."""
    names = sorted(results)
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]]
    fields = {"relevant": [], "direction": [], "axis": [], "strength": [], "strength_within_1": []}
    per_pair = {}

    for a, b in pairs:
        acc = {k: [] for k in fields}
        for i in range(len(articles)):
            va, vb = results[a][i], results[b][i]
            if not va or not vb:
                continue
            ra, rb = bool(va.get("relevant")), bool(vb.get("relevant"))
            acc["relevant"].append(ra == rb)
            if not (ra and rb):
                continue          # labels only exist for items both judged relevant
            acc["direction"].append(va.get("impact_direction") == vb.get("impact_direction"))
            acc["axis"].append(L.clean_axis(va.get("axis")) == L.clean_axis(vb.get("axis")))
            try:
                sa, sb = int(va.get("impact_strength") or 0), int(vb.get("impact_strength") or 0)
                acc["strength"].append(sa == sb)
                acc["strength_within_1"].append(abs(sa - sb) <= 1)
            except Exception:
                pass
        per_pair[f"{a}|{b}"] = {k: (round(sum(v) / len(v), 3) if v else None)
                                for k, v in acc.items()}
        per_pair[f"{a}|{b}"]["n"] = len(acc["relevant"])
        for k, v in acc.items():
            fields[k].extend(v)

    overall = {k: (round(sum(v) / len(v), 3) if v else None) for k, v in fields.items()}
    overall["n_comparisons"] = len(fields["relevant"])
    return overall, per_pair


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

    overall, per_pair = agreement(results, articles)
    rec = {
        "checked": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sample": len(articles),
        "providers": sorted(results),
        "overall": overall,
        "pairwise": per_pair,
        "note": ("Agreement is a ceiling on label trustworthiness: the chain uses "
                 "whichever provider answers first, so disagreement here is noise "
                 "already present in events.json."),
    }
    hist = read_json(LLM_AGREEMENT_FILE, [])
    if not isinstance(hist, list):
        hist = [hist]
    hist.append(rec)
    hist = hist[-KEEP_RUNS:]
    write_json(LLM_AGREEMENT_FILE, hist)

    print(f"\n일치도 (비교쌍 {overall['n_comparisons']}건):")
    for k in ("relevant", "direction", "axis", "strength", "strength_within_1"):
        print(f"  {k:18s} {overall[k]}")
    print("saved:", LLM_AGREEMENT_FILE)
    L.diag_summary("check_llm_agreement")


if __name__ == "__main__":
    main()
