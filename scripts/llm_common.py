#!/usr/bin/env python3
"""
Shared LLM judgement chain (Gemini -> Groq -> Mistral) used by BOTH
collect_news.py (NewsAPI/GDELT) and collect_feeds.py (first-party RSS).

Both collectors judge items the exact same way: a cheap keyword pre-filter
first (each collector keeps its own, since the keyword lists differ), then
this shared rich judgement — relevance, category, phenomenon-start date,
country/division scope, KPI, impact direction/strength/confidence — via
whichever of the three free LLMs is currently available. Centralizing this
means a Gemini quota outage never degrades either collector's classification
to hardcoded guesses; Groq or Mistral judge it for real, using the identical
prompt/schema, so results stay consistent regardless of which model answered.

Env (set as GitHub Secrets):
  GEMINI_API_KEY, GEMINI_MODEL   — aistudio.google.com/apikey (free, no card)
  GROQ_API_KEY, GROQ_MODEL       — console.groq.com/keys (free, no card)
  MISTRAL_API_KEY, MISTRAL_MODEL — console.mistral.ai (free, no card)

Also the single home for anything more than one script needs, so it cannot
drift out of sync the way the old per-collector keyword lists did:
  * every data/ and config file path (see "file paths" below) and the
    read_json/write_json pair that reads and writes them
  * queries.txt / kw_*.txt / interests.txt parsers
  * event field normalisation: clean_scope(), clean_date(), clean_axis()
  * near-duplicate suppression: DupIndex
  * has_korean(), clip_sentence(), parse_date()
"""
import os, re, json, time, urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(__file__)

# --- file paths -------------------------------------------------------------
# One name per file, defined once. events.json alone used to be DATA in five
# scripts, EVENTS in two and EVFILE in one, each with its own os.path.join —
# 44 of those joins across the tree, so a moved or renamed file meant finding
# every copy.
ROOT = os.path.join(HERE, "..")
DATA_DIR = os.path.join(ROOT, "data")


def data_path(name):
    return os.path.join(DATA_DIR, name)


EVENTS_FILE      = data_path("events.json")
FEED_STATE_FILE  = data_path("feed_state.json")
FEED_PERF_FILE   = data_path("feed_performance.json")
FEED_HEALTH_FILE = data_path("feed_health.json")
QUERY_PERF_FILE  = data_path("query_performance.json")
GDELT_POOL_FILE  = data_path("gdelt_pool.json")
WIKI_FILE        = data_path("wiki_series.json")
CRUX_FILE        = data_path("crux_series.json")
MODEL_STATUS_FILE = data_path("model_status.json")
LLM_USAGE_FILE   = data_path("llm_usage.json")
LLM_AGREEMENT_FILE = data_path("llm_agreement.json")
EVENT_PRESSURE_FILE = data_path("event_pressure.json")
PREDICTION_SCORES_FILE = data_path("prediction_scores.json")
OPTIMIZE_LOG_FILE = data_path("optimize_log.json")
PRUNED_FILE      = data_path("pruned_duplicates.json")

QUERIES_FILE   = os.path.join(ROOT, "queries.txt")
KW_NEWS_FILE   = os.path.join(ROOT, "kw_news.txt")
KW_FEEDS_FILE  = os.path.join(ROOT, "kw_feeds.txt")
INTERESTS_FILE = os.path.join(ROOT, "interests.txt")
FEEDS_FILE     = os.path.join(ROOT, "feeds.txt")
INDEX_HTML     = os.path.join(ROOT, "index.html")


def read_json(path, default=None):
    """Parse a JSON file, or return `default` if it is missing or unreadable.

    Every caller wrote this try/except itself (23 copies). A malformed file is
    treated as absent on purpose: the daily run must keep going and rewrite it,
    never halt because yesterday's output was truncated.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def write_json(path, obj, indent=1):
    """Write JSON the way every data/ file in this repo is written: UTF-8 with
    Korean kept readable, and indent 1 so a git diff is one line per field.

    indent=None for the day-by-day series (wiki_series, event_pressure): they
    run to tens of thousands of points, where one line per field turns a 280 KB
    file into megabytes and the per-line diff stops being useful anyway.
    """
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=indent)


# The twelve markets `scope` was restricted to until 2026-08-18, when it
# became free-form Korean country names (see clean_scope below). Kept because
# maintenance.py scope needs it to read the four months stored under the old
# scheme: a scope listing all twelve was the old prompt's way of saying
# worldwide, so it migrates to "전체" rather than to twelve country names.
LEGACY_MARKETS = ["US", "GB", "DE", "FR", "ES", "PT", "BR", "MX_C", "AU", "IN", "TR", "KR"]

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
MISTRAL_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")

_gemini_off = {"flag": False}
_groq_off = {"flag": False}
_mistral_off = {"flag": False}

# Per-provider telemetry for one run, persisted to data/llm_usage.json by
# save_usage(). These counters used to be three {ok, off, error} dicts printed
# to stdout and then lost with the Actions log, which made two things
# impossible to answer after the fact: how many requests each free tier
# actually consumed, and WHY the chain fell through to a later provider.
# The fields below separate the failure modes that matter for that:
#   attempt    - HTTP requests actually sent (what burns the free-tier quota)
#   ok         - returned a verdict the chain accepted
#   ko_reject  - returned a verdict, but title/impact/description weren't in
#                Korean, so _korean_fields_ok discarded it and the chain moved
#                on. Costs FULL tokens and yields nothing — the expensive
#                failure, and invisible in the old counters (they scored it
#                "ok" because the call itself succeeded).
#   empty      - responded, but with no usable output to parse
#   http_429   - rate/quota limited (sets the provider's off flag for the run)
#   http_auth  - 401/403 (also sets the off flag)
#   http_other - any other HTTP error
#   exception  - transport/parse failure
#   skipped_off- not called at all: no API key, or already disabled this run.
#                Costs nothing; this is why fallback is a per-RUN cost, not a
#                per-item one — after the first 429 the chain stops retrying
#                that provider entirely.
#   batch_shape_fail - answered a batch request with the wrong number of
#                verdicts (or not an array), so the batch was re-judged
#                per-item. Costs a full batch prompt and yields nothing;
#                if this climbs, lower LLM_BATCH.
#   batch_no_index - the batch had the right shape but the verdicts did not
#                echo a usable item number, so their pairing with the articles
#                rests on array position alone and nothing verified it. Not an
#                error; a standing count means this provider's alignment is
#                unchecked.
#   batch_reordered - verdicts arrived in a different order than the items and
#                were re-seated by their echoed number. Every one of these
#                would have been a judgement filed against the wrong article
#                before 2026-08-18.
_STAT_FIELDS = ("attempt", "ok", "ko_reject", "dir_reject", "empty", "batch_shape_fail",
                "batch_no_index", "batch_reordered",
                "http_429", "http_auth", "http_other", "exception", "skipped_off")
_STATS = {p: dict.fromkeys(_STAT_FIELDS, 0) for p in ("gemini", "groq", "mistral")}


def _bump(provider, field, n=1):
    _STATS[provider][field] += n


def has_korean(s):
    return any('\uac00' <= c <= '\ud7a3' for c in (s or ""))


# axis: which of the 3-axis-panel buckets (demand/share/supply) an event
# mainly acts through \u2014 see FILTER_SYSTEM below for the full definitions the
# LLM is given. clean_axis() guards against a malformed/missing value from
# the LLM; the collectors store "" in that case, and build.py's axisOf()
# falls back to its own keyword heuristic for any event with axis=="" (this
# is also what makes it a safe upgrade for the 90+ events collected before
# this field existed).
# The axis definitions the model is given. Held here rather than inline in
# FILTER_SYSTEM because two callers need the same words: the collectors, via
# FILTER_SYSTEM, and `maintenance.py axis --rejudge`, which re-asks this one
# field for events labelled before it existed. Two copies would drift, and a
# re-judgement made against different wording is not comparable to the
# original judgement.
AXIS_SPEC = (
 'demand|share|supply \u2014 WHICH of 3 causal buckets this event mainly '
 'acts through. demand = a MARKET-WIDE shift in overall interest/search '
 'volume/traffic pool that affects everyone in the category roughly equally, '
 'not specific to samsung.com vs one named rival (e.g. AI Overviews cutting '
 'click-through industry-wide, a memory-price macro shock, a holiday '
 'shopping surge, a broad social-commerce trend). share = REDISTRIBUTES '
 'visibility/traffic specifically BETWEEN samsung.com and a NAMED competitor '
 '(e.g. a competitor product launch/price move, an algorithm change that '
 'favors a named rival over Samsung). supply = about samsung.com\'s OWN site '
 '(indexing, crawling, outage, performance/Core Web Vitals) \u2014 never about a '
 'third party. When torn between demand and share, pick demand UNLESS a '
 'specific competitor is named as directly gaining at Samsung\'s expense.'
)

# --- event exposure weighting ------------------------------------------------
# How much of an event is still "in flight" on a given day:
#     strength x CONF_W[confidence] x 0.5 ** (age / halflife)
# score_predictions.py builds the cumulative impact index and the group fit on
# this, and build.py's per-event allocation divides an observed traffic move by
# the same quantity. Those two must agree exactly — an allocation weighted
# differently from the index it sits beside would put two contradictory
# readings of the same events on one screen — so the numbers live here and both
# sides import them rather than each keeping a copy.
HORIZON = {
    "immediate": {"halflife": 3,  "window": 7},
    "weeks":     {"halflife": 14, "window": 28},
    "months":    {"halflife": 60, "window": 90},
}
DEFAULT_HORIZON = "weeks"
CONF_W = {"high": 1.0, "med": 0.66, "low": 0.33}
DIR_SIGN = {"+": 1.0, "-": -1.0}
DECAY_CUTOFF = 4        # stop applying an event after this many half-lives

VALID_AXES = {"demand", "share", "supply"}
def clean_axis(v):
    v = (v or "").strip().lower()
    return v if v in VALID_AXES else ""


# Every factor points somewhere. "neutral"/"unknown" were in the enum, and an
# event carrying one gets no share of the period's move, no percentage and no
# bar — it sat in the ledger looking judged when nothing had been decided about
# it. 79 of 540 were in that state, and 56 of those never came from a model at
# all: the collectors filled a MISSING field with the literal "unknown", the
# hardcoded-default habit this project forbids everywhere else.
#
# So the escape hatch is gone from the prompt and from here. Uncertainty has a
# field of its own — `confidence` already reads "low = ... or you are unsure of
# the DIRECTION itself" — and that is where it belongs: a forced guess recorded
# as low confidence is weighted at 0.33 and stays visible as a guess, whereas
# "neutral" silently removed the event from every calculation on the page.
VALID_DIRECTIONS = {"+", "-"}
def clean_direction(v):
    v = (v or "").strip()
    return v if v in VALID_DIRECTIONS else ""


def clean_strength(v, default=2):
    """1-5 as an int. Groq answered "3" (a string) on 2026-09-01 and the
    collectors stored it verbatim, because they pass this field straight
    through. Both readers coerce (`+e.impact_strength` in build.py,
    `int(...)` in score_predictions.py) so nothing was visibly wrong — only
    `maintenance.py audit`, which checks the type, caught it. Same lesson as
    the date field (원칙 7): a value a model fills in gets range-checked and
    type-checked before it is stored, not where it happens to be read."""
    try:
        return max(1, min(5, int(str(v).strip())))
    except (TypeError, ValueError):
        return default

# The fallback used when an event carries no axis of its own — events collected
# before the field existed, and anything the model left blank. build.py has the
# same rules in JS for its own fallback; this is the Python side, and the two
# must agree or the dashboard will show one axis while the stored ledger says
# another.
SUPPLY_KW = ["인덱싱", "크롤링", "indexing", "crawling", "다운타임", "downtime",
             "장애", "outage", "core web vitals", "사이트 속도", "robots.txt", "sitemap"]
OWN_KW = ["samsung", "galaxy", "삼성", "갤럭시"]
# A named rival is what makes a platform/AI/marketing event a SHARE event —
# traffic moving between Samsung and that rival — rather than a market-wide
# shift that moves everyone's traffic together (DEMAND).
COMPETITOR_KW = ["apple", "xiaomi", "vivo", "oppo", "lg", "tcl", "hisense",
                 "whirlpool", "bosch", "아이폰", "애플", "샤오미", "비보", "오포",
                 "엘지", "보쉬"]


def guess_axis(event):
    """Heuristic axis for an event the model did not classify.

    Reads the text only. It used to branch on `category` first, which is why it
    put 13 Apple stories on the wrong axis (원칙 3): a regulation or economy
    story never reached the named-rival rule, so "EU fines Apple" came out
    demand. The field is gone now, and dropping the branch closes that hole —
    a named rival makes it share wherever it appears.

    build.py's axisOf() is the JS twin of this and must stay identical.
    """
    t = " ".join(str(event.get(f) or "") for f in
                 ("title", "impact", "description")).lower()
    if any(k in t for k in SUPPLY_KW):
        return "supply"
    # A named rival means traffic moving between Samsung and that rival —
    # unless the story is Samsung's own move, which grows the market instead.
    if any(k in t for k in COMPETITOR_KW) and not any(k in t for k in OWN_KW):
        return "share"
    return "demand"



# --- scope (impact countries) --------------------------------------------
# Scope is written the way the article reads, not as a fixed market list.
# "전체" when a story touches every market; otherwise the countries it is
# actually about, in Korean ("영국", "독일"). Two things changed on
# 2026-08-18 when this replaced the old twelve-code enum:
#
#   * The universe is no longer the twelve tracked markets. An article about
#     Vietnam used to be squeezed into "all twelve" or dropped; now it says
#     베트남. build.py builds the filter from whatever the events contain.
#   * The values are the labels. There is no code->Korean lookup left to drift
#     out of step with the data, and the stored file reads the way the
#     dashboard does.
#
# The models still answer this field loosely — codes, English names, "WW",
# once the instruction text itself — so clean_scope() maps all of it onto the
# canonical Korean name.
SCOPE_ALL = "전체"

# (ISO-2, Korean, English aliases). ISO-2 is kept only as an input alias: it is
# what four months of events were stored as, and what the models reach for.
_COUNTRY_TABLE = [
    ("US", "미국", ("UNITED STATES", "USA", "AMERICA", "U.S.", "U.S.A.")),
    ("CA", "캐나다", ("CANADA",)),
    ("MX_C", "멕시코", ("MEXICO", "MX")),
    ("BR", "브라질", ("BRAZIL",)),
    ("AR", "아르헨티나", ("ARGENTINA",)),
    ("CL", "칠레", ("CHILE",)),
    ("CO", "콜롬비아", ("COLOMBIA",)),
    ("PE", "페루", ("PERU",)),
    ("GB", "영국", ("UNITED KINGDOM", "UK", "GBR", "BRITAIN", "ENGLAND")),
    ("DE", "독일", ("GERMANY",)),
    ("FR", "프랑스", ("FRANCE",)),
    ("ES", "스페인", ("SPAIN",)),
    ("PT", "포르투갈", ("PORTUGAL",)),
    ("IT", "이탈리아", ("ITALY",)),
    ("NL", "네덜란드", ("NETHERLANDS", "HOLLAND")),
    ("BE", "벨기에", ("BELGIUM",)),
    ("CH", "스위스", ("SWITZERLAND",)),
    ("AT", "오스트리아", ("AUSTRIA",)),
    ("SE", "스웨덴", ("SWEDEN",)),
    ("NO", "노르웨이", ("NORWAY",)),
    ("DK", "덴마크", ("DENMARK",)),
    ("FI", "핀란드", ("FINLAND",)),
    ("IE", "아일랜드", ("IRELAND",)),
    ("PL", "폴란드", ("POLAND",)),
    ("CZ", "체코", ("CZECHIA", "CZECH REPUBLIC")),
    ("HU", "헝가리", ("HUNGARY",)),
    ("RO", "루마니아", ("ROMANIA",)),
    ("GR", "그리스", ("GREECE",)),
    ("UA", "우크라이나", ("UKRAINE",)),
    ("RU", "러시아", ("RUSSIA",)),
    ("TR", "튀르키예", ("TURKEY", "TURKIYE", "TÜRKIYE")),
    ("AE", "아랍에미리트", ("UAE", "UNITED ARAB EMIRATES")),
    ("SA", "사우디아라비아", ("SAUDI ARABIA", "SAUDI")),
    ("IL", "이스라엘", ("ISRAEL",)),
    ("EG", "이집트", ("EGYPT",)),
    ("ZA", "남아프리카공화국", ("SOUTH AFRICA", "남아공")),
    ("NG", "나이지리아", ("NIGERIA",)),
    ("KE", "케냐", ("KENYA",)),
    ("MA", "모로코", ("MOROCCO",)),
    ("IN", "인도", ("INDIA",)),
    ("PK", "파키스탄", ("PAKISTAN",)),
    ("BD", "방글라데시", ("BANGLADESH",)),
    ("LK", "스리랑카", ("SRI LANKA",)),
    ("CN", "중국", ("CHINA", "PRC")),
    ("JP", "일본", ("JAPAN",)),
    ("KR", "한국", ("SOUTH KOREA", "KOREA", "KOR", "ROK", "대한민국", "국내")),
    ("TW", "대만", ("TAIWAN",)),
    ("HK", "홍콩", ("HONG KONG",)),
    ("SG", "싱가포르", ("SINGAPORE",)),
    ("MY", "말레이시아", ("MALAYSIA",)),
    ("TH", "태국", ("THAILAND",)),
    ("VN", "베트남", ("VIETNAM", "VIET NAM")),
    ("PH", "필리핀", ("PHILIPPINES",)),
    ("ID", "인도네시아", ("INDONESIA",)),
    ("AU", "호주", ("AUSTRALIA", "오스트레일리아")),
    ("NZ", "뉴질랜드", ("NEW ZEALAND",)),
]

# Everything that means "every market".
_SCOPE_ALL_WORDS = {"전체", "전세계", "전 세계", "세계", "글로벌", "모든 국가", "전국가",
                    "WW", "WORLDWIDE", "WORLD", "GLOBAL", "GLOBALLY", "ALL",
                    "INTERNATIONAL", "FULL LIST IF WORLDWIDE", "FULL LIST",
                    "N/A", "NONE", "ANY", "-"}
# A region is a legitimate answer. When an article only says "EU" or "아시아",
# that IS what is known, and expanding it into a member list would put country
# claims in the ledger the article never made. So regions are stored as
# themselves — "유럽" — and the member lists below exist only so the filter can
# tell that a Europe-wide event belongs in Germany's view too.
#
# "아시아" is deliberately here and NOT in the dashboard's region dropdown: it
# overlaps 동아시아/동남아/서남아, so it works as a stored value and as a
# matching rule, but not as a filter group of its own.
SCOPE_REGIONS = {
    "북미": ["미국", "캐나다"],
    "중남미": ["브라질", "멕시코", "아르헨티나", "칠레", "콜롬비아", "페루"],
    "유럽": ["영국", "독일", "프랑스", "스페인", "포르투갈", "이탈리아", "네덜란드",
             "벨기에", "스위스", "오스트리아", "스웨덴", "노르웨이", "덴마크",
             "핀란드", "아일랜드", "폴란드", "체코", "헝가리", "루마니아",
             "그리스", "우크라이나", "러시아"],
    "중동": ["튀르키예", "아랍에미리트", "사우디아라비아", "이스라엘"],
    "아프리카": ["이집트", "남아프리카공화국", "나이지리아", "케냐", "모로코"],
    "서남아": ["인도", "파키스탄", "방글라데시", "스리랑카"],
    "동남아": ["인도네시아", "베트남", "태국", "필리핀", "말레이시아", "싱가포르"],
    "동아시아": ["중국", "일본", "대만", "홍콩"],
    "오세아니아": ["호주", "뉴질랜드"],
    "아시아": ["중국", "일본", "대만", "홍콩", "한국", "인도", "파키스탄",
               "방글라데시", "스리랑카", "인도네시아", "베트남", "태국",
               "필리핀", "말레이시아", "싱가포르"],
}
_REGION_ALIAS = {
    "EU": "유럽", "유럽연합": "유럽", "EUROPE": "유럽", "EUROPEAN UNION": "유럽",
    "EEA": "유럽", "서유럽": "유럽", "동유럽": "유럽",
    "북미": "북미", "NORTH AMERICA": "북미", "북아메리카": "북미",
    "중남미": "중남미", "남미": "중남미", "라틴아메리카": "중남미",
    "LATIN AMERICA": "중남미", "SOUTH AMERICA": "중남미",
    "중동": "중동", "MIDDLE EAST": "중동", "MENA": "중동",
    "아프리카": "아프리카", "AFRICA": "아프리카",
    "서남아": "서남아", "남아시아": "서남아", "SOUTH ASIA": "서남아",
    "동남아": "동남아", "동남아시아": "동남아", "SOUTHEAST ASIA": "동남아",
    "SOUTH EAST ASIA": "동남아",
    "동아시아": "동아시아", "EAST ASIA": "동아시아",
    "오세아니아": "오세아니아", "대양주": "오세아니아", "OCEANIA": "오세아니아",
    "아시아": "아시아", "ASIA": "아시아", "APAC": "아시아",
    "ASIA PACIFIC": "아시아", "아시아태평양": "아시아",
}
# Every canonical name is its own alias — easy to leave out by hand, and a
# missing one silently turns that region into "전체".
_REGION_ALIAS.update({r: r for r in SCOPE_REGIONS})
_REGION_ORDER = {r: i for i, r in enumerate(SCOPE_REGIONS)}

_SCOPE_LOOKUP = {}
for _code, _ko, _aliases in _COUNTRY_TABLE:
    for _k in (_code, _ko) + _aliases:
        _SCOPE_LOOKUP[_k.upper()] = _ko

# Order for the stored string: table order, so two events naming the same
# countries always serialise identically and diffs stay readable.
_SCOPE_ORDER = {ko: i for i, (_c, ko, _a) in enumerate(_COUNTRY_TABLE)}


def clean_scope(value):
    """Normalise an LLM 'scope' answer to "전체", or ';'-joined Korean country
    and region names.

    Accepts a list or a ';'-joined string, in any of the forms the models
    actually produce. Unrecognised tokens are dropped; if nothing usable
    survives the answer becomes "전체", which is the broadest reading and the
    default the collectors already applied to a missing scope — a garbled
    answer must never come out narrower than no answer at all.
    """
    if isinstance(value, str):
        parts = value.split(";")
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        parts = []
    out, regions, world = [], [], False
    for raw in parts:
        t = str(raw).strip().strip(".,'\"[]")
        if not t:
            continue
        key = t.upper()
        if key in _SCOPE_ALL_WORDS:
            world = True
            continue
        region = _REGION_ALIAS.get(key)
        if region:
            regions.append(region)
            continue
        ko = _SCOPE_LOOKUP.get(key)
        if ko:
            out.append(ko)
    if world or not (out or regions):
        return SCOPE_ALL
    seen, ordered = set(), []
    for c in sorted(out, key=lambda c: _SCOPE_ORDER.get(c, 999)):
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    # Countries first, then any region — a scope naming both reads as "these
    # countries, plus that region generally".
    for r in sorted(regions, key=lambda r: _REGION_ORDER.get(r, 99)):
        if r not in seen:
            seen.add(r)
            ordered.append(r)
    return ";".join(ordered)


# --- event date validation -------------------------------------------------
# Both collectors used to accept the model's date on a bare regex:
#     re.match(r"^\d{4}-\d{2}-\d{2}$", v)
# which passes "2024-05-00" (not a real day, 5 such rows got stored) and, far
# worse, passes any well-formed but wildly wrong year. With no clock in the
# prompt the model dated 90% of items to its training era, so the field the
# entire dashboard filters on was ~2 years off. clean_date() closes both holes:
# it parses strictly and rejects anything a last-24h news pipeline could not
# plausibly have produced, falling back to the source's own publish date.
DATE_MAX_BACKDATE = int(os.environ.get("DATE_MAX_BACKDATE", "180"))


def today_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def parse_date(v):
    """Strict ISO date parse -> datetime.date, or None. Rejects '2024-05-00'."""
    from datetime import datetime
    try:
        return datetime.strptime((v or "").strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def clean_date_ex(value, published=None, today=None, max_backdate=None):
    """Return (YYYY-MM-DD, date_source) for an event.

    value      - the date the LLM extracted (may be junk)
    published  - the source's own publish date, when the collector has one.
                 This is ground truth and becomes the fallback.
    Falls back to `published`, else `today`, when `value` is unparseable, in
    the future, or implausibly far in the past. A phenomenon can legitimately
    predate its article (a report on last quarter's shipments), so the
    backdate allowance is generous — it only has to catch the training-era
    anchoring, which sat >365 days out.

    The second element says WHERE the date came from, using the same vocabulary
    maintenance.py dates wrote and the dashboard/scorer read:
      'llm'     the model's own date survived validation ("기사 명시일")
      'url'     we fell back to the source's publish date ("발행일 확인")
      'capture' we fell back to the collection day ("수집일 추정")
    This is not cosmetic. score_predictions.py splits hit rates on it: a date
    taken FROM the capture day cannot also be evidence we foresaw that day's
    traffic, so 'capture' rows must land in the retrospective bucket. The
    collectors used to drop this provenance on the floor, which silently
    promoted every newly collected event into the foreknown bucket (they read
    as the 'seed' default).
    """
    today = today or today_iso()
    pub = parse_date(published)
    ref = pub or parse_date(today)
    fallback = (published if pub else today, "url" if pub else "capture")
    limit = DATE_MAX_BACKDATE if max_backdate is None else max_backdate
    d = parse_date(value)
    if d is None or ref is None:
        return fallback
    if d > ref:                      # nothing is published before it happens
        return (ref.isoformat(), fallback[1])
    if (ref - d).days > limit:       # training-era anchoring, not a real date
        return (ref.isoformat(), fallback[1])
    return (d.isoformat(), "llm")


def clean_date(value, published=None, today=None, max_backdate=None):
    """Date only. Prefer clean_date_ex() so the provenance is stored too."""
    return clean_date_ex(value, published, today, max_backdate)[0]


# --- near-duplicate suppression --------------------------------------------
# Ten feeds, two news APIs and a GDELT pool all cover the same story, so the
# ledger filled up with rows that differ only in wording. Exact-id dedup never
# caught them: the id is md5(title) or md5(label+title), and every source
# writes its own headline.
#
# Rule (what the dashboard owner asked for): within DEDUP_WINDOW_DAYS, only the
# FIRST source of a story is stored; later retellings are dropped.
#
# Two comparisons, at two different points in the pipeline, because neither
# text alone is a safe judge — measured on the 454 events already collected:
#   * raw_title (the source's own English headline) separates cleanly. True
#     cross-source duplicates score >= 0.47, the next unrelated pair 0.43. It
#     is checked BEFORE the LLM, so a duplicate costs no request at all.
#   * The Korean title the LLM writes is the only thing that can match a
#     Samsung KR newsroom post against English coverage of the same launch
#     (raw-headline similarity there is 0.00 — different languages). But the
#     model reaches for stock phrasing, so unrelated events collide: "갤럭시
#     A57 최저가 할인" vs "갤럭시 S26 최저가 할인" scores 0.60 on different
#     products. Hence a much higher bar, applied only after judgement.
# Both thresholds are deliberately conservative: a missed duplicate costs one
# redundant row, a false match silently discards a real event forever.
DEDUP_WINDOW_DAYS = int(os.environ.get("DEDUP_WINDOW_DAYS", "7"))
DEDUP_RAW_SIM = float(os.environ.get("DEDUP_RAW_SIM", "0.50"))
DEDUP_KO_SIM = float(os.environ.get("DEDUP_KO_SIM", "0.70"))
_DEDUP_MIN_CHARS = 8          # below this, Jaccard on so few tokens is noise

_TITLE_STRIP = re.compile(r"[^0-9a-z가-힣]+")
_TITLE_BRACKET = re.compile(r"\[[^\]]*\]")


def norm_title(s):
    """Lowercase, drop bracketed prefixes ('[Samsung newsroom (KR)] ') and
    punctuation. Source headlines differ in quotes/dashes far more than in
    words, and stored feed titles carry a label the incoming item lacks."""
    return _TITLE_STRIP.sub(" ", _TITLE_BRACKET.sub(" ", (s or "").lower())).strip()


def _title_sets(s):
    """(character 3-grams, word set) of a normalised title.
    Character n-grams carry Korean, where whitespace tokens are unreliable
    (particles glue onto nouns); word tokens carry English, where they are
    robust to word order. Comparing on the better of the two covers both."""
    n = norm_title(s)
    if len(n.replace(" ", "")) < _DEDUP_MIN_CHARS:
        return None
    flat = n.replace(" ", "")
    return ({flat[i:i + 3] for i in range(len(flat) - 2)},
            {w for w in n.split() if len(w) > 1})


def _jaccard(a, b):
    return len(a & b) / len(a | b) if (a and b) else 0.0


def norm_url(u):
    """Article URL without scheme, 'www.', query string, fragment or trailing
    slash — the same piece re-syndicated picks up ?utm_source=... every time."""
    u = (u or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = u.split("#", 1)[0].split("?", 1)[0]
    return u.rstrip("/")


class DupIndex:
    """Answers 'have we already stored this story?' for one collector run.

    Seeded with everything in events.json, then fed each event the run stores,
    so the first source wins both against history and within the run itself —
    including across the two collectors, since they run in sequence and each
    re-reads the file the other just wrote.
    """

    def __init__(self, events, window_days=None):
        self.window = DEDUP_WINDOW_DAYS if window_days is None else window_days
        self.rows = []
        self.urls = {}
        for e in events or []:
            self.add(e)

    def add(self, event):
        u = norm_url(event.get("raw_url"))
        if u:
            self.urls.setdefault(u, event)
        self.rows.append({
            "date": parse_date(event.get("date")),
            "captured": parse_date(event.get("captured_date")),
            "raw": _title_sets(event.get("raw_title")),
            "ko": _title_sets(event.get("title")),
            "event": event,
        })

    @staticmethod
    def note_coverage(matched):
        """Record that one more source told the story `matched` already holds.

        How many outlets picked a story up is a size signal, and it is the only
        one available that does not come from traffic — so unlike anything
        derived from the move itself, it can be fed to a judge or a fit without
        making the result circular. The count was being thrown away: the
        collectors tallied suppressed duplicates per query/feed, which says
        which QUERY is redundant, but nothing about which EVENT was widely
        reported.

        Starts at 1 (the source that got there first), so the number reads as
        "how many sources covered this", not "how many were discarded".
        """
        if isinstance(matched, dict):
            matched["coverage_count"] = int(matched.get("coverage_count") or 1) + 1

    def _in_window(self, row, anchor):
        if anchor is None:
            # A candidate with no publish date was still fetched today, and
            # that is what its stored date will be — so compare against today's
            # window, not against all of history. Returning True here meant a
            # feed item lacking a pubDate was matched against two years of
            # events, where a chance similarity is far likelier.
            anchor = parse_date(today_iso())
        for d in (row["date"], row["captured"]):
            if d is not None and abs((anchor - d).days) <= self.window:
                return True
        return False

    def find(self, raw_title=None, ko_title=None, url=None, anchor=None,
             raw_sim=None, ko_sim=None):
        """Return (matched_event, reason, score) for the first stored event
        this one duplicates, or None. `anchor` is the candidate's own date —
        its publish date pre-judgement, its event date after."""
        u = norm_url(url)
        if u and u in self.urls:
            return (self.urls[u], "url", 1.0)
        a = parse_date(anchor) if isinstance(anchor, str) else anchor
        want_raw = DEDUP_RAW_SIM if raw_sim is None else raw_sim
        want_ko = DEDUP_KO_SIM if ko_sim is None else ko_sim
        cand_raw = _title_sets(raw_title) if raw_title else None
        cand_ko = _title_sets(ko_title) if ko_title else None
        if not cand_raw and not cand_ko:
            return None
        for row in self.rows:
            if not self._in_window(row, a):
                continue
            if cand_raw and row["raw"]:
                s = max(_jaccard(cand_raw[0], row["raw"][0]),
                        _jaccard(cand_raw[1], row["raw"][1]))
                if s >= want_raw:
                    return (row["event"], "raw_title", round(s, 2))
            if cand_ko and row["ko"]:
                s = max(_jaccard(cand_ko[0], row["ko"][0]),
                        _jaccard(cand_ko[1], row["ko"][1]))
                if s >= want_ko:
                    return (row["event"], "title", round(s, 2))
        return None


def clip_sentence(text, limit=400):
    """Trim to <= limit chars without cutting mid-word.
    Prefer ending at the last sentence boundary; otherwise the last word."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    if cut >= limit * 0.5:
        return head[:cut + 1].strip()
    sp = head.rfind(" ")
    return (head[:sp].strip() if sp > 0 else head.strip()) + "…"


# --- Priority topics (interests.txt) — folded into the judgement prompt so
# both collectors treat these subjects as especially relevant if related. ---
def load_interests():
    path = INTERESTS_FILE
    out = []
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    except Exception:
        pass
    return out

INTERESTS = load_interests()


# --- queries.txt ('category | query text') — shared by collect_news.py,
# collect_gdelt.py and optimize.py so all three read the exact same file the
# exact same way. ---
def keyword_pass(text, keep, drop):
    """The free pre-filter both collectors run before spending an LLM call.

    Drop wins over keep: one blocked term rejects the item however many keep
    terms it also matches. Lived in collect_news.py as keyword_verdict() and in
    collect_feeds.py as relevant() — byte-identical bodies under two names,
    which is how the Samsung-KR pre-filter bug survived: the fix went into one
    copy. The keyword LISTS stay per-collector (kw_news.txt / kw_feeds.txt);
    only the rule is shared.
    """
    t = (text or "").lower()
    if any(k in t for k in drop):
        return False
    return any(k in t for k in keep)


def perf_counter():
    """A fresh per-source counter row: raw -> dup -> kw_pass -> kept.

    optimize.py reads these field names out of query_performance.json and
    feed_performance.json to compute kw_pass_rate / keep_rate / near_dup_rate,
    so the two collectors must spell them identically or a rate silently reads
    as zero.
    """
    return {"raw": 0, "dup": 0, "dup_near": 0, "kw_pass": 0, "kept": 0}


def load_queries_tagged(path=None, categories=None):
    """Returns [(category, query_text), ...] in file order.

    Pass `categories` to fold anything outside that set into "other".
    optimize.py used to do that in a wrapper of the same name, so two different
    functions called load_queries_tagged were live at once and the collectors
    saw a category optimize.py would have normalised away.
    """
    path = path or QUERIES_FILE
    out = []
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cat, q = [p.strip() for p in line.split("|", 1)] if "|" in line else ("other", line)
            if q:
                out.append((cat if not categories or cat in categories else "other", q))
    except Exception:
        pass
    return out

def load_queries(path=None):
    """Query text only (category tag stripped) — for collectors that just
    fetch with these queries and don't need the category (optimize.py is the
    only caller that needs load_queries_tagged() directly, for tuning)."""
    out = [q for _, q in load_queries_tagged(path)]
    return out or ["samsung", "samsung galaxy", "smartphone market", "ecommerce"]


# --- kw_news.txt / kw_feeds.txt ('KEEP' lines, then a '# ---DROP---' marker
# line, then 'DROP' lines) — shared by collect_news.py, collect_feeds.py and
# optimize.py. ---
def load_kw_file(path):
    keep, drop, in_drop = [], [], False
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if "---DROP---" in line:
                    in_drop = True
                continue
            (drop if in_drop else keep).append(line.lower())
    except Exception:
        return [], []
    return keep, drop

# Bumped whenever FILTER_SYSTEM changes in a way that could move the labels.
# Stamped onto every event as `prompt_version`, because otherwise "did the new
# wording help?" is unanswerable: the ledger mixes events judged under every
# version of the prompt it has ever had, and averaging across them hides any
# improvement inside the old ones.
#   1 — everything up to 2026-08-24 (no stamp on those events; treated as 1)
#   2 — 2026-08-25: anchored strength/confidence scales, calibration note
PROMPT_VERSION = 3


FILTER_SYSTEM = (
 "Judge if this news item could plausibly affect samsung.com web traffic or "
 "revenue (direct or indirect). Reject generic PR, gossip, stock noise, "
 "unrelated same-name entities.\n"
 "RULES:\n"
 "1) Keep SPECIFIC dated events (launch, regulation, named report, "
 "supply-chain/market shift) AND general/gradual trend analysis backed by "
 "REALIZED data (e.g. a market-research firm's report on a structural shift "
 "that has ALREADY happened/been measured), even without one single anchor "
 "date. Recurring seasonal topics (holiday shopping, back-to-school) are "
 "fine too if there's a real data point or finding attached, not just a "
 "generic mention.\n"
 "2) REJECT forecasts/projections/predictions about the future (\"expected "
 "to grow to X by 2030\", \"market forecast to reach Y\", analyst/industry "
 "outlook pieces) and REJECT rumors/leaks/unconfirmed reports about a "
 "not-yet-official product (leaked pricing, leaked launch date, \"sources "
 "say\"). Reasoning like \"this forecast/leak means traffic is already "
 "shifting in anticipation\" is too speculative to keep. This does NOT "
 "apply to a company's own OFFICIAL confirmed announcement of a future "
 "launch/event (e.g. Samsung officially announcing a product ships on a "
 "specific date) — that's a real, dated corporate action and should be kept.\n"
 "3) 'date' = when the event/phenomenon ACTUALLY began/took effect (not the "
 "article's publish date) if there is one. For general trend analysis with "
 "no single event date, use the report's publish date instead. These items "
 "were all published within the last few days — TODAY'S DATE IS GIVEN BELOW. "
 "Never date an item to a year other than the current one unless the text "
 "itself states an explicit earlier date; when the text gives no date at all, "
 "use today's date. Never return a date in the future.\n"
 "4) KEEP dated stats/surveys on how people discover/research/buy electronics "
 "(retail-channel share, brand-site vs marketplace behavior, social product "
 "discovery, AI-shopping adoption, market research reports) — as long as "
 "they report REALIZED findings, not a forward projection (see rule 2).\n"
 "Respond with ONLY this JSON, no markdown:\n"
 '{"relevant":true|false,"date":"YYYY-MM-DD",'
 '"scope":[the countries THIS article is about, as Korean country names '
 '("영국","독일","인도"). Use exactly ["전체"] when it applies everywhere '
 'rather than to particular countries. Never answer "worldwide"/"WW"/"global", '
 'and do not pad the list with countries the article does not mention. If the '
 'article only identifies a region and not the countries within it, name the '
 'region instead ("유럽","아시아","중동") — do not guess which countries it '
 'means],'
 '"division":[MX=mobile/phones (Apple,Xiaomi,vivo,OPPO-relevant),'
 'VD=TV/display (LG,TCL,Hisense-relevant),DA=home appliances (LG,Whirlpool,'
 'Bosch-relevant); empty if none],"kpi":[from Impression,Click,Traffic,Order,CVR,Revenue,AOV],'
 '"title":"<=12 words",'
 '"description":"THE SUMMARY. 1-3 Korean sentences saying what the article '
 'reports — facts only: what happened, who did it, when/where, any numbers. '
 'Do NOT put any samsung.com interpretation here; that belongs in impact. '
 'Stop at one sentence if the article says only one thing.",'
 '"impact":"THE INFERENCE — your reasoning, not the article\'s. 1-2 Korean '
 'sentences on how this could move samsung.com WEB TRAFFIC (more/fewer '
 'visits, how people find or reach the site, session behavior) and WHY. Not '
 'a general claim about purchase decisions or consumer behavior.",'
 '"impact_direction":'
 '"+ or - ONLY — does this move samsung.com traffic up or down? There is no '
 'neutral and no unknown: every external factor tips one way, even slightly. '
 'When you genuinely cannot tell, pick the more likely side and say so in '
 'confidence (low), which is the field for exactly that doubt. Do not use '
 'the middle as a way out of deciding.","impact_horizon":"immediate|weeks|months",'
 '"impact_strength":"1-5, HOW MANY samsung.com visits this moves. Anchor to '
 'these, do not average toward the middle: 5 = samsung.com is itself the '
 'subject and many visitors are directly affected (a Samsung flagship launch '
 'or preorder opening, a samsung.com outage, a site-wide Samsung sale) — rare. '
 '4 = a named, dated event that clearly redirects buying attention in a market '
 'Samsung sells in (a major rival flagship launch, a platform change adding or '
 'removing a large traffic source). 3 = ordinary industry news that plausibly '
 'nudges interest (a mid-tier product, a regional promotion, a research report '
 'with measured data). 2 = tangential or slow (component pricing, a niche '
 'market, a small vendor). 1 = barely touches samsung.com traffic. Test: if '
 'you cannot name who would visit samsung.com differently because of this, it '
 'is at most 2.",'
 '"confidence":"high|med|low — YOUR CERTAINTY that this impact_direction/'
 'impact_strength judgement is correct (NOT the article\'s factual accuracy, '
 'NOT consistency with any traffic trend). high = the causal path is direct '
 'and already established: samsung.com is named, or this is a confirmed dated '
 'corporate action in a market Samsung sells in. med = plausible but you are '
 'inferring a step (readers get more interested, therefore they visit). low = '
 'speculative: general industry commentary, an effect that depends on how '
 'other companies react, or you are unsure of the DIRECTION itself. '
 'STRENGTH AND CONFIDENCE ARE INDEPENDENT — do not let them track each other. '
 'A rival flagship launch can be strength 4 with confidence low when you '
 'cannot tell whether it pulls visitors away or lifts interest in the whole '
 'category. A small samsung.com banner change can be strength 2 with '
 'confidence high. Use low regularly; never using it means you are reporting '
 'size, not certainty.",'
 '"axis":"' + AXIS_SPEC + '"}\n'
 'title/impact/description IN KOREAN (한국어), with plain 다/했다/이다 endings (NOT polite 요/습니다) and SIMPLE everyday words — explaining to a colleague, not writing a report. description is the summary and impact is your inference: do not repeat one inside the other. If not relevant: {"relevant":false}.'
)


def _interest_note():
    return ("\n\nPRIORITY TOPICS (treat as especially relevant if related): "
            + ", ".join(INTERESTS)) if INTERESTS else ""


_calib_note_cache = {}


def _calibration_note():
    """Tell the model how its own past labels turned out.

    Two separate pieces, with very different safety profiles:

    * DISTRIBUTION — how the strength values it has already assigned are
      spread. This reads only the ledger's own labels, never traffic, so
      there is no way for it to smuggle an outcome into a prediction. It is
      always included: the observed problem is that 58% of events land on 3
      and "low" confidence has never once been used, which is a scale-usage
      failure the model can fix without knowing anything about traffic.

    * OUTCOMES — what the labels turned out to be worth (조정강도). Learning
      from PAST outcomes to label FUTURE articles is ordinary calibration,
      not circular: the traffic being predicted has not happened yet. But it
      is only worth teaching if the mapping carries signal, and right now the
      gap between predicted and observed strength (1.45) is WIDER than the
      gap you would get by shuffling the labels (1.37). Feeding that back
      would teach one kind of noise in place of another. So this half is
      gated on convergence.informative and stays silent until the labels beat
      chance — at which point it turns itself on.
    """
    if "note" in _calib_note_cache:
        return _calib_note_cache["note"]
    parts = []
    try:
        ev = read_json(EVENTS_FILE, []) or []
        st = {}
        conf = {}
        for e in ev:
            try:
                k = max(1, min(5, int(e.get("impact_strength") or 0)))
            except Exception:
                continue
            st[k] = st.get(k, 0) + 1
            c = (e.get("confidence") or "").strip().lower()
            if c:
                conf[c] = conf.get(c, 0) + 1
        n = sum(st.values())
        if n >= 50:
            spread = ", ".join(f"{k}:{st.get(k,0)*100//n}%" for k in range(1, 6))
            cs = ", ".join(f"{k}:{v*100//max(1,sum(conf.values()))}%"
                           for k, v in sorted(conf.items()))
            parts.append(
                f"\n\nCALIBRATION — how you have been using these scales so far "
                f"({n} past items). impact_strength: {spread}. confidence: {cs}. "
                f"A scale bunched on one value carries no information. Judge each "
                f"item on its own merits, but do not round toward the middle: if an "
                f"item is genuinely marginal say so with a low number and low "
                f"confidence, and reserve the top of the range for the rare item "
                f"that earns it.")
    except Exception:
        pass
    try:
        sc = read_json(PREDICTION_SCORES_FILE, {}) or {}
        cal = sc.get("strength_calibration") or {}
        conv = cal.get("convergence") or {}
        by_pred = cal.get("by_predicted") or {}
        if conv.get("informative") and by_pred:
            rows = ", ".join(f"{k}->{v.get('observed_median')}" for k, v in sorted(by_pred.items()))
            parts.append(
                f"\n\nOUTCOMES — for past items whose effect window has closed, the "
                f"strength you assigned versus what the traffic move actually came to "
                f"on the same 1-5 scale: {rows}. Where those differ, your scale is "
                f"off in that direction; correct for it.")
    except Exception:
        pass
    note = "".join(parts)
    _calib_note_cache["note"] = note
    return note


def _today_note():
    """The single most important line for date accuracy.

    Without it the model has no clock and anchors extracted dates to its
    training era: 291 of 325 auto-collected events (90%) were stored with a
    'date' more than a YEAR before the day they were captured — an article
    about the Galaxy Z Fold 8, fetched 2026-08-04, was dated 2024-08-22.
    Every period filter and the whole 3-axis attribution key off that field,
    so the dashboard was analysing the wrong dates entirely.
    """
    return "\n\nTODAY'S DATE IS " + today_iso() + " (UTC)."


def _item_block(article):
    # Most article summaries are already short (NewsAPI/RSS truncate their
    # own way), but clip defensively — an occasional long one would otherwise
    # bloat every judgement call's token cost for no benefit to the verdict.
    # PUBLISHED is included when the source gave us one: it is ground truth
    # the model should anchor 'date' to, and it is what clean_date() falls
    # back to when the model's answer is implausible.
    pub = article.get("date") or ""
    return ("TITLE: " + article["title"] +
            "\nSUMMARY: " + clip_sentence(article["desc"], 400) +
            (f"\nPUBLISHED: {pub}" if pub else "") +
            "\nSOURCE: " + article["source"])


def _build_filter_prompt(article):
    return (FILTER_SYSTEM + _interest_note() + _calibration_note() + _today_note()
            + "\n\nITEM:\n" + _item_block(article))


# How many articles to judge per request. The instruction block above is ~1.1k
# tokens and used to be re-sent for every single article, so ~93% of all input
# tokens were the same text over and over; batching amortises it across BATCH
# items. It also divides the REQUEST count by the same factor, which matters
# more than the tokens: requests are what the free tiers actually ration, and
# Mistral's 2/min limit is paid per request (31s sleep each).
# Kept modest (5) on purpose — a bigger batch saves less and less (the prefix
# is already amortised) while making a single malformed response cost more.
BATCH = max(1, int(os.environ.get("LLM_BATCH", "5")))


def _build_batch_prompt(articles):
    """Same instructions, N items, one JSON array back — index-aligned."""
    items = "\n\n".join(f"[{i+1}]\n{_item_block(a)}" for i, a in enumerate(articles))
    return (FILTER_SYSTEM + _interest_note() + _calibration_note() + _today_note() +
            f"\n\nYou will judge {len(articles)} items, numbered [1]..[{len(articles)}]. "
            f"Apply the rules above to EACH item INDEPENDENTLY.\n"
            f'Respond with ONLY a JSON array of exactly {len(articles)} objects, in the '
            f'SAME ORDER as the items, each object being the verdict for that item '
            f'(use {{"relevant":false}} for ones that fail). Add "i": the item number '
            f'([1]..[{len(articles)}]) that verdict is for — it is checked, and a verdict '
            f'filed under the wrong item is worse than no verdict. No other extra keys, '
            f'no wrapper object, no markdown.\n\nITEMS:\n' + items)


def call_openai_chat_json(url, api_key, model, prompt, max_tokens=600, temperature=0,
                          timeout=30, extra=None):
    """POST to an OpenAI-compatible /chat/completions endpoint (Groq, Mistral).
    Returns the raw parsed JSON dict (any schema), or None on empty output.

    extra: provider-specific body fields (e.g. Groq's reasoning_effort). Kept
    separate so an unsupported field can be dropped and the call retried."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature, "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if extra:
        payload.update(extra)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}",
                 "User-Agent": "scom-external/1.0 (+https://github.com/hyunho0812/scom-external)"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    out = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "").strip()
    out = out.replace("```json", "").replace("```", "").strip()
    if not out:
        return None
    return json.loads(out)


def gemini_filter(prompt, max_tokens=600):
    """1st choice. Full relevance/category/date/impact judgement via Gemini's
    free tier. Takes a built prompt (single-item or batch) and returns the
    parsed JSON, or None if unavailable."""
    if not GEMINI_KEY or _gemini_off["flag"]:
        _bump("gemini", "skipped_off")
        return None
    _bump("gemini", "attempt")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens,
                              "responseMimeType": "application/json",
                              "thinkingConfig": {"thinkingBudget": 0}},
    }).encode()
    try:
        req = urllib.request.Request(url, data=body,
              headers={"Content-Type": "application/json",
                       "User-Agent": "scom-external/1.0 (+https://github.com/hyunho0812/scom-external)"},
              method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content", {}) or {}).get("parts", [{}])
        text = "".join(p.get("text", "") for p in parts).strip()
        text = text.replace("```json", "").replace("```", "").strip()
        time.sleep(6.0)  # avoid per-minute limit (~10/min)
        if not text:
            print(f"  Gemini returned empty text (finishReason={cand.get('finishReason')}) "
                  f"— treating as unavailable for this item.")
            _bump("gemini", "empty")
            return None
        verdict = json.loads(text)
        _bump("gemini", "ok")
        return verdict
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if e.code == 429:
            print("  Gemini quota hit (429) — falling back to Groq.")
            _gemini_off["flag"] = True
            _bump("gemini", "http_429")
        elif e.code in (401, 403):
            print(f"  Gemini auth/permission error {e.code} — {body} "
                  f"— disabling Gemini for the rest of this run.")
            _gemini_off["flag"] = True
            _bump("gemini", "http_auth")
        else:
            print(f"  Gemini error {e.code} — {body}")
            _bump("gemini", "http_other")
        return None
    except Exception as e:
        print("  Gemini parse error:", e)
        _bump("gemini", "exception")
        return None


# Groq's default model (openai/gpt-oss-120b) is a REASONING model: it emits
# reasoning tokens before the answer, and those count against max_tokens. At
# the shared max_tokens=600 the reasoning can consume the whole budget, so
# `choices[0].message.content` comes back empty, call_openai_chat_json returns
# None, and the chain silently falls through to Mistral.
#
# That matches the observed record exactly: Groq entered the chain on
# 2026-07-06 already on gpt-oss-120b and has produced ZERO kept events since,
# while `check.py health` keeps reporting it "ok" (that check is a metadata GET —
# it never generates, so it cannot see this). It is the same failure the
# project already fixed for Gemini with thinkingConfig.thinkingBudget=0; the
# equivalent was simply never applied to Groq.
#
# So: cap the reasoning with reasoning_effort and give the call enough room for
# reasoning AND the JSON verdict. reasoning_effort is Groq-specific, so if this
# Groq account/model rejects it (HTTP 400), _groq_no_extra latches and every
# later call drops the field instead of failing outright.
GROQ_MAX_TOKENS = int(os.environ.get("GROQ_MAX_TOKENS", "1500"))
GROQ_REASONING_EFFORT = os.environ.get("GROQ_REASONING_EFFORT", "low")
_groq_no_extra = {"flag": False}


def _groq_extra():
    """Groq-only body fields, or None once the endpoint has rejected them."""
    if _groq_no_extra["flag"] or not GROQ_REASONING_EFFORT:
        return None
    if "gpt-oss" not in GROQ_MODEL and "reason" not in GROQ_MODEL:
        return None  # not a reasoning model — nothing to cap
    return {"reasoning_effort": GROQ_REASONING_EFFORT}


def groq_filter(prompt, max_tokens=None):
    """2nd choice. Same judgement as gemini_filter, served by Groq. Used only
    when Gemini is unavailable, so a Gemini outage no longer degrades
    classification to hardcoded defaults."""
    if not GROQ_KEY or _groq_off["flag"]:
        _bump("groq", "skipped_off")
        return None
    _bump("groq", "attempt")
    # gpt-oss spends part of the budget on reasoning tokens, so a batch needs
    # headroom beyond what the verdicts themselves take (see GROQ_MAX_TOKENS).
    cap = max(GROQ_MAX_TOKENS, max_tokens or 0)
    try:
        verdict = call_openai_chat_json(
            "https://api.groq.com/openai/v1/chat/completions", GROQ_KEY, GROQ_MODEL,
            prompt, max_tokens=cap, extra=_groq_extra())
        time.sleep(2.0)  # 30 RPM free limit
        # A falsy verdict here means the call succeeded but produced nothing
        # usable. That used to increment no counter at all, so the run looked
        # like Groq had never been asked.
        _bump("groq", "ok" if verdict else "empty")
        return verdict
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if e.code == 400 and _groq_extra():
            # The reasoning_effort field isn't accepted here. Latch it off and
            # retry this same item plainly, so adding the field can never make
            # Groq worse than it was without it.
            print(f"  Groq rejected reasoning_effort (400) — {body} "
                  f"— retrying without it and dropping it for this run.")
            _groq_no_extra["flag"] = True
            try:
                verdict = call_openai_chat_json(
                    "https://api.groq.com/openai/v1/chat/completions", GROQ_KEY,
                    GROQ_MODEL, prompt, max_tokens=cap)
                time.sleep(2.0)
                _bump("groq", "ok" if verdict else "empty")
                return verdict
            except Exception as e2:
                print("  Groq retry without reasoning_effort failed:", e2)
                _bump("groq", "exception")
                return None
        if e.code == 429:
            print("  Groq quota hit (429) — falling back to Mistral.")
            _groq_off["flag"] = True
            _bump("groq", "http_429")
        elif e.code in (401, 403):
            print(f"  Groq auth/permission error {e.code} — {body} "
                  f"— disabling Groq for the rest of this run.")
            _groq_off["flag"] = True
            _bump("groq", "http_auth")
        else:
            print(f"  Groq filter error {e.code} — {body}")
            _bump("groq", "http_other")
        return None
    except Exception as e:
        print("  Groq filter failed:", e)
        _bump("groq", "exception")
        return None


def mistral_filter(prompt, max_tokens=600):
    """3rd choice (last resort). Same judgement as gemini_filter/groq_filter,
    served by Mistral. Note: Mistral's free Experiment-tier requests may be
    used to train their models — fine here since this only ever handles
    public news/RSS text."""
    if not MISTRAL_KEY or _mistral_off["flag"]:
        _bump("mistral", "skipped_off")
        return None
    _bump("mistral", "attempt")
    try:
        verdict = call_openai_chat_json(
            "https://api.mistral.ai/v1/chat/completions", MISTRAL_KEY, MISTRAL_MODEL,
            prompt, max_tokens=max_tokens)
        # Mistral free tier: 2 req/min — 31s gives a safety margin. This sleep
        # is why batching matters so much for runtime: it is paid per REQUEST,
        # so a batch of 5 costs one 31s wait instead of five.
        time.sleep(31.0)
        _bump("mistral", "ok" if verdict else "empty")
        return verdict
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if e.code == 429:
            print("  Mistral quota hit (429) — no LLM judge left this run.")
            _mistral_off["flag"] = True
            _bump("mistral", "http_429")
        elif e.code in (401, 403):
            print(f"  Mistral auth/permission error {e.code} — {body} "
                  f"— disabling Mistral for the rest of this run.")
            _mistral_off["flag"] = True
            _bump("mistral", "http_auth")
        else:
            print(f"  Mistral filter error {e.code} — {body}")
            _bump("mistral", "http_other")
        return None
    except Exception as e:
        print("  Mistral filter failed:", e)
        _bump("mistral", "exception")
        return None


def _korean_fields_ok(verdict):
    """The prompt requires title/impact/description IN KOREAN. Mistral in
    particular has been observed to comply for title/description but slip
    English into 'impact' — silently storing that would violate the
    no-English-text policy, so treat it the same as a failed judgement and
    let the chain fall through to the next LLM."""
    if not verdict.get("relevant", True):
        return True  # nothing to check when the item was judged not relevant
    for field in ("title", "impact", "description"):
        val = verdict.get(field)
        if val and not has_korean(val):
            return False
    return True


def _direction_ok(verdict):
    """The prompt now allows only "+" or "-". Anything else — an omitted field,
    a leftover "neutral"/"unknown", a sentence instead of a sign — is a verdict
    that did not decide, and the collectors used to paper over it with the
    literal string "unknown". Treat it like the non-Korean case instead: the
    item is re-judged on its own, then through the rest of the chain, and only
    skipped if nobody will commit to a side. Never stored as a default."""
    if not verdict.get("relevant", True):
        return True
    return bool(clean_direction(verdict.get("impact_direction")))


def _reject_dir(prov, model):
    print(f"  {model} returned no usable impact_direction — "
          f"treating as a failed judgement, trying next LLM.")
    _bump(prov, "ok", -1)
    _bump(prov, "dir_reject")


def _chain():
    """The judgement chain, resolved at call time rather than captured at
    import. Binding these once at module level would freeze whatever the
    functions were then — surprising for anything that patches or wraps a
    provider (tests do exactly this), and a silent no-op when it happens."""
    return ((gemini_filter, GEMINI_MODEL, "gemini"),
            (groq_filter, GROQ_MODEL, "groq"),
            (mistral_filter, MISTRAL_MODEL, "mistral"))


def _reject_ko(prov, model):
    print(f"  {model} returned non-Korean title/impact/description — "
          f"treating as a failed judgement, trying next LLM.")
    # Re-attribute: the provider already scored an "ok" for answering, but the
    # chain is throwing that answer away. Without this the counters would
    # report a healthy provider that in fact produces nothing usable while
    # burning a full prompt's worth of tokens.
    _bump(prov, "ok", -1)
    _bump(prov, "ko_reject")


def llm_filter(article):
    """Run the full judgement chain: Gemini -> Groq -> Mistral. Returns
    (verdict_dict, model_name) or (None, "") if all three are unavailable —
    only then should the caller skip the item rather than store it with
    English text or guessed classification."""
    prompt = _build_filter_prompt(article)
    for fn, model, prov in _chain():
        verdict = fn(prompt)
        if isinstance(verdict, list):  # a provider ignored the single-item shape
            verdict = verdict[0] if len(verdict) == 1 else None
        if verdict is not None and not _korean_fields_ok(verdict):
            _reject_ko(prov, model)
            verdict = None
        if verdict is not None and not _direction_ok(verdict):
            _reject_dir(prov, model)
            verdict = None
        if verdict is not None:
            return verdict, model
    return None, ""


def _align_batch(out, n, prov, model):
    """Re-order verdicts by their echoed "i" (1-based) when that is possible.

    Returns the list to use. Leaves `out` untouched — and counts
    'batch_no_index' — when the indices are absent, out of range, or
    duplicated, since a partial reorder would be a guess."""
    idx = []
    for v in out:
        if not isinstance(v, dict):
            idx = []
            break
        try:
            idx.append(int(v.get("i")))
        except (TypeError, ValueError):
            idx = []
            break
    if len(idx) != n or sorted(idx) != list(range(1, n + 1)):
        _bump(prov, "batch_no_index")
        return out
    if idx != list(range(1, n + 1)):
        print(f"  {model} batch came back in order {idx} — re-aligned by item number.")
        _bump(prov, "batch_reordered")
    seat = [None] * n
    for v, i in zip(out, idx):
        v.pop("i", None)          # not part of the event schema
        seat[i - 1] = v
    return seat


def llm_filter_batch(articles):
    """Judge up to BATCH articles in ONE request. Returns a list of
    (verdict_or_None, model_name) index-aligned with `articles`.

    Falls back to per-item llm_filter() for anything the batch can't settle:
    a provider that returns the wrong number of verdicts, a non-dict entry, or
    an entry whose Korean fields fail the guard. That keeps the batch a pure
    cost optimisation — the worst case is the old per-item behaviour, never a
    dropped or a wrongly-kept article.
    """
    if not articles:
        return []
    if len(articles) == 1:
        return [llm_filter(articles[0])]
    prompt = _build_batch_prompt(articles)
    # Rejects cost ~4 tokens, keeps ~200; budget generously so a batch that
    # happens to be all-keeps can't get truncated mid-array.
    cap = 300 + 320 * len(articles)
    for fn, model, prov in _chain():
        out = fn(prompt, cap)
        if out is None:
            continue
        # Some providers wrap an array in a single-key object despite the
        # instruction; unwrap the obvious cases rather than wasting the call.
        if isinstance(out, dict):
            vals = [v for v in out.values() if isinstance(v, list)]
            out = vals[0] if len(vals) == 1 else None
        if not isinstance(out, list) or len(out) != len(articles):
            got = "not a list" if not isinstance(out, list) else f"{len(out)} verdicts"
            print(f"  {model} batch shape mismatch (expected {len(articles)}, got {got})"
                  f" — falling back to per-item for this batch.")
            _bump(prov, "batch_shape_fail")
            continue
        # The batch is only a cost optimisation if verdict i really is item i.
        # Nothing used to check that: the array was trusted on position alone,
        # so a provider that reordered, or answered about the wrong item,
        # attached one article's judgement to another's title and URL — and it
        # happened (2026-08-07 "How Gemini plans vacation itineraries" was
        # stored describing a Samsung Galaxy launch). Re-order by the echoed
        # "i" when every verdict carries a distinct valid one; that repairs a
        # shuffle outright. If the provider ignored the field, fall through to
        # positional order — the pre-existing behaviour, so this can only help
        # — but record it, because a provider that never echoes is one whose
        # ordering nobody is checking.
        out = _align_batch(out, len(articles), prov, model)
        results, redo = [], []
        for i, v in enumerate(out):
            if not isinstance(v, dict):
                results.append(None); redo.append(i); continue
            if not _korean_fields_ok(v):
                _reject_ko(prov, model)
                results.append(None); redo.append(i); continue
            if not _direction_ok(v):
                _reject_dir(prov, model)
                results.append(None); redo.append(i); continue
            results.append((v, model))
        for i in redo:  # re-judge just the unusable ones, individually
            results[i] = llm_filter(articles[i])
        return results
    # No provider produced a usable batch — fall back entirely.
    return [llm_filter(a) for a in articles]


USAGE_FILE = LLM_USAGE_FILE
USAGE_KEEP_DAYS = 30
_ORDER = (("gemini", "1st"), ("groq", "2nd"), ("mistral", "3rd"))


def diag_summary(label=""):
    """Print [diag] lines for all three providers' usage this run, then persist
    them via save_usage(). Call once at the end of a collector's main()."""
    prefix = f"[{label}] " if label else ""
    for prov, rank in _ORDER:
        s = _STATS[prov]
        print(f"{prefix}[diag] {prov} ({rank}) attempt: {s['attempt']}, ok: {s['ok']}, "
              f"ko_reject: {s['ko_reject']}, empty: {s['empty']}, "
              f"batch_shape_fail: {s['batch_shape_fail']}, "
              f"batch_no_index: {s['batch_no_index']}, "
              f"batch_reordered: {s['batch_reordered']}, "
              f"429: {s['http_429']}, auth: {s['http_auth']}, "
              f"other: {s['http_other']}, exc: {s['exception']}, "
              f"skipped_off: {s['skipped_off']}")
    if label:
        save_usage(label)


def save_usage(stage):
    """Append this run's per-provider counters to data/llm_usage.json.

    One record per collector run (stage = "collect_news" / "collect_feeds"),
    keyed by UTC date so a day with both collectors yields two records. Kept to
    the last USAGE_KEEP_DAYS days' worth. Never raises: telemetry must not be
    able to fail a collection run that otherwise succeeded.
    """
    from datetime import datetime, timezone
    try:
        rec = {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "stage": stage,
            "providers": {p: dict(_STATS[p]) for p, _ in _ORDER},
            # Total HTTP requests this run. This is the number that actually
            # drains the free tiers — and it is NOT items x 3: once a provider
            # 429s, its off flag skips it for the remainder of the run, so the
            # fallback is paid once per run rather than once per item.
            "total_attempts": sum(_STATS[p]["attempt"] for p, _ in _ORDER),
        }
        try:
            hist = json.load(open(USAGE_FILE, encoding="utf-8"))
            if not isinstance(hist, list):
                hist = [hist]
        except Exception:
            hist = []
        hist.append(rec)
        cutoff = sorted({r.get("date", "") for r in hist})[-USAGE_KEEP_DAYS:]
        hist = [r for r in hist if r.get("date", "") in cutoff]
        write_json(USAGE_FILE, hist)
        print(f"  llm usage saved: {USAGE_FILE} ({rec['total_attempts']} API requests this run)")
    except Exception as e:
        print("  llm usage not saved:", e)

