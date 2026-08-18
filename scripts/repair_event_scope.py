#!/usr/bin/env python3
"""
One-off repair — normalise the `scope` (impact countries) field.

WHY
  FILTER_SYSTEM asked for "country codes from US,GB,…,KR; full list if
  worldwide" and never checked the answer. The models replied three ways:

    - the codes, as intended
    - "WW" (80 events) or "worldwide" (85) — tokens the dashboard has never
      heard of
    - "full list if worldwide" (13) — the instruction text itself, stored as
      if it were a country

  The region/country filter matches an event only when its scope contains a
  code the filter knows, so 101 events vanished the moment any country or
  region was selected. They were not mis-filed; they were unreachable.

  Codes outside the twelve tracked markets (CN, JP, TW, AE, CA, ID) were real
  and correct, but had no entry in the filter either — same effect.

WHAT IT DOES
  Rewrites every event's scope through llm_common.clean_scope(), which as of
  2026-08-18 stores what the article says rather than a fixed market list:
  "전체" for a story that applies everywhere, otherwise the Korean names of
  the countries it is about. Old ISO codes are accepted as input aliases, so
  this converts the four months already stored (US;KR -> 미국;한국). Events
  whose scope is already in that form are untouched.

  The original string is preserved in `raw_scope` the first time an event is
  changed, so a bad expansion stays reversible.

USAGE
  python3 scripts/repair_event_scope.py            # report only (default)
  python3 scripts/repair_event_scope.py --apply    # rewrite data/events.json
"""
import os, sys, json, argparse
from collections import Counter

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
from llm_common import clean_scope, SCOPE_ALL, LEGACY_MARKETS

DATA = os.path.join(HERE, "..", "data", "events.json")


def migrate(old):
    """clean_scope(), plus the one rule only a migration needs.

    The old prompt said "full list if worldwide", so an event carrying all
    twelve tracked markets was the model saying worldwide, not making twelve
    separate country claims. Those become "전체". Anything narrower is a real
    country list and converts name by name.
    """
    codes = {t.strip() for t in (old or "").split(";") if t.strip()}
    if codes >= set(LEGACY_MARKETS):
        return SCOPE_ALL
    return clean_scope(old)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the repaired file")
    args = ap.parse_args()

    events = json.load(open(DATA, encoding="utf-8"))
    changes, before, after = [], Counter(), Counter()
    for e in events:
        # raw_scope holds the model's own untouched answer, kept the first time
        # this ran. Re-deriving from it (not from the already-rewritten scope)
        # is what recovers information a previous pass discarded — "EU" was
        # expanded into four countries before regions became storable, and only
        # the original still says the article named the bloc, not the members.
        old = e.get("raw_scope") or e.get("scope", "")
        before.update(t for t in old.split(";") if t)
        new = migrate(old)
        after.update(new.split(";"))
        if new != e.get("scope", ""):
            changes.append((e, e.get("scope", ""), new))

    print(f"events {len(events)}건 — scope 수정 대상 {len(changes)}건")
    print(f"  수정 전 값 종류 {len(before)}개 / 수정 후 {len(after)}개")
    print(f"  수정 후: 전체 {after[SCOPE_ALL]}건, "
          f"국가 지정 {sum(v for k, v in after.items() if k != SCOPE_ALL)}건")
    named = sorted((k for k in after if k != SCOPE_ALL), key=lambda k: -after[k])
    print(f"  등장 국가 {len(named)}개: " + ", ".join(f"{k}({after[k]})" for k in named))
    shown = Counter((o, n) for _, o, n in changes)
    print("\n대표 변환 (상위 8):")
    for (o, n), cnt in shown.most_common(8):
        print(f"  {cnt:4d}건  {o[:52]!r}\n            → {n[:52]!r}")

    if not args.apply:
        print("\n(dry-run — 실제 저장하려면 --apply)")
        return

    for e, old, new in changes:
        e.setdefault("raw_scope", old)      # keep the model's own answer
        e["scope"] = new
    json.dump(events, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n저장 완료: {len(changes)}건 수정")


if __name__ == "__main__":
    main()
