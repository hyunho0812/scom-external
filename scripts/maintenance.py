#!/usr/bin/env python3
"""
Maintenance operations on data/events.json — run by hand, never by the daily
workflow.

Five separate scripts used to live here (repair_event_dates, repair_event_scope,
prune_duplicates, merge_past_events, check_feed_translation). They were the same
program with different bodies: load events.json, work out what should change,
print it, and only write when told to. Folding them into subcommands means one
place for that shape, one --apply convention, and one file to keep current when
the event schema moves.

  dates        Repair dates corrupted before the prompt carried today's date.
               Until 2026-08-10 the model had no clock and anchored extracted
               dates to its training era: 291 of 325 auto-collected events were
               stored more than a YEAR before the day they were captured, and
               the dashboard's period filter, trend chart and axis split all key
               off `date`. Prefers a publish date embedded in raw_url, else
               falls back to captured_date when the stored date is implausible.
               Also stamps date_source on rows collected before that field
               existed. Seeds (E1xx) are never touched.

  scope        Normalise `scope` to what the article says: "전체", or Korean
               country/region names. Reads raw_scope (the model's untouched
               answer) so information an earlier pass discarded — "EU" expanded
               into four countries — comes back as 유럽.

  dedupe       Remove events a later source retold, using the same DupIndex
               thresholds the collectors enforce. First source wins. Removed
               rows are written out in full so the decision is reversible.

  merge        Merge hand-curated event JSON arrays into events.json, validating
               each record against the schema and renumbering ids (E101...).

  translation  Report feed events whose description never got translated —
               a symptom of the whole LLM chain failing for that run.

USAGE
  python3 scripts/maintenance.py <command>            # report only (default)
  python3 scripts/maintenance.py <command> --apply    # write the change
"""
import os, sys, json, re, glob, argparse
from datetime import date
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
from llm_common import (EVENTS_FILE, PRUNED_FILE, DEDUP_WINDOW_DAYS, LEGACY_MARKETS,
                        SCOPE_ALL, DupIndex, clean_scope, clean_axis, parse_date,
                        has_korean, read_json, write_json)


# ============================================================ dates
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


def cmd_dates(args):
    events = read_json(EVENTS_FILE, [])
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
    write_json(EVENTS_FILE, deduped)
    print(f"\n저장 완료: date_source {len(missing)}건 보강, {len(changes)}건 수정, 중복 {dropped}건 제거, 최종 {len(deduped)}건")


# ============================================================ scope
def migrate_scope(old):
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


def cmd_scope(args):
    events = read_json(EVENTS_FILE, [])
    changes, before, after = [], Counter(), Counter()
    for e in events:
        # raw_scope holds the model's own untouched answer, kept the first time
        # this ran. Re-deriving from it (not from the already-rewritten scope)
        # is what recovers information a previous pass discarded — "EU" was
        # expanded into four countries before regions became storable, and only
        # the original still says the article named the bloc, not the members.
        old = e.get("raw_scope") or e.get("scope", "")
        before.update(t for t in old.split(";") if t)
        new = migrate_scope(old)
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
    write_json(EVENTS_FILE, events)
    print(f"\n저장 완료: {len(changes)}건 수정")


# ============================================================ dedupe
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


def cmd_dedupe(args):
    events = read_json(EVENTS_FILE, [])
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
    write_json(args.out, record)
    write_json(EVENTS_FILE, kept)
    print(f"\n저장 완료: {len(dups)}건 제거, 최종 {len(kept)}건 "
          f"(제거분 전문 → {os.path.relpath(args.out)})")


# ============================================================ merge
ALLOWED_CAT = {"culture","marketing","platform","holiday","economy",
               "social_issue","geopolitics","AI","company","regulation"}
ALLOWED_DIV = {"MX","VD","DA"}
ALLOWED_KPI = {"Impression","Click","Traffic","Order","CVR","Revenue","AOV"}
ALLOWED_DIR = {"+","-","neutral","unknown"}
ALLOWED_HOR = {"immediate","weeks","months"}
ALLOWED_CONF = {"high","med","low"}
ALLOWED_METRIC = {"traffic","revenue","both"}
# common fixes for category values AIs might emit
CAT_FIX = {"competitor":"company","ai":"AI","ecommerce":"economy",
           "tech":"company","environment":"geopolitics","politics":"geopolitics"}

def clean_list(val, allowed, fixes=None):
    if isinstance(val, list):
        items = val
    else:
        items = re.split(r"[;,]", str(val or ""))
    out = []
    for it in items:
        it = it.strip()
        if fixes and it.upper() in fixes: it = fixes[it.upper()]
        if it in allowed and it not in out:
            out.append(it)
    return out

def clean_record(r):
    try:
        date = str(r.get("date","")).strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            return None
        cat = str(r.get("category","economy")).strip()
        cat = CAT_FIX.get(cat, cat)
        if cat not in ALLOWED_CAT: cat = "economy"
        # Korean country names or "전체" — see llm_common.clean_scope()
        scope = clean_scope(r.get("scope"))
        divs = clean_list(r.get("divisions"), ALLOWED_DIV)
        kpi = clean_list(r.get("kpi"), ALLOWED_KPI) or ["Traffic"]
        d = str(r.get("impact_direction","unknown")).strip()
        if d not in ALLOWED_DIR: d = "unknown"
        hor = str(r.get("impact_horizon","weeks")).strip()
        if hor not in ALLOWED_HOR: hor = "weeks"
        conf = str(r.get("confidence","low")).strip()
        if conf not in ALLOWED_CONF: conf = "low"
        metric = str(r.get("metric","traffic")).strip()
        if metric not in ALLOWED_METRIC: metric = "traffic"
        try: strength = int(r.get("impact_strength",2))
        except (ValueError, TypeError): strength = 2
        strength = max(1, min(5, strength))
        title = str(r.get("title","")).strip()
        if not title: return None
        return {
            "event_id": "TMP",
            "date": date,
            "captured_date": str(r.get("captured_date", date)).strip() or date,
            "scope": scope,   # already a ';'-joined string
            "divisions": ";".join(divs),
            "kpi": ";".join(kpi),
            "category": cat,
            "title": title,
            "description": str(r.get("description","")).strip(),
            "impact_direction": d,
            "impact_horizon": hor,
            "confidence": conf,
            "metric": metric,
            "source": str(r.get("source","")).strip(),
            "impact": str(r.get("impact","")).strip(),
            "impact_strength": strength,
            "axis": clean_axis(r.get("axis","")),  # demand|share|supply|"" — "" falls back to build.py's heuristic
        }
    except Exception:
        return None

def load_array(path):
    txt = open(path, encoding="utf-8").read().strip()
    # tolerate code fences or leading prose
    txt = txt.replace("```json","").replace("```","").strip()
    i = txt.find("["); j = txt.rfind("]")
    if i>=0 and j>i: txt = txt[i:j+1]
    return json.loads(txt)

def cmd_merge(args):
    folder, out = args.folder, args.out
    files = sorted(glob.glob(os.path.join(folder,"*.json")))
    if not files:
        print(f"No JSON files in {folder}/ — save each AI output as a .json file there.")
        return
    records = []
    for f in files:
        try:
            arr = load_array(f)
        except Exception as e:
            print(f"  skip {f}: parse error {e}"); continue
        kept = 0
        for r in (arr or []):
            c = clean_record(r)
            if c: records.append(c); kept += 1
        print(f"  {os.path.basename(f)}: {kept} valid records")
    # dedup by (date,title), sort by date, renumber
    seen=set(); uniq=[]
    for r in sorted(records, key=lambda x:(x["date"], x["title"])):
        key=(r["date"], r["title"][:40])
        if key in seen: continue
        seen.add(key); uniq.append(r)
    for i,r in enumerate(uniq, start=101):
        r["event_id"] = f"E{i}"
    write_json(out, uniq)
    print(f"\nMerged {len(uniq)} events -> {out}")
    print(f"Date range: {uniq[0]['date'] if uniq else '-'} ~ {uniq[-1]['date'] if uniq else '-'}")

# ============================================================ translation
def cmd_translation(args):
    """Feed events whose description never got translated.

    English text here means every provider in the chain failed for that item
    and something stored the source text anyway — the collectors refuse to do
    that now, so a non-zero count points at older rows or a regression.
    """
    ev = read_json(args.file, [])
    feeds = [e for e in ev if str(e.get("event_id", "")).startswith("FP")]
    print(f"피드 이벤트(FP): {len(feeds)}건")
    if not feeds:
        print("→ 피드 이벤트가 없음.")
        return
    eng = [e for e in feeds if not has_korean(e.get("description", ""))]
    same = [e for e in feeds
            if e.get("description", "") == e.get("raw_desc", "") and e.get("raw_desc")]
    print(f"  description이 영어(번역 실패 의심): {len(eng)}건")
    print(f"  description == raw_desc(번역 전혀 안 됨): {len(same)}건")
    if not eng:
        print("\n✓ 모든 피드 이벤트가 한국어 — 번역 정상")
        return
    print("\n=== 번역 실패 의심 항목 (최대 5건) ===")
    for e in eng[:5]:
        print(f"  {e['event_id']} | {e.get('title','')[:50]}")
        print(f"    desc: {e.get('description','')[:80]}")
    print(f"\n→ 피드 {len(feeds)}건 중 {len(eng)}건({len(eng)/len(feeds)*100:.0f}%)이 영어 "
          f"= LLM 체인(Gemini→Groq→Mistral)이 전부 실패했거나 키가 없음")


# ============================================================ dispatch
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("dates", help="repair event dates + stamp date_source")
    p.add_argument("--apply", action="store_true", help="write the repaired file")
    p.add_argument("--threshold", type=int, default=REPAIR_THRESHOLD,
                   help="days before capture past which a stored date is implausible")
    p.set_defaults(func=cmd_dates)

    p = sub.add_parser("scope", help="normalise scope to 전체 / Korean names")
    p.add_argument("--apply", action="store_true", help="write the repaired file")
    p.set_defaults(func=cmd_scope)

    p = sub.add_parser("dedupe", help="remove near-duplicate events")
    p.add_argument("--apply", action="store_true", help="write the pruned file")
    p.add_argument("--out", default=PRUNED_FILE, help="where to save removed rows")
    p.set_defaults(func=cmd_dedupe)

    p = sub.add_parser("merge", help="merge curated event arrays into events.json")
    p.add_argument("folder", nargs="?", default="past_events")
    p.add_argument("out", nargs="?", default=EVENTS_FILE)
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("translation", help="report untranslated feed events")
    p.add_argument("file", nargs="?", default=EVENTS_FILE)
    p.set_defaults(func=cmd_translation)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
