#!/usr/bin/env python3
"""
Turn the event ledger into something falsifiable.

The dashboard used to put two unrelated things side by side: an arithmetic
decomposition of the wiki/traffic series (the axis percentages) and an LLM
classification of news (the event list). Neither constrained the other, so the
"3-axis diagnosis" was a juxtaposition a reader mentally joined — never a
claim that could be wrong.

This script builds the bridge, and writes two files:

  data/event_pressure.json    daily signed pressure per axis — the event ledger
                              expressed as a TIME SERIES, so it lives on the
                              same axis as traffic and can actually be compared
                              to it. Discrete events and a continuous series are
                              different data types; this is the conversion.

  data/prediction_scores.json whether the ledger's predictions came true:
                              direction hit-rate, a strength->realised-move
                              calibration table, the pressure/traffic
                              correlation, a permutation test against shuffled
                              dates, and the per-axis check that demand-tagged
                              events actually track the demand series.

Each stored event is already a prediction — impact_direction says which way,
impact_strength how hard, impact_horizon how soon. Nothing ever checked them.
Scoring them turns impact_strength from an LLM opinion into an empirically
calibrated coefficient: not "the model said 4/5" but "events like this have
historically moved the proxy 3.2%".

HONESTY NOTES, because they decide how much any of this is worth:

  * Confounding. Events overlap, so a single event's "hit" is contaminated by
    everything else happening that week. Per-event hit rate is a marginal
    association, NOT an isolated causal effect. The pressure/traffic
    correlation handles overlap properly and is the more trustworthy number.

  * date_source. maintenance.py dates reconstructed most dates FROM the
    capture day. A date derived from the day we noticed something cannot also
    be evidence we foresaw it, so the foreknown subset (date_source url/llm,
    i.e. an independent witness) is reported separately. Treat that subset as
    the honest one and the rest as retrospective.

  * Power. The usable window is short. n is printed everywhere; when it is
    small the numbers are indicative, not conclusive. The permutation test is
    what stops a small-n coincidence being read as a finding.

Free, no API calls: reads data/events.json + data/wiki_series.json only.
"""
import os, sys, json, math, random
from datetime import date, timedelta

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
from llm_common import parse_date, EVENTS_FILE, EVENT_PRESSURE_FILE, PREDICTION_SCORES_FILE, WIKI_FILE, read_json, write_json

# exponential decay, and the window its prediction is scored over.
HORIZON = {
    "immediate": {"halflife": 3,  "window": 7},
    "weeks":     {"halflife": 14, "window": 28},
    "months":    {"halflife": 60, "window": 90},
}
DEFAULT_HORIZON = "weeks"
CONF_W = {"high": 1.0, "med": 0.66, "low": 0.33}
DIR_SIGN = {"+": 1.0, "-": -1.0}
AXES = ("demand", "share", "supply")

BASELINE_DAYS = 14      # window before an event, for its "before" level
# An event counts as scorable only when its whole horizon window is covered by
# the traffic series. Not 1.0: the wikipedia feed occasionally drops a day, and
# one missing day should not disqualify a finished 90-day horizon.
MIN_WINDOW_COVERAGE = 0.95
DECAY_CUTOFF = 4        # stop applying an event after this many half-lives
FWD_DAYS = 7            # forward window for the pressure/traffic correlation
PERMUTATIONS = 1000
# Competitors that make up the "market" series (Samsung excluded — it is the
# subject, not the market). Mirrors collect_wiki.py's BRANDS.
COMPETITORS = ("Apple", "Xiaomi", "vivo", "OPPO", "LG", "TCL", "Hisense",
               "Whirlpool", "Bosch")


# ---------------------------------------------------------------- utilities
def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def series_map(points):
    """[{date, views}] -> {date_obj: value}"""
    out = {}
    for p in points:
        d = parse_date(p.get("date"))
        if d is not None:
            out[d] = float(p.get("views") or 0)
    return out


def window_mean(smap, start, end):
    vals = [smap[d] for d in (start + timedelta(days=i)
                              for i in range((end - start).days + 1)) if d in smap]
    return mean(vals)


def strength_of(e):
    try:
        return max(1, min(5, int(e.get("impact_strength") or 2)))
    except Exception:
        return 2


def horizon_of(e):
    h = (e.get("impact_horizon") or "").strip().lower()
    return h if h in HORIZON else DEFAULT_HORIZON


def event_weight(e):
    """Signed magnitude an event contributes on its own day."""
    return (strength_of(e)
            * CONF_W.get((e.get("confidence") or "").lower(), 0.33)
            * DIR_SIGN.get(e.get("impact_direction"), 0.0))


def axis_of(e):
    a = (e.get("axis") or "").strip().lower()
    return a if a in AXES else ""


# ------------------------------------------------------------ pressure index
def build_pressure(events, days):
    """{axis: {date: signed pressure}} plus a combined 'all'.

    An event contributes weight * 0.5 ** (age / halflife) on every day from its
    own date onward, until DECAY_CUTOFF half-lives have passed. Nothing before
    the event date: a cause cannot act before it happens.
    """
    grid = {a: {d: 0.0 for d in days} for a in AXES + ("all",)}
    if not days:
        return grid
    last = days[-1]
    for e in events:
        d0 = parse_date(e.get("date"))
        w = event_weight(e)
        if d0 is None or w == 0.0:
            continue
        hl = HORIZON[horizon_of(e)]["halflife"]
        ax = axis_of(e)
        end = min(last, d0 + timedelta(days=hl * DECAY_CUTOFF))
        d = max(d0, days[0])
        while d <= end:
            if d in grid["all"]:
                v = w * (0.5 ** ((d - d0).days / hl))
                grid["all"][d] += v
                if ax:
                    grid[ax][d] += v
            d += timedelta(days=1)
    return grid


# --------------------------------------------------------- per-event scoring
def window_coverage(smap, start, end):
    """Fraction of the days in [start, end] the traffic series actually has."""
    n = (end - start).days + 1
    if n <= 0:
        return 0.0
    have = sum(1 for i in range(n) if (start + timedelta(days=i)) in smap)
    return have / n


def score_events(events, smap):
    """Did each event's predicted direction actually happen?

    An event is scored only once its horizon has ELAPSED. window_mean() happily
    averages whatever days exist, so the previous check ("after is not None")
    let a 90-day-horizon event from last week be graded on six days of data —
    half of everything being scored was an unfinished horizon, and the headline
    hit rate was mostly measuring events that had not had time to happen yet.
    """
    scored, skipped, unfinished = [], 0, 0
    for e in events:
        d0 = parse_date(e.get("date"))
        sign = DIR_SIGN.get(e.get("impact_direction"))
        if d0 is None or sign is None:      # neutral/unknown make no prediction
            skipped += 1
            continue
        win = HORIZON[horizon_of(e)]["window"]
        a, b = d0 + timedelta(days=1), d0 + timedelta(days=win)
        if window_coverage(smap, a, b) < MIN_WINDOW_COVERAGE:
            unfinished += 1                 # horizon still running
            continue
        before = window_mean(smap, d0 - timedelta(days=BASELINE_DAYS), d0 - timedelta(days=1))
        after = window_mean(smap, a, b)
        if not before or after is None:     # no traffic data around this date
            skipped += 1
            continue
        actual = (after - before) / before
        scored.append({
            "event_id": e.get("event_id"),
            "date": e.get("date"),
            "date_source": e.get("date_source", "seed"),
            "axis": axis_of(e),
            "predicted": e.get("impact_direction"),
            "strength": strength_of(e),
            "confidence": (e.get("confidence") or "low").lower(),
            "horizon": horizon_of(e),
            "actual_pct": round(actual * 100, 2),
            "hit": (actual > 0) == (sign > 0),
        })
    return scored, skipped, unfinished


def summarise(scored):
    """Hit rate + calibration, overall and split by date provenance."""
    def block(rows):
        if not rows:
            return {"n": 0}
        hits = sum(1 for r in rows if r["hit"])
        by_strength = {}
        for s in range(1, 6):
            sub = [r for r in rows if r["strength"] == s]
            if sub:
                by_strength[str(s)] = {
                    "n": len(sub),
                    "hit_rate": round(sum(1 for r in sub if r["hit"]) / len(sub), 3),
                    "mean_abs_move_pct": round(mean([abs(r["actual_pct"]) for r in sub]), 2),
                }
        by_conf = {}
        for c in ("high", "med", "low"):
            sub = [r for r in rows if r["confidence"] == c]
            if sub:
                by_conf[c] = {"n": len(sub),
                              "hit_rate": round(sum(1 for r in sub if r["hit"]) / len(sub), 3)}
        return {
            "n": len(rows),
            "hit_rate": round(hits / len(rows), 3),
            "mean_abs_move_pct": round(mean([abs(r["actual_pct"]) for r in rows]), 2),
            "by_strength": by_strength,
            "by_confidence": by_conf,
        }

    # "foreknown" = the date came from an independent witness (a publish date in
    # the URL, or an LLM date we had no reason to override), not from the day we
    # happened to notice. Only these can support a claim of foresight.
    foreknown = [r for r in scored if r["date_source"] in ("url", "llm", "seed")]
    return {
        "all": block(scored),
        "foreknown": block(foreknown),
        "retrospective": block([r for r in scored if r["date_source"] == "capture"]),
        "by_axis": {a: block([r for r in scored if r["axis"] == a]) for a in AXES},
    }


# ----------------------------------------------------- correlation + null test
def forward_change(smap, days):
    """{date: pct change of the next FWD_DAYS vs the trailing FWD_DAYS}."""
    out = {}
    for d in days:
        prev = window_mean(smap, d - timedelta(days=FWD_DAYS - 1), d)
        nxt = window_mean(smap, d + timedelta(days=1), d + timedelta(days=FWD_DAYS))
        if prev and nxt is not None:
            out[d] = (nxt - prev) / prev
    return out


def dense_window_start(events, days, min_per_month=20):
    """First day of the stretch where the ledger is actually populated.

    Walks months backward from the end and stops at the first one holding
    fewer than `min_per_month` events. Everything before that is sparse
    hand-seeded history that would dilute any correlation to zero.
    """
    from collections import Counter
    per = Counter((e.get("date") or "")[:7] for e in events)
    months = sorted({d.isoformat()[:7] for d in days})
    keep = []
    for m in reversed(months):
        if per.get(m, 0) < min_per_month:
            break
        keep.append(m)
    if not keep:
        return None
    first = min(keep)
    return min(d for d in days if d.isoformat()[:7] == first)


def correlate(pressure_by_day, fwd, days):
    xs, ys = [], []
    for d in days:
        if d in fwd:
            xs.append(pressure_by_day.get(d, 0.0))
            ys.append(fwd[d])
    return pearson(xs, ys), len(xs)


def permutation_test(events, days, targets, observed, n=PERMUTATIONS, seed=20260810):
    """Could a random ledger explain the traffic just as well?

    Shuffling event dates over the same span preserves every other property of
    the ledger — how many events, their strengths, horizons and directions —
    and destroys only the timing. If the real ledger does not beat the shuffled
    ones, the correlation is an artefact of volume, not of timing.

    This is the right test here rather than a t-test on r: both the pressure
    index and the forward-change series are heavily smoothed, so daily
    observations are strongly autocorrelated and a naive t-test would be wildly
    overconfident. Shuffling preserves that structure in the traffic series and
    destroys it only in the ledger.

    `targets` maps a key ("all"/"demand"/...) to its forward-change series, so
    every axis is tested against the SAME shuffles in one pass.
    """
    if not days or len(days) < 10:
        return None
    rng = random.Random(seed)
    nulls = {k: [] for k in targets}
    for _ in range(n):
        shuffled = []
        for e in events:
            c = dict(e)
            c["date"] = rng.choice(days).isoformat()
            shuffled.append(c)
        grid = build_pressure(shuffled, days)
        for k, fwd_k in targets.items():
            r, _ = correlate(grid[k], fwd_k, days)
            if r is not None:
                nulls[k].append(r)
    out = {}
    for k, null in nulls.items():
        obs = observed.get(k)
        if not null or obs is None:
            out[k] = None
            continue
        beat = sum(1 for x in null if abs(x) >= abs(obs))
        p = beat / len(null)
        out[k] = {
            "permutations": len(null),
            "observed_r": round(obs, 4),
            "null_p95_abs_r": round(sorted(abs(x) for x in null)[int(len(null) * 0.95)], 4),
            "p_value": round(p, 4),
            "significant": p < 0.05,
        }
    return out


# ------------------------------------------------------------------- driver
def main():
    events = read_json(EVENTS_FILE, [])
    wiki = read_json(WIKI_FILE, {}).get("series", {})
    samsung = series_map(wiki.get("Samsung", []))
    if not samsung:
        print("wiki Samsung series empty — nothing to score against")
        return

    # Market = summed competitor attention, on days where every brand reported.
    comp_maps = [series_map(wiki.get(b, [])) for b in COMPETITORS]
    comp_maps = [m for m in comp_maps if m]
    market = {}
    for d in samsung:
        vals = [m[d] for m in comp_maps if d in m]
        if len(vals) == len(comp_maps) and vals:
            market[d] = sum(vals)

    ev_dates = [d for d in (parse_date(e.get("date")) for e in events) if d]
    if not ev_dates:
        print("no dated events")
        return
    # Only the span where events and the series overlap: before the first event
    # pressure is identically zero and would swamp any correlation.
    start = max(min(ev_dates), min(samsung))
    end = min(max(samsung), max(ev_dates))
    if end <= start:
        print("event window and wiki series do not overlap")
        return
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    # The ledger is not uniformly populated: daily collection only began in
    # mid-2026, so ~85% of the span carries a handful of hand-seeded events and
    # the last stretch carries hundreds. Correlating across the whole span
    # measures mostly empty days and is guaranteed to return ~0 whatever the
    # truth is. So report BOTH: the full span, and the dense window where the
    # ledger is actually active (the headline number).
    dense_start = dense_window_start(events, days)
    dense_days = [d for d in days if d >= dense_start] if dense_start else days

    grid = build_pressure(events, days)
    fwd = forward_change(samsung, days)
    r_full, n_full = correlate(grid["all"], fwd, days)
    r_all, n_pairs = correlate(grid["all"], fwd, dense_days)

    # Axis validation: do demand-tagged events track the MARKET series, and
    # share-tagged events track Samsung's share of it? If not, the axis labels
    # are decorative and the axis split means nothing.
    share = {d: samsung[d] / (samsung[d] + market[d])
             for d in market if (samsung[d] + market[d])}
    axis_checks, targets, observed = {}, {"all": fwd}, {"all": r_all}
    for ax, target in (("demand", market), ("share", share), ("supply", samsung)):
        if not target:
            continue
        f = forward_change(target, days)
        r, n = correlate(grid[ax], f, dense_days)
        axis_checks[ax] = {"r": None if r is None else round(r, 4), "n": n,
                           "target": {"demand": "market_total",
                                      "share": "samsung_share",
                                      "supply": "samsung"}[ax]}
        targets[ax], observed[ax] = f, r

    scored, skipped, unfinished = score_events(events, samsung)
    perm = permutation_test(events, dense_days, targets, observed)

    write_json(EVENT_PRESSURE_FILE, {
        "updated": date.today().isoformat(),
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": len(days)},
        "halflife_days": {k: v["halflife"] for k, v in HORIZON.items()},
        "series": {a: [{"date": d.isoformat(), "p": round(grid[a][d], 3)} for d in days]
                   for a in AXES + ("all",)},
    }, indent=None)   # 4 axes x ~660 days

    write_json(PREDICTION_SCORES_FILE, {
        "updated": date.today().isoformat(),
        "window": {"from": start.isoformat(), "to": end.isoformat(), "days": len(days)},
        "proxy": "wikipedia_samsung_pageviews",
        "scored": len(scored),
        "skipped": skipped,
        # Horizon still running — not a failure, just not gradeable yet. Split
        # out from `skipped` so a small `scored` reads as "too early" rather
        # than "the data is broken".
        "unfinished_horizon": unfinished,
        "summary": summarise(scored),
        "correlation": {
            "pressure_vs_forward_traffic_r": None if r_all is None else round(r_all, 4),
            "n_days": n_pairs, "forward_days": FWD_DAYS,
            "dense_window_from": dense_start.isoformat() if dense_start else None,
            "full_window_r": None if r_full is None else round(r_full, 4),
            "full_window_n_days": n_full,
        },
        "axis_validation": axis_checks,
        "permutation": perm,  # keyed by all/demand/share/supply
        # Korean: these render directly in the dashboard (UI language is Korean).
        "caveats": [
            "이벤트가 서로 겹치므로 개별 적중률은 '연관'이지 그 이벤트만의 효과가 아닙니다.",
            "'수집일 추정' 날짜는 기사에서 날짜를 얻지 못해 수집한 날로 채운 값이라, 미리 알았다는 근거가 될 수 없습니다.",
            "위키피디아 조회수는 samsung.com 트래픽의 대리지표이며, 그 대리 관계 자체는 아직 검증되지 않았습니다.",
            "일별 관측은 자기상관이 강해 일반 유의성 검정은 과신합니다 — 순열검정 p값을 기준으로 보세요.",
        ],
    })

    s = summarise(scored)
    print(f"window {start} ~ {end} ({len(days)}일), 채점 {len(scored)}건 / "
          f"제외 {skipped}건 / horizon 진행중 {unfinished}건")
    print(f"  방향 적중률  전체 {s['all'].get('hit_rate')} (n={s['all'].get('n')})"
          f"  |  사전근거 {s['foreknown'].get('hit_rate')} (n={s['foreknown'].get('n')})")
    print(f"  압력지수 vs 향후{FWD_DAYS}일 트래픽")
    print(f"    조밀구간({dense_start} ~) r = {r_all if r_all is None else round(r_all,4)} (n={n_pairs}일)  ← 대표값")
    print(f"    전체구간            r = {r_full if r_full is None else round(r_full,4)} (n={n_full}일)")
    pa = (perm or {}).get("all")
    if pa:
        print(f"    순열검정 p = {pa['p_value']} (귀무 |r| 95%={pa['null_p95_abs_r']}, "
              f"{pa['permutations']}회) → {'유의' if pa['significant'] else '유의하지 않음'}")
    print("  축 검증 (해당 축 압력 vs 그 축이 대변해야 할 계열):")
    for ax, c in axis_checks.items():
        pp = (perm or {}).get(ax) or {}
        verdict = "유의" if pp.get("significant") else "유의하지 않음"
        print(f"    {ax:7s} vs {c['target']:14s} r = {c['r']:>7} (n={c['n']})  "
              f"p = {pp.get('p_value','-')}  {verdict}")
    print("saved:", EVENT_PRESSURE_FILE, PREDICTION_SCORES_FILE)


if __name__ == "__main__":
    main()
