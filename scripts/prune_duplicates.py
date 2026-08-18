#!/usr/bin/env python3
"""
One-off cleanup — remove events that are near-duplicates of an earlier one.

WHY
  Twelve feeds, NewsAPI and the GDELT pool all cover the same story. Until
  2026-08-18 nothing caught that: dedup keyed on event_id (md5 of the title)
  and on (title, date), so a different headline made a different event. The
  collectors now refuse such writes (llm_common.DupIndex, CLAUDE.md 원칙 9);
  this removes what was already stored under the old behaviour.

HOW
  Replays every event through DupIndex in the order it was collected, using
  the exact thresholds the collectors use. The FIRST source of a story stays;
  later retellings are removed. Hand-curated seeds (E1xx) are never removed —
  they only seed the index.

  Removal is not silent: every removed row is written out in full (--out) so
  the decision is reversible by hand.

  Re-collection is not a risk. A removed feed item is still listed in
  feed_state.json (last 300 links per feed) so it is not re-fetched as fresh,
  and if it ever did come round again DupIndex would block it against the
  copy that stayed.

USAGE
  python3 scripts/prune_duplicates.py                 # report only (default)
  python3 scripts/prune_duplicates.py --apply         # rewrite events.json
  python3 scripts/prune_duplicates.py --apply --out /path/removed.json
"""
import os, sys, json, argparse

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
from llm_common import DupIndex, DEDUP_WINDOW_DAYS

DATA = os.path.join(HERE, "..", "data", "events.json")
DEFAULT_OUT = os.path.join(HERE, "..", "data", "pruned_duplicates.json")


def find_duplicates(events):
    """Return [(event, original, reason, score)] in collection order."""
    # Collection order, not date order: "first source wins" means the one we
    # captured first, and a later-captured item can carry an earlier date.
    order = sorted(events, key=lambda e: (e.get("captured_date") or e.get("date") or "",
                                          e.get("date") or ""))
    idx, dups = DupIndex([]), []
    for e in order:
        if str(e.get("event_id", ""))[:1] == "E":      # hand-curated seed
            idx.add(e)
            continue
        hit = idx.find(raw_title=e.get("raw_title"), url=e.get("raw_url"),
                       anchor=e.get("raw_date") or e.get("date"))
        if not hit:
            hit = idx.find(ko_title=e.get("title"), anchor=e.get("date"))
        if hit:
            dups.append((e, hit[0], hit[1], hit[2]))
            continue
        idx.add(e)
    return dups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the pruned file")
    ap.add_argument("--out", default=DEFAULT_OUT, help="where to save removed rows")
    args = ap.parse_args()

    events = json.load(open(DATA, encoding="utf-8"))
    dups = find_duplicates(events)
    print(f"events {len(events)}건 — 중복 {len(dups)}건 "
          f"(창 {DEDUP_WINDOW_DAYS}일)")
    from collections import Counter
    print("  사유별:", dict(Counter(r for _, _, r, _ in dups)))
    for e, orig, why, score in dups:
        print(f"  [{why} {score}] {e.get('date')} {e.get('event_id')} "
              f"{(e.get('title') or '')[:44]}")
        print(f"       ← 남김 {orig.get('date')} {orig.get('event_id')} "
              f"{(orig.get('title') or '')[:44]}")

    if not args.apply:
        print("\n(dry-run — 실제 저장하려면 --apply)")
        return

    remove = {id(e) for e, _, _, _ in dups}
    kept = [e for e in events if id(e) not in remove]
    kept.sort(key=lambda e: e.get("date", ""))
    record = [{"removed": e, "duplicate_of": orig.get("event_id"),
               "reason": why, "score": score} for e, orig, why, score in dups]
    json.dump(record, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(kept, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n저장 완료: {len(dups)}건 제거, 최종 {len(kept)}건 "
          f"(제거분 전문 → {os.path.relpath(args.out)})")


if __name__ == "__main__":
    main()
