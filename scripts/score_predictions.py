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


def calibrate_strength(scored, ev_by_id):
    """조정강도 — where each event's traffic move ranks among all of them.

    The strength label is a prediction of HOW FAR traffic moves. Once a horizon
    elapses the move is known, so the label has an observed counterpart, cut
    into fifths so it lands on the same 1-5 scale.

    What this is NOT is that event's own effect, and an earlier version of this
    function claimed otherwise. It grouped events by exact (date, horizon) and
    called the ones whose group agreed on direction "attributable", reporting
    the rest as unattributable — which read as "the remaining ones are clean".
    They were not. Effect windows run 7, 28 or 90 days, so an event dated weeks
    earlier is still pushing during this one's window, and grouping on an exact
    date never saw it. Checked against real overlap, every single event in that
    "clean" set had opposite-direction events live inside its window.

    With ~16 events arriving a day and windows up to 90 days long, dozens are
    always in flight at once, and one traffic series cannot be divided among
    them. So the filter is gone — every scored event gets a 조정강도 — and
    `opposing_overlap` carries the honest caveat instead: how many
    opposite-direction events were live during this one's window. Read the
    number as "traffic moved this much around this event", never as "this event
    moved traffic this much".

    The value never overwrites impact_strength. That field is the prediction,
    and this file exists to check predictions against outcomes; deriving one
    from the other would make the check circular.
    """
    if len(scored) < 10:
        return {"n": len(scored), "note": "표본 부족 — 아직 교정할 수 없습니다."}

    moves = sorted(abs(r["actual_pct"]) for r in scored)
    # 4 internal cuts -> 5 buckets of equal count
    cuts = [moves[int(len(moves) * q)] for q in (0.2, 0.4, 0.6, 0.8)]

    def bucket(pct):
        a = abs(pct)
        return 1 + sum(1 for c in cuts if a >= c)

    # Real effect windows, so overlap is measured on when events were actually
    # in flight rather than on whether two share a calendar date.
    spans = {}
    for r in scored:
        d0 = parse_date(r["date"])
        if d0 is None:
            continue
        w = HORIZON[r["horizon"]]["window"]
        spans[r["event_id"]] = (d0 + timedelta(days=1), d0 + timedelta(days=w))

    def opposing(r):
        me = spans.get(r["event_id"])
        if not me:
            return 0
        a, b = me
        n = 0
        for x in scored:
            if x["event_id"] == r["event_id"] or x["predicted"] == r["predicted"]:
                continue
            other = spans.get(x["event_id"])
            if other and other[0] <= b and other[1] >= a:
                n += 1
        return n

    per_event, table, overlaps = {}, {}, []
    for r in scored:
        obs = bucket(r["actual_pct"])
        opp = opposing(r)
        overlaps.append(opp)
        per_event[r["event_id"]] = {
            "predicted": r["strength"], "observed": obs,
            "actual_pct": r["actual_pct"], "hit": r["hit"],
            # How many opposite-direction events were live in this window.
            "opposing_overlap": opp,
        }
        table.setdefault(r["strength"], []).append(obs)

    # Convergence: how far the LLM's strength sat from the 조정강도, and how far
    # a shuffled label would have sat. Without the shuffled baseline a gap of
    # 1.45 looks like "close enough" when it is in fact worse than guessing.
    gaps = [abs(v["predicted"] - v["observed"]) for v in per_event.values()]
    shuffled = sorted(v["observed"] for v in per_event.values())
    preds = sorted(v["predicted"] for v in per_event.values())
    # Expected |p-o| if the two were unrelated: average over all pairings.
    rand_gap = sum(abs(p - o) for p in preds for o in shuffled) / (len(preds) * len(shuffled))
    by_ver, by_month = {}, {}
    for eid, v in per_event.items():
        e = ev_by_id.get(eid, {})
        g = abs(v["predicted"] - v["observed"])
        by_ver.setdefault(str(e.get("prompt_version") or 1), []).append(g)
        by_month.setdefault((e.get("date") or "")[:7], []).append(g)

    calib = {}
    for pred in sorted(table):
        obs = sorted(table[pred])
        calib[str(pred)] = {
            "n": len(obs),
            "observed_median": obs[len(obs) // 2],
            "observed_mean": round(sum(obs) / len(obs), 2),
            # What this predicted value should be read as, given history.
            "suggested": obs[len(obs) // 2],
        }
    ov = sorted(overlaps)
    return {
        "n": len(scored),
        "overlap": {
            "median": ov[len(ov) // 2],
            "max": ov[-1],
            # Events with no opposing force in flight — the only ones whose move
            # could be read as their own. Currently this is essentially none.
            "isolated": sum(1 for o in ov if o == 0),
        },
        "convergence": {
            "mean_gap": round(sum(gaps) / len(gaps), 3),
            "random_gap": round(rand_gap, 3),
            # Below random_gap means the label carries information about magnitude.
            "informative": (sum(gaps) / len(gaps)) < rand_gap,
            "exact_match_rate": round(sum(1 for g in gaps if g == 0) / len(gaps), 3),
            "by_prompt_version": {k: {"n": len(v), "mean_gap": round(sum(v) / len(v), 3)}
                                  for k, v in sorted(by_ver.items())},
            "by_month": {k: {"n": len(v), "mean_gap": round(sum(v) / len(v), 3)}
                         for k, v in sorted(by_month.items()) if k and len(v) >= 3},
        },
        "bucket_cuts_pct": [round(c, 2) for c in cuts],
        "by_predicted": calib,
        "per_event": per_event,
        "note": ("조정강도는 horizon 경과 후 트래픽 변화폭을 5분위로 자른 값입니다. "
                 "그 사건 하나의 효과가 아니라 '그 무렵 트래픽이 이만큼 움직였다'는 "
                 "뜻이며, 같은 구간에 반대 방향 이벤트가 몇 건 살아 있었는지는 "
                 "opposing_overlap에 있습니다. 저장된 impact_strength는 덮어쓰지 "
                 "않습니다 — 예측과 결과를 나란히 두어야 예측을 검증할 수 있습니다."),
    }


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


# ------------------------------------------------------- group attribution
# Events grouped by axis x direction, fitted JOINTLY against the traffic curve.
#
# Why joint rather than the before/after read used for 조정강도: with dozens of
# events live at once, a before/after window around one of them measures the
# sum of everything in flight. A joint fit instead asks "what per-group weights
# make the sum of all decayed contributions reproduce the actual curve", so the
# groups compete to explain the same movement and each one's share is an output
# rather than a relabelling of the movement itself.
#
# Why groups and not events: 47 days of dense traffic against 375 events is 8
# unknowns per observation, and any allocation fits equally well. Collapsing to
# a handful of groups makes the system solvable.
GROUPS = [("demand", "+"), ("demand", "-"), ("share", "+"), ("share", "-"), ("supply", None)]
GROUP_KO = {("demand", "+"): "수요↑", ("demand", "-"): "수요↓",
            ("share", "+"): "점유↑", ("share", "-"): "점유↓",
            ("supply", None): "공급"}
# Half-lives the search may choose from, in days. Coarse on purpose: the data
# cannot separate 20 from 22, and a fine grid would only invite overfitting.
HALFLIFE_GRID = [2, 3, 5, 7, 10, 14, 21, 30, 45, 60, 90]


def group_of(e):
    ax = axis_of(e)
    d = e.get("impact_direction")
    if ax == "supply":
        return ("supply", None)
    return (ax, d) if d in ("+", "-") else None


def _solve(ata, atb):
    """Gaussian elimination with partial pivoting. n is 6 at most."""
    n = len(atb)
    m = [row[:] + [atb[i]] for i, row in enumerate(ata)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            return None
        m[c], m[p] = m[p], m[c]
        pv = m[c][c]
        for r in range(n):
            if r == c:
                continue
            f = m[r][c] / pv
            for k in range(c, n + 1):
                m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def _design(events, days, halflives):
    """One decayed-exposure column per group, plus an intercept."""
    cols = []
    for g in GROUPS:
        hl = halflives[g]
        col = []
        members = [e for e in events if group_of(e) == g]
        dated = [(parse_date(e.get("date")), strength_of(e) * CONF_W.get(
            (e.get("confidence") or "low").lower(), 0.33)) for e in members]
        dated = [(d, w) for d, w in dated if d is not None]
        for t in days:
            s = 0.0
            for d0, w in dated:
                age = (t - d0).days
                if 0 <= age <= hl * DECAY_CUTOFF:
                    s += w * (0.5 ** (age / hl))
            col.append(s)
        cols.append(col)
    cols.append([1.0] * len(days))     # intercept
    return cols


def _lstsq(cols, y):
    n = len(cols)
    ata = [[sum(a * b for a, b in zip(cols[i], cols[j])) for j in range(n)] for i in range(n)]
    atb = [sum(a * b for a, b in zip(cols[i], y)) for i in range(n)]
    return _solve(ata, atb)


def _sse(cols, y, beta):
    tot = 0.0
    for k in range(len(y)):
        pred = sum(beta[i] * cols[i][k] for i in range(len(cols)))
        tot += (y[k] - pred) ** 2
    return tot


def fit_groups(events, smap, days, max_passes=3):
    """Coordinate descent over the half-life grid, least squares inside.

    A separate half-life per group is a 5-dimensional grid; searching it whole
    would be 11^5 fits. Tuning one group at a time and repeating converges in a
    few passes at a fraction of the cost.
    """
    days = [d for d in days if d in smap]
    if len(days) < 20:
        return None
    y = [math.log(smap[d]) for d in days if smap[d] > 0]
    days = [d for d in days if smap[d] > 0]
    if len(days) != len(y) or len(y) < 20:
        return None

    halflives = {g: 14 for g in GROUPS}
    cols = _design(events, days, halflives)
    beta = _lstsq(cols, y)
    if beta is None:
        return None
    best = _sse(cols, y, beta)
    for _ in range(max_passes):
        moved = False
        for g in GROUPS:
            cur = halflives[g]
            for hl in HALFLIFE_GRID:
                if hl == cur:
                    continue
                trial = dict(halflives); trial[g] = hl
                c2 = _design(events, days, trial)
                b2 = _lstsq(c2, y)
                if b2 is None:
                    continue
                s2 = _sse(c2, y, b2)
                if s2 < best - 1e-9:
                    best, halflives, cols, beta, moved = s2, trial, c2, b2, True
        if not moved:
            break

    ss_tot = sum((v - (sum(y) / len(y))) ** 2 for v in y)
    return {"days": days, "y": y, "cols": cols, "beta": beta,
            "halflives": halflives, "r2": (1 - best / ss_tot) if ss_tot else None}


RIDGE_LAMBDA = 10.0     # heavy on purpose; see group_attribution
MIN_TRAIN_WEEKS = 20


def _ridge(cols, y, lam):
    n = len(cols)
    ata = [[sum(a * b for a, b in zip(cols[i], cols[j])) for j in range(n)] for i in range(n)]
    for i in range(n):
        ata[i][i] += lam
    return _solve(ata, [sum(a * b for a, b in zip(cols[i], y)) for i in range(n)])


def _weekly(events, days, smap, halflives):
    """Weekly means of log traffic and of each group's exposure.

    Daily deltas in wikipedia pageviews are almost entirely noise — weekday
    shape and random spikes — and nothing predicts them. Weeks are also how the
    dashboard is actually read, so this is both the fairer and the more
    relevant grain.
    """
    cols = _design(events, days, halflives)[:-1]     # drop the intercept
    buckets = {}
    for i, d in enumerate(days):
        buckets.setdefault(d.isocalendar()[:2], []).append(i)
    wk = sorted(buckets)
    y = [math.log(sum(smap[days[i]] for i in buckets[w]) / len(buckets[w])) for w in wk]
    x = [[sum(c[i] for i in buckets[w]) / len(buckets[w]) for w in wk] for c in cols]
    return x, y


def _diff(v):
    return [v[i] - v[i - 1] for i in range(1, len(v))]


def rolling_origin(events, smap, days, halflives, lam=RIDGE_LAMBDA):
    """Predict each week from only the weeks before it, and score the lot.

    Two corrections over a single chronological split, both of which were
    making the previous number meaningless:

    * LEVEL. Fitting log traffic with a constant intercept scores any drift in
      the overall level as model error. An intercept-only model — no events at
      all — already scored r2_out -0.79 on the dense window and -11.23 on the
      full one, so the reported -5.87 was mostly measuring drift rather than
      anything about events. Working in week-over-week differences removes the
      level, which is also the quantity the dashboard asks about.

    * SPLIT. One 70/30 cut leaves ~10 test weeks, and which 10 decides the
      answer: that split reads +0.070 where rolling origin over 73 test weeks
      reads -0.12. Refitting each week and testing on the next uses every week
      as a test point, so the estimate stops depending on where the cut fell.
    """
    days = [d for d in days if d in smap and smap[d] > 0]
    x, y = _weekly(events, days, smap, halflives)
    dy, dx = _diff(y), [_diff(c) for c in x]
    preds, acts = [], []
    for t in range(MIN_TRAIN_WEEKS, len(dy)):
        beta = _ridge([c[:t] for c in dx], dy[:t], lam)
        if beta is None:
            continue
        preds.append(sum(beta[i] * dx[i][t] for i in range(len(dx))))
        acts.append(dy[t])
    if len(acts) < 8:
        return None
    m = sum(acts) / len(acts)
    sse = sum((a - p) ** 2 for a, p in zip(acts, preds))
    sst = sum((a - m) ** 2 for a in acts)
    return {"test_weeks": len(acts), "ridge_lambda": lam,
            "r2_out": round(1 - sse / sst, 4) if sst else None}


def group_attribution(events, smap, days, all_days=None):
    """Group shares over the fitted window, and whether they may be used.

    The shares come from a fit over `days`. Whether anyone may read them comes
    from rolling_origin over the FULL history — a fit always explains the days
    it was tuned on, so r2_in is not evidence, and the shares stay locked until
    the same model earns a positive score on weeks it never saw.
    """
    full = fit_groups(events, smap, days)
    if not full:
        return None
    oos = rolling_origin(events, smap, sorted(all_days or smap), full["halflives"])

    contrib, total = {}, 0.0
    for i, g in enumerate(GROUPS):
        c = full["beta"][i] * (sum(full["cols"][i]) / len(full["days"]))
        contrib[g] = c
        total += abs(c)
    shares = {GROUP_KO[g]: {
        "coefficient": round(full["beta"][i], 5),
        "halflife_days": full["halflives"][g],
        "share_pct": round(abs(contrib[g]) / total * 100, 1) if total else None,
        "signed_effect": round(contrib[g], 5),
        "n_events": sum(1 for e in events if group_of(e) == g),
    } for i, g in enumerate(GROUPS)}

    r2o = (oos or {}).get("r2_out")
    usable = r2o is not None and r2o > 0
    return {
        "window": {"from": full["days"][0].isoformat(),
                   "to": full["days"][-1].isoformat(), "days": len(full["days"])},
        "r2_in": round(full["r2"], 4) if full["r2"] is not None else None,
        "out_of_sample": oos,
        "usable": usable,
        "verdict": ("검증에서도 설명력이 있어 배분을 신뢰할 수 있습니다."
                    if usable else
                    "학습에 쓰지 않은 주에서 설명력이 0 이하입니다 — 이 배분은 아직 쓰지 않습니다."),
        "groups": shares,
        "note": ("그룹 계수와 반감기는 트래픽 곡선에 맞춘 값입니다. r2_in은 맞춘 "
                 "구간이라 항상 높게 나오므로, 판단 기준은 주 단위 전주 대비 변화를 "
                 "롤링 오리진으로 검정한 r2_out입니다."),
    }


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
    groups = group_attribution(events, samsung, dense_days, all_days=days)
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
        "strength_calibration": calibrate_strength(scored, {e.get("event_id"): e for e in events}),
        "correlation": {
            "pressure_vs_forward_traffic_r": None if r_all is None else round(r_all, 4),
            "n_days": n_pairs, "forward_days": FWD_DAYS,
            "dense_window_from": dense_start.isoformat() if dense_start else None,
            "full_window_r": None if r_full is None else round(r_full, 4),
            "full_window_n_days": n_full,
        },
        "axis_validation": axis_checks,
        "group_attribution": groups,
        "permutation": perm,  # keyed by all/demand/share/supply
        # Korean: these render directly in the dashboard (UI language is Korean).
        "caveats": [
            "이벤트가 서로 겹치므로 개별 적중률은 '연관'이지 그 이벤트만의 효과가 아닙니다.",
            "'수집일 추정' 날짜는 기사에서 날짜를 얻지 못해 수집한 날로 채운 값이라, 미리 알았다는 근거가 될 수 없습니다.",
            "위키피디아 조회수는 samsung.com 트래픽의 대리지표이며, 그 대리 관계 자체는 아직 검증되지 않았습니다.",
            "일별 관측은 자기상관이 강해 일반 유의성 검정은 과신합니다 — 순열검정 p값을 기준으로 삼아야 합니다.",
            "조정강도는 사후 결과일 뿐 예측이 아닙니다. 저장된 impact_strength는 그대로 두고 나란히 보여줍니다.",
            "조정강도는 그 사건 하나의 효과가 아니라 '그 무렵 트래픽이 이만큼 움직였다'는 값입니다 — 영향 구간이 겹치는 이벤트가 항상 수십 건이라 트래픽 한 계열을 개별 사건 몫으로 나눌 수 없습니다.",
        ],
    })

    s = summarise(scored)
    print(f"window {start} ~ {end} ({len(days)}일), 채점 {len(scored)}건 / "
          f"제외 {skipped}건 / horizon 진행중 {unfinished}건")
    print(f"  방향 적중률  전체 {s['all'].get('hit_rate')} (n={s['all'].get('n')})"
          f"  |  사전근거 {s['foreknown'].get('hit_rate')} (n={s['foreknown'].get('n')})")
    print(f"  누적 영향지수 vs 향후{FWD_DAYS}일 트래픽")
    print(f"    조밀구간({dense_start} ~) r = {r_all if r_all is None else round(r_all,4)} (n={n_pairs}일)  ← 대표값")
    print(f"    전체구간            r = {r_full if r_full is None else round(r_full,4)} (n={n_full}일)")
    if groups:
        oo = groups.get("out_of_sample") or {}
        print(f"  그룹 배분 (축x방향 {len(groups['groups'])}개)")
        print(f"    맞춘 구간 r2_in = {groups['r2_in']}  |  검증 구간 r2_out = {oo.get('r2_out')}"
              f"  -> {'사용 가능' if groups['usable'] else '아직 사용 불가(과적합)'}")
        for k, v in groups["groups"].items():
            print(f"      {k:5s} {v['n_events']:3d}건  반감기 {v['halflife_days']:2d}일  "
                  f"비중 {v['share_pct']}%  효과 {v['signed_effect']:+.4f}")
    pa = (perm or {}).get("all")
    if pa:
        print(f"    순열검정 p = {pa['p_value']} (귀무 |r| 95%={pa['null_p95_abs_r']}, "
              f"{pa['permutations']}회) → {'유의' if pa['significant'] else '유의하지 않음'}")
    print("  축 검증 (해당 축 지수 vs 그 축이 대변해야 할 계열):")
    for ax, c in axis_checks.items():
        pp = (perm or {}).get(ax) or {}
        verdict = "유의" if pp.get("significant") else "유의하지 않음"
        print(f"    {ax:7s} vs {c['target']:14s} r = {c['r']:>7} (n={c['n']})  "
              f"p = {pp.get('p_value','-')}  {verdict}")
    print("saved:", EVENT_PRESSURE_FILE, PREDICTION_SCORES_FILE)


if __name__ == "__main__":
    main()
