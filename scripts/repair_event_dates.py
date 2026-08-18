#!/usr/bin/env python3
"""
One-off repair — fix event dates corrupted by the missing date anchor.

WHY
  Until 2026-08-10 the judgement prompt never told the model what day it was,
  and the collectors accepted its answer on a bare regex. With no clock the
  model anchored extracted dates to its training era: 291 of 325 auto-collected
  events (90%) were stored with a `date` more than a YEAR before the day they
  were captured. An article about the Galaxy Z Fold 8 fetched 2026-08-04 was
  filed under 2024-08-22; an Apple Watch Series 11 piece under 2024-09-01.
  Five rows were not even real dates ("2024-05-00" — day 00 passes the regex).

  Every period filter, the trend chart and the whole 3-axis attribution key off
  `date`, so the dashboard was reading the wrong two years of history.

  llm_common.clean_date() + the TODAY'S DATE line in the prompt stop this
  happening again. This script repairs what is already stored.

WHAT IT DOES  (auto-collected events only — `A…`/`FP…` ids)
  1. If raw_url carries a publish date (…/2026/08/01/…) and it is plausible,
     use it. Highest fidelity: an independent witness.
  2. Else if the stored date is implausible for a pipeline that only ever reads
     the last 24h of news — more than REPAIR_THRESHOLD days before capture —
     fall back to captured_date. Collectors run daily, so capture is within a
     day or two of publication.
  3. Else leave it alone: a modest backdate is a legitimate phenomenon-start
     date (a report published in Q3 about Q2 shipments).

  Hand-curated seed events (E1xx) are never touched — their dates were entered
  by a human and are correct.

  event_id for news events is md5(title + date), so a repaired date would
  change the id. Ids are NOT recomputed: they are referenced by feed_state and
  would break dedup against already-seen items. The id is an opaque key, not a
  date source.

USAGE
  python3 scripts/repair_event_dates.py --dry-run   # report only (default)
  python3 scripts/repair_event_dates.py --apply     # rewrite data/events.json
"""
import os, sys, json, re, argparse
from datetime import date

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
from llm_common import parse_date  # strict ISO parse; rejects "2024-05-00"

DATA = os.path.join(HERE, "..", "data", "events.json")

# A stored date more than this many days before capture cannot have come from a
# last-24h news pipeline. Deliberately generous: quarterly-report events
# legitimately lag their article by a couple of months, and the corruption we
# are hunting sits >365 days out, so 180 separates them cleanly.
REPAIR_THRESHOLD = 180
# A URL-derived date is only believed if it lands within this window of capture.
URL_PLAUSIBLE_DAYS = 120

_URL_PATTERNS = [
    re.compile(r"/(20\d{2})/(\d{1,2})/(\d{1,2})(?:/|[-_.])"),   # /2026/08/01/
    re.compile(r"[-_](20\d{2})(\d{2})(\d{2})[-_.]"),            # -20260801.
    re.compile(r"/(20\d{2})/(\d{1,2})/"),                       # /2026/08/
]


def url_date(url):
    """Publish date embedded in an article URL, or None."""
    for pat in _URL_PATTERNS:
        m = pat.search(url or "")
        if not m:
            continue
        g = m.groups()
        try:
            return date(int(g[0]), int(g[1]), int(g[2]) if len(g) > 2 else 1)
        except ValueError:
            continue          # e.g. month 13 — keep trying the other patterns
    return None


def infer_source(e):
    """Reconstruct `date_source` for an event stored before the collectors
    recorded it, by replaying llm_common.clean_date()'s decision.

    The collectors validated dates from 2026-08-10 but did not save WHERE the
    surviving date came from until 2026-08-18, so ~78 auto-collected events
    carry no provenance. Both the dashboard badge and score_predictions.py
    default a missing value to "seed", which reads as a hand-entered date and
    puts the row in the foreknown bucket — the one place a capture-derived
    date must never appear. clean_date() is deterministic given the stored
    inputs, so its decision can be recovered exactly:

      raw_date parses  -> it was the only fallback offered; date == raw_date
                          means the fallback was taken ('url'), anything else
                          means the model's date survived ('llm').
      raw_date missing -> the fallback was the capture day; date ==
                          captured_date means it was taken ('capture').

    A publish date embedded in raw_url outranks both — it is an independent
    witness, which is what 'url' meant when this script first ran.
    """
    cur = parse_date(e.get("date"))
    pub = parse_date(e.get("raw_date"))
    cap = parse_date(e.get("captured_date"))
    ud = url_date(e.get("raw_url"))
    if not cur:
        return "capture"
    if ud and ud == cur:
        return "url"
    if pub:
        return "url" if cur == pub else "llm"
    if cap and cur == cap:
        return "capture"
    return "llm"


def repair(events, threshold=REPAIR_THRESHOLD):
    """Return (changes, stats). changes = [(event, old, new, reason)]."""
    changes, stats = [], {"seed_skipped": 0, "ok": 0,
                          "from_url": 0, "from_capture": 0, "unfixable": 0}
    for e in events:
        if str(e.get("event_id", ""))[:1] not in ("A", "F"):
            stats["seed_skipped"] += 1
            continue
        cap = parse_date(e.get("captured_date"))
        cur = parse_date(e.get("date"))
        if cap is None:                      # nothing to anchor against
            stats["unfixable"] += 1
            e.setdefault("date_source", infer_source(e))
            continue

        ud = url_date(e.get("raw_url"))
        if ud and ud <= cap and (cap - ud).days <= URL_PLAUSIBLE_DAYS:
            if ud != cur:
                changes.append((e, e.get("date"), ud.isoformat(), "url"))
                stats["from_url"] += 1
            else:
                stats["ok"] += 1
                e.setdefault("date_source", infer_source(e))
            continue

        if cur is None or (cap - cur).days > threshold or cur > cap:
            changes.append((e, e.get("date"), cap.isoformat(), "capture"))
            stats["from_capture"] += 1
        else:
            stats["ok"] += 1
            e.setdefault("date_source", infer_source(e))
    return changes, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the repaired file")
    ap.add_argument("--threshold", type=int, default=REPAIR_THRESHOLD)
    args = ap.parse_args()

    events = json.load(open(DATA, encoding="utf-8"))
    missing = [e for e in events
               if str(e.get("event_id", ""))[:1] in ("A", "F")
               and not e.get("date_source")]
    changes, stats = repair(events, args.threshold)

    print(f"events {len(events)}건 — 시드 {stats['seed_skipped']} 제외, "
          f"정상 {stats['ok']}, 수정대상 {len(changes)} "
          f"(URL근거 {stats['from_url']}, 수집일근거 {stats['from_capture']}), "
          f"복구불가 {stats['unfixable']}")

    if missing:
        from collections import Counter
        c = Counter(e.get("date_source", "?") for e in missing)
        print(f"date_source 없던 자동수집 {len(missing)}건 → "
              + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))

    if changes:
        print("\n표본 10건:")
        for e, old, new, why in changes[:10]:
            print(f"  {old} → {new}  [{why}]  {(e.get('raw_title') or e.get('title',''))[:52]}")
        span = sorted(n for _, _, n, _ in changes)
        print(f"\n수정 후 날짜 범위: {span[0]} ~ {span[-1]}")

    if not args.apply:
        print("\n(dry-run — 실제 저장하려면 --apply)")
        return

    for e, _old, new, why in changes:
        e["date"] = new
        # Provenance matters for the credibility work: a date we set FROM the
        # capture day cannot also be used to claim we foresaw that day's
        # traffic. score_predictions.py reads this to separate genuine
        # foreknowledge from dates that are merely the day we noticed.
        e["date_source"] = why
    events.sort(key=lambda x: x.get("date", ""))
    # Repair can collapse two events onto the same (date, title); events.json's
    # integrity check forbids that, so drop the later duplicate.
    seen, deduped = set(), []
    for e in events:
        key = (e.get("date", ""), e.get("title", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)
    dropped = len(events) - len(deduped)
    json.dump(deduped, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n저장 완료: date_source {len(missing)}건 보강, {len(changes)}건 수정, 중복 {dropped}건 제거, 최종 {len(deduped)}건")


if __name__ == "__main__":
    main()
