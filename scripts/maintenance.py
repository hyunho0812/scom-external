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

  split        Retrofit the 요약 / LLM 추론 split onto events collected before
               2026-08-18, whose description carries the model's inference in
               its trailing sentence(s). The inference half is already stored
               separately in `impact`, so this only has to take it out of the
               summary — no re-judging, no LLM. Originals kept in
               raw_description.

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
                        has_korean, read_json, write_json, guess_axis, data_path,
                        VALID_AXES, AXIS_SPEC)
import llm_common as L


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

    # Hand-seeded rows are skipped by repair(), which left them with no
    # date_source at all. The scorer already treats a missing value as "seed",
    # so nothing behaved wrongly — but an absent field and an implicit default
    # are not the same thing to anyone reading the file, and the audit cannot
    # tell a seed apart from a collector that quietly stopped stamping.
    seeded = 0
    for e in events:
        if not e.get("date_source") and str(e.get("event_id", ""))[:1] not in ("A", "F"):
            e["date_source"] = "seed"
            seeded += 1
    if seeded:
        print(f"시드 {seeded}건에 date_source='seed' 명시")

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


# ============================================================ split
# The old prompt asked for one `description` paragraph built as "sentence 1:
# what happened. sentence 2: how this affects samsung.com web traffic", so
# every event collected before 2026-08-18 has the model's inference glued onto
# the article's facts. The dashboard now labels the two separately (요약 /
# LLM 추론), and the inference half already exists on its own in `impact` —
# all 435 stored events have one. So the retrofit is a split, not a re-judge:
# take the trailing inference sentences out of description and keep the facts.
#
# No LLM is involved and none is needed. The whole original is kept in
# raw_description, so anything the split gets wrong is recoverable and running
# this twice changes nothing.
# Split on punctuation only. Including 다 as a terminator looks right for
# Korean until a postposition ends in it: "직접 방문하기보다 AI 에이전트를…"
# and "평소보다 훨씬" both split mid-sentence, and the summary came out cut off
# in the middle of a clause. Every stored description ends its sentences with
# a period, so punctuation alone is both correct and unambiguous.
_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+')
# Naming our own site is what marks a sentence as the inference half. Traffic
# words alone are not enough: "AI 검색 결과에 마크다운 페이지가 더 잘 노출되도록
# 광고를 활용한다" is the article reporting how Time's ad product works, and a
# 노출/클릭 keyword would have thrown that fact out of the summary.
_INFERENCE_MARK = re.compile(
    r'삼성닷컴|samsung\.com|삼성\.com|브랜드 (공식 )?사이트|삼성 공식 사이트|자사몰')


def sentences(text):
    text = (text or "").strip()
    return [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()] if text else []


def split_fact_inference(description):
    """(facts, inference) sentence lists for one stored description.

    Two sentences is the documented old shape — fact then inference — so the
    second one goes, whatever words it happens to use: a market-level guess
    like "소비자는 구매를 미루는 경향을 보인다" is still a guess. With three or
    more, only the trailing sentences that NAME samsung.com are inference; the
    middle ones are usually still reporting, and if none names it the old shape
    still says the last one is the inference. The first sentence is never
    dropped, so a summary can never come out empty.
    """
    s = sentences(description)
    if len(s) < 2:
        return s, []
    if len(s) == 2:
        return s[:1], s[1:]
    k = len(s)
    while k > 1 and _INFERENCE_MARK.search(s[k - 1]):
        k -= 1
    if k == len(s):          # none of them names the site — old shape says last
        k -= 1
    return s[:k], s[k:]


def cmd_split(args):
    events = read_json(EVENTS_FILE, [])
    changes, unchanged = [], 0
    for e in events:
        # Always split from raw_description when it exists: it is the untouched
        # original, so re-running reproduces the same answer instead of cutting
        # an already-split summary in half, and a later fix to the splitter can
        # simply be re-applied.
        source = e.get("raw_description") or e.get("description", "")
        facts, inference = split_fact_inference(source)
        new_desc = " ".join(facts)
        if not inference or new_desc == e.get("description", ""):
            unchanged += 1
            continue
        changes.append((e, source, new_desc, " ".join(inference)))

    kept_len = [len(new) for _, _, new, _ in changes]
    print(f"events {len(events)}건 — 요약/추론 분리 대상 {len(changes)}건")
    if changes:
        print(f"  분리 후 요약 길이: 최소 {min(kept_len)}자 / 중앙값 "
              f"{sorted(kept_len)[len(kept_len)//2]}자")
    print(f"  그대로 두는 건: {unchanged}건 (이미 분리됐거나 사실만 있음)")
    if changes:
        print("\n표본 3건:")
        for e, old, new, inf in changes[:3]:
            print(f"  · {(e.get('title') or '')[:44]}")
            print(f"    요약 ← {new[:74]}")
            print(f"    떼어냄 {inf[:74]}")
            print(f"    (impact) {(e.get('impact') or '')[:74]}")

    if not args.apply:
        print("\n(dry-run — 실제 저장하려면 --apply)")
        return

    for e, source, new_desc, _inf in changes:
        e.setdefault("raw_description", source)  # the pre-split original
        e["description"] = new_desc
    write_json(EVENTS_FILE, events)
    print(f"\n저장 완료: {len(changes)}건 분리 (원본은 raw_description에 보존)")

# ============================================================ dispatch
AXIS_BATCH = int(os.environ.get("AXIS_BATCH", "5"))


def _axis_prompt(items):
    """Ask for the axis and nothing else.

    Deliberately NOT FILTER_SYSTEM. That prompt re-decides relevance, direction,
    strength and the Korean body text, so running it here would rewrite verdicts
    the ledger is supposed to preserve — and could drop an event entirely on a
    REJECT rule written after it was collected. This asks the one question the
    heuristic answered badly, using AXIS_SPEC so the wording is the same one
    every other axis judgement was made against.
    """
    blocks = []
    for i, e in enumerate(items):
        blocks.append(
            f"[{i}] CATEGORY: {e.get('category') or '-'}\n"
            f"TITLE: {(e.get('title') or '')[:200]}\n"
            f"SUMMARY: {(e.get('description') or '')[:400]}\n"
            f"INFERENCE: {(e.get('impact') or '')[:300]}")
    return ("You classify stored events for a samsung.com traffic dashboard.\n"
            "For EACH item below decide ONLY the axis.\n\n"
            "axis: " + AXIS_SPEC + "\n\n"
            f"Return a JSON array of exactly {len(items)} objects, same order as the "
            'items, each {"i":<index>,"axis":"demand|share|supply"}. '
            "No other fields and no prose.\n\n" + "\n\n".join(blocks))


def _judge_axes(items):
    """{index: axis} from the provider chain, retrying only what is unresolved.

    Falls through Gemini -> Groq -> Mistral like the collectors do, but each
    retry carries only the items still missing an axis, so one provider's
    partial answer is kept rather than thrown away. An item no provider
    resolved is simply absent from the result: the project's rule is to skip,
    never to store a guess dressed up as a judgement.
    """
    out = {}
    pending = list(range(len(items)))
    for fn, model, name in L._chain():
        if not pending:
            break
        for flag in (L._gemini_off, L._groq_off, L._mistral_off):
            flag["flag"] = False
        subset = [items[i] for i in pending]
        res = fn(_axis_prompt(subset), 200 + 60 * len(subset))
        if isinstance(res, dict):
            vals = [v for v in res.values() if isinstance(v, list)]
            res = vals[0] if len(vals) == 1 else None
        if not isinstance(res, list):
            print(f"  {name}: 응답 형태 불일치 — 다음 provider로")
            continue
        got = 0
        for pos, row in enumerate(res):
            if not isinstance(row, dict):
                continue
            # Trust the echoed index when it is usable, else fall back to
            # position — the same alignment guard the batch collectors use.
            j = row.get("i")
            j = j if isinstance(j, int) and 0 <= j < len(subset) else pos
            ax = clean_axis(row.get("axis"))
            if ax:
                out[pending[j]] = (ax, model)
                got += 1
        print(f"  {name} ({model}): {got}/{len(subset)}건 판정")
        pending = [i for i in pending if i not in out]
    return out


def rejudge_axes(events, batch, limit):
    """Re-ask the model for the axis of every heuristic-filled event."""
    todo = [e for e in events if e.get("axis_source") == "heuristic"]
    if limit:
        todo = todo[:limit]
    print(f"휴리스틱으로 채운 {len(todo)}건을 {batch}건씩 재판정합니다")
    changed, kept, failed = [], 0, 0
    for start in range(0, len(todo), batch):
        chunk = todo[start:start + batch]
        print(f"[{start + 1}-{start + len(chunk)}/{len(todo)}]")
        res = _judge_axes(chunk)
        for i, e in enumerate(chunk):
            if i not in res:
                failed += 1
                continue
            ax, model = res[i]
            if ax != e.get("axis"):
                changed.append((e, e.get("axis"), ax))
            else:
                kept += 1
            e["_new_axis"], e["_new_model"] = ax, model
    return todo, changed, kept, failed


def cmd_axis(args):
    """Fill in the axis for events that never got one.

    Everything hand-seeded and everything collected before the field existed
    carries no axis, and the dashboard has been guessing for them on every
    page load. Storing the guess means the ledger says what the dashboard
    shows, and `axis_source` keeps the guess distinguishable from the model's
    own call — so a later pass can revisit the heuristic ones without touching
    a judgement that was actually made.
    """
    events = read_json(EVENTS_FILE, [])

    if getattr(args, "from_file", None):
        # Apply axes decided elsewhere. The re-judge above needs the API keys
        # and network egress, which a sandboxed session does not have; a
        # reviewer with the ledger in front of them can decide the same field
        # and hand the result over as {event_id: axis}. Same guards either way:
        # only heuristic-filled events are touched and the axis must be valid.
        #
        # The guess being replaced is NOT saved. Unlike raw_title/raw_date/
        # raw_description, which hold things that cannot be produced again, it
        # is just the output of guess_axis() over fields the event still
        # carries — re-running that function reproduces it exactly.
        mapping = read_json(args.from_file, {})
        if not isinstance(mapping, dict) or not mapping:
            print("적용할 판정이 없습니다:", args.from_file)
            return
        by_id = {e.get("event_id"): e for e in events}
        applied, changed, skipped = 0, [], []
        for eid, raw in mapping.items():
            e = by_id.get(eid)
            ax = clean_axis(raw)
            if e is None:
                skipped.append((eid, "이벤트 없음"))
            elif e.get("axis_source") != "heuristic":
                skipped.append((eid, f"axis_source={e.get('axis_source')}"))
            elif not ax:
                skipped.append((eid, f"축 값이 잘못됨: {raw!r}"))
            else:
                applied += 1
                if ax != e.get("axis"):
                    changed.append((e, e.get("axis"), ax))
                if args.apply:
                    e["axis"] = ax
                    e["axis_source"] = args.source
        print(f"{args.from_file}\n적용 대상 {applied}건 · 바뀜 {len(changed)}건 · "
              f"건너뜀 {len(skipped)}건 · axis_source → {args.source!r}")
        moves = Counter((a, b) for _, a, b in changed)
        for (a, b), n in moves.most_common():
            print(f"  {a} → {b}: {n}건")
        for e, a, b in changed:
            print(f"  {e.get('event_id')} [{e.get('category')}] {a} → {b}  "
                  f"{(e.get('title') or '')[:44]}")
        for eid, why in skipped[:10]:
            print(f"  건너뜀 {eid}: {why}")
        if args.apply:
            write_json(EVENTS_FILE, events)
            print("적용됨:", EVENTS_FILE)
        else:
            print("(dry-run — --apply 로 저장)")
        return

    if getattr(args, "rejudge", False):
        # Replace the keyword guess with an actual judgement. The heuristic's
        # last rule is "everything else -> demand", so economy/regulation/
        # geopolitics events were labelled without anything having read them,
        # and 90 of the 94 came out demand. Those labels are what the axis
        # decomposition and the group fit are built on.
        todo, changed, kept, failed = rejudge_axes(events, args.batch, args.limit)
        print(f"\n판정됨 {len(changed) + kept}건 · 바뀜 {len(changed)}건 · "
              f"그대로 {kept}건 · 실패 {failed}건")
        moves = Counter((a, b) for _, a, b in changed)
        for (a, b), n in moves.most_common():
            print(f"  {a} → {b}: {n}건")
        for e, a, b in changed[:12]:
            print(f"  {e.get('event_id')} [{e.get('category')}] {a} → {b}  "
                  f"{(e.get('title') or '')[:40]}")
        if args.apply:
            for e in todo:
                ax = e.pop("_new_axis", None)
                e.pop("_new_model", None)
                if not ax:
                    continue        # no provider answered — leave the guess alone
                # The guess is not preserved: guess_axis() recomputes it from
                # fields the event still has, and axis_source already says which
                # events this pass touched.
                e["axis"] = ax
                e["axis_source"] = "llm"
            write_json(EVENTS_FILE, events)
            print("적용됨:", EVENTS_FILE)
        else:
            for e in todo:
                e.pop("_new_axis", None), e.pop("_new_model", None)
            print("(dry-run — --apply 로 저장)")
        return

    todo = [e for e in events if e.get("axis") not in VALID_AXES]
    counts = {}
    for e in todo:
        ax = guess_axis(e)
        counts[ax] = counts.get(ax, 0) + 1
        if args.apply:
            e["axis"] = ax
            e["axis_source"] = "heuristic"
    for e in events:
        if args.apply and e.get("axis") in VALID_AXES and not e.get("axis_source"):
            e["axis_source"] = "llm"
    print(f"축 없는 이벤트 {len(todo)}건 → {counts}")
    for e in todo[:8]:
        print(f"  {e.get('event_id')} [{e.get('category')}] → {guess_axis(e)}  {(e.get('title') or '')[:40]}")
    if args.apply:
        write_json(EVENTS_FILE, events)
        print("적용됨:", EVENTS_FILE)
    else:
        print("(dry-run — --apply 로 저장)")


def cmd_audit(args):
    """One pass over data/ that reports what is missing or inconsistent.

    Read-only. The daily pipeline keeps appending to these files and nothing
    re-checks their shape, so this is the sweep that catches a field that
    silently stopped being written or a cross-file reference that no longer
    resolves.
    """
    problems = []
    def bad(msg):
        problems.append(msg)
        print("  ✗", msg)
    def ok(msg):
        print("  ✓", msg)

    events = read_json(EVENTS_FILE, [])
    print(f"\n[events.json] {len(events)}건")
    ids = [e.get("event_id") for e in events]
    if len(ids) != len(set(ids)):
        bad(f"event_id 중복 {len(ids)-len(set(ids))}건")
    else:
        ok("event_id 고유")
    if events != sorted(events, key=lambda e: e.get("date") or ""):
        bad("date 정렬 깨짐")
    else:
        ok("date 정렬")
    checks = [
        ("axis", lambda e: e.get("axis") in VALID_AXES),
        ("impact_direction", lambda e: e.get("impact_direction") in ("+", "-", "neutral", "unknown")),
        ("impact_horizon", lambda e: e.get("impact_horizon") in ("immediate", "weeks", "months")),
        ("confidence", lambda e: (e.get("confidence") or "").lower() in ("high", "med", "low")),
        ("impact_strength", lambda e: isinstance(e.get("impact_strength"), int) and 1 <= e["impact_strength"] <= 5),
        ("scope", lambda e: bool(e.get("scope"))),
        ("date_source", lambda e: bool(e.get("date_source"))),
        ("description", lambda e: bool(e.get("description"))),
        ("impact", lambda e: bool(e.get("impact"))),
    ]
    for name, pred in checks:
        miss = [e for e in events if not pred(e)]
        if miss:
            bad(f"{name} 결측/이상 {len(miss)}건 (예 {miss[0].get('event_id')})")
        else:
            ok(f"{name} 전건 정상")

    print("\n[wiki_series.json]")
    ser = (read_json(data_path("wiki_series.json"), {}) or {}).get("series", {})
    before = len(problems)
    for brand, pts in sorted(ser.items()):
        ds = sorted(p.get("date") for p in pts if p.get("date"))
        if not ds:
            bad(f"{brand} 시계열 비어있음"); continue
        span = (parse_date(ds[-1]) - parse_date(ds[0])).days + 1
        gaps, dups = span - len(ds), len(ds) - len(set(ds))
        if gaps or dups:
            bad(f"{brand} 결측 {gaps}일 / 중복 {dups}건")
    if len(problems) == before:
        ok(f"{len(ser)}개 브랜드 전부 연속·중복 없음")

    print("\n[파일 간 참조]")
    ps = read_json(data_path("prediction_scores.json"), {}) or {}
    pe = (ps.get("strength_calibration") or {}).get("per_event") or {}
    orphan = [k for k in pe if k not in set(ids)]
    if orphan:
        bad(f"prediction_scores가 없는 이벤트 {len(orphan)}건을 참조")
    else:
        ok(f"prediction_scores.per_event {len(pe)}건 모두 events에 존재")
    pruned = read_json(PRUNED_FILE, []) or []
    back = [r for r in pruned if ((r.get("event") or {}).get("event_id")) in set(ids)]
    if back:
        bad(f"제거했던 중복 {len(back)}건이 events에 다시 있음")
    else:
        ok(f"pruned_duplicates {len(pruned)}건, 되살아난 것 없음")

    print("\n[신선도]")
    for name in ("feed_health.json", "model_status.json", "crux_series.json"):
        d = read_json(data_path(name), {}) or {}
        stamp = d.get("checked") or d.get("last_checked") or d.get("updated")
        print(f"  {name:22s} {stamp}")

    print(f"\n총 {len(problems)}건의 문제" if problems else "\n문제 없음")
    return problems


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

    p = sub.add_parser("split", help="split old description into 요약 / LLM 추론")
    p.add_argument("--apply", action="store_true", help="write the split file")
    p.set_defaults(func=cmd_split)

    p = sub.add_parser("axis", help="fill in a missing axis from the shared heuristic")
    p.add_argument("--apply", action="store_true", help="write the filled file")
    p.add_argument("--rejudge", action="store_true",
                   help="re-ask the LLM for the axis of heuristic-filled events "
                        "(needs the API keys; asks for the axis only)")
    p.add_argument("--batch", type=int, default=AXIS_BATCH,
                   help="events per request when re-judging")
    p.add_argument("--limit", type=int, default=0,
                   help="stop after this many events (0 = all)")
    p.add_argument("--from-file", dest="from_file",
                   help="apply axes from a {event_id: axis} JSON file instead "
                        "of calling the API")
    p.add_argument("--source", default="claude-opus-5",
                   help="axis_source to stamp when using --from-file")
    p.set_defaults(func=cmd_axis)

    p = sub.add_parser("audit", help="consistency sweep over data/ (read-only)")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("translation", help="report untranslated feed events")
    p.add_argument("file", nargs="?", default=EVENTS_FILE)
    p.set_defaults(func=cmd_translation)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
