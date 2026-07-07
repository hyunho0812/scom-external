# samsung.com External Factors — free auto-updating web dashboard

This deploys a public dashboard URL that refreshes itself **every day with no
action from you**. Hosting and automation are free via GitHub Pages + Actions.

A live URL can only be created under your own GitHub account — these steps
produce it in about 15 minutes. After that you never touch it.

---

## What's in this folder
```
index.html                      <- the dashboard (Korean UI, trend graph), auto-generated
data/events.json                <- the event log (seeded with 10 events)
data/feed_state.json            <- remembers seen RSS entries (auto-managed)
scripts/collect_news.py         <- Layer 1 daily: NewsAPI+GDELT -> keyword pre-filter -> LLM judgement
scripts/collect_feeds.py        <- Layer 2 daily: first-party RSS -> keyword pre-filter -> LLM judgement
scripts/collect_gdelt.py        <- Layer 1a daily: free GDELT news pool (no key)
scripts/collect_imf.py          <- Layer 3 monthly (28th): IMF stats -> country-stats tab
scripts/collect_wiki.py         <- daily: Wikipedia pageviews -> company trend graph
scripts/llm_common.py           <- shared Gemini/Groq/Mistral fallback-chain helpers
scripts/check_model.py          <- daily: health-checks all 3 LLMs -> dashboard badges
scripts/optimize.py             <- daily: Gemini tunes queries.txt/keyword filters
scripts/merge_past_events.py    <- manual tool: merge AI/uploaded event batches
scripts/check_feed_translation.py <- manual diagnostic: audit feed translation quality
scripts/build.py                <- daily: rebuilds index.html from all data files
feeds.txt                       ← first-party source list (edit to manage feeds)
.github/workflows/daily-update.yml ← the free daily cron that runs everything
```

## Three collection layers + a human layer
No single source sees everything. News covers sudden EVENTS but misses slow
STATES (aging) and sub-threshold changes (a tiny ChatGPT UI tweak). So:
1. **Layer 1 - news (daily):** broad pull from NewsAPI+GDELT, Gemini filters for relevance.
2. **Layer 2 - first-party feeds (daily):** official platform blogs/release notes,
   so small changes are caught straight from the source, no press needed.
3. **Layer 3 - IMF stats (monthly):** IMF SDMX monthly indicators (overall/furnishings/housing/communications/recreation CPI, retail sales, labor-force participation) for the country-stats tab. Runs on the 28th for the previous month. (Previously
   a slow trend (aging, GDP/capita, internet penetration) crosses a threshold.

Even with these layers, full coverage is impossible — the aim is to make missing
something important *unlikely*, not guaranteed-never.

## How the daily loop works
Every morning GitHub Actions runs on its own:
1. `collect_news.py` pulls recent articles from a news API (broad — includes noise).
2. Each article goes to Claude, which decides "relevant to samsung.com?" and,
   if yes, tags it (category, scope, direction…). Only relevant items are kept.
3. `build.py` regenerates `index.html`.
4. The page is published to GitHub Pages. Your URL now shows today's view.

The LLM filter is what makes "automatic" usable — the news API alone returns
lots of irrelevant items; Claude drops them before they reach your dashboard.
It is not perfect — skim the list weekly and delete any stragglers from
`data/events.json`.

---

## One-time setup

### 1. Create the repo
- Sign in at github.com ▸ New repository ▸ name it e.g. `samsung-external` ▸
  Public ▸ Create.
- Upload this whole folder's contents (drag the files into the repo's
  "Add file ▸ Upload files", keeping the `scripts/`, `data/`, `.github/` paths).

### 2. Add your API keys as secrets (all free)
- Repo ▸ Settings ▸ Secrets and variables ▸ Actions ▸ New repository secret.
- `GEMINI_API_KEY` — get it free at aistudio.google.com/apikey (sign in with a
  Google account, "Create API key"; no credit card). This powers the Layer 0/1
  LLM filter (1st choice).
- `NEWS_API_KEY` — free at newsapi.org (or adapt collect_news.py to another source).
- `GROQ_API_KEY` — get it free at console.groq.com/keys (sign in with email or
  Google; no credit card). 2nd-choice LLM, used only when Gemini's daily quota
  runs out.
- `MISTRAL_API_KEY` — get it free at console.mistral.ai (no credit card). This is
  the 3rd-choice LLM, used only when BOTH Gemini and Groq are unavailable in the
  same run. Note: Mistral's free "Experiment" tier may use your requests to train
  their models (per Mistral's own help docs) — acceptable here since this only
  ever processes public news/RSS text, never samsung.com's real traffic data.
- So the whole pipeline is 100% LLM-based across three independent free tiers,
  with no non-LLM translation API anywhere.
- Secrets are encrypted and never appear in the page or logs.
- (Optional) the workflow sets GEMINI_MODEL to gemini-2.5-flash, GROQ_MODEL to
  openai/gpt-oss-120b, and MISTRAL_MODEL to mistral-small-latest. If any
  provider retires that model name, change it in the workflow to a current
  free equivalent — `scripts/check_model.py` checks all three daily and the
  dashboard badge turns red ("retired") if one needs swapping.

### Free-tier comparison (as of 2026-07)
All figures are published limits and change without notice — the dashboard's
model-status badges are the source of truth for whether each is actually
working right now.

| | Gemini (1st) | Groq (2nd) | Mistral (3rd) |
|---|---|---|---|
| Model used here | gemini-2.5-flash | openai/gpt-oss-120b | mistral-small-latest |
| Requests/min | ~10–15 | 30 | **2** (tight — only hit as last resort) |
| Requests/day | ~1,500 (varies) | 1,000 | not published (token-capped instead) |
| Token budget | large context (~1M) | 8K/min, 200K/day | **~1B/month** (most generous by far) |
| No credit card | ✓ | ✓ | ✓ |
| Data-training opt-out | only outside EU/UK/EEA | usually no training | **requests may train Mistral's models** |
| Durability note | Google cut free limits once already (late 2025) | occasionally deprecates/renames models (check console.groq.com/docs/deprecations) | tier has had no recorded pricing changes |

Practical read: Gemini and Groq handle almost all daily volume between them.
Mistral's 2 RPM makes it unsuitable as anything but a rarely-hit last resort,
but its huge monthly token budget means it won't run dry even if it ends up
carrying a full day's leftover translations once in a while.

### 3. Turn on Pages
- Repo ▸ Settings ▸ Pages ▸ Source = "GitHub Actions". Save.

### 4. Run it once
- Repo ▸ Actions ▸ "daily-update" ▸ Run workflow. After it finishes,
  Settings ▸ Pages shows your live URL: `https://<you>.github.io/samsung-external/`.
- That's your team link. The cron (`0 21 * * *` = ~06:00 KST) refreshes it daily.

---

## Costs — everything is free
- GitHub Pages + Actions: free for public repos.
- Layer 1 news + Layer 2 first-party feeds: both use the SAME free LLM
  judgement chain (keyword pre-filter → Gemini → Groq → Mistral, all free
  tiers, no card). Hybrid order (keyword first) keeps LLM calls low so you
  stay inside each provider's free daily quota. If Gemini's quota is hit
  (HTTP 429), Groq judges instead; if Groq also fails, Mistral does — only if
  ALL THREE are unavailable is an item skipped, rather than stored with
  English text or guessed classification.
- Layer 3 stats (IMF SDMX): FREE, no key. Monthly. World Bank (annual) was removed.
So the whole pipeline runs at $0. Note: free tiers can change their limits/policy
over time, and free-tier inputs (here: public news titles/summaries — nothing
sensitive) may be used by the provider for model improvement.

## Company trend graph (Wikipedia pageviews)
The dashboard shows a trend line: Samsung (always, baseline) + the selected
division's company total. Data is daily Wikipedia pageviews (collect_wiki.py,
free, no key) for Samsung/Apple/LG/Whirlpool — an interest/attention PROXY, not
real company web traffic. Events appear as numbered callout markers mapped to
a list under the graph. Division mapping: MX=Apple, VD=LG, DA=Whirlpool.

## Model-status badges (knowing when to swap models)
The dashboard shows three badges — one per LLM in the judgement chain
(Gemini, Groq, Mistral) — each showing the model name, whether it's alive,
and when it was last checked. Each daily run, `check_model.py` pings all
three providers' model-info endpoints (a cheap GET, no generation):
- **green "정상 ✓"** — model responds, nothing to do.
- **red "종료됨 — 모델 교체 필요"** — the model 404s (the provider retired it).
  Swap that provider's *_MODEL env var in the workflow for a current model;
  collection keeps running on the next LLM in the chain until you do.
- **amber "키 없음"** — no API key set for that provider, or a transient error.
This is how you catch a model retirement (like Groq deprecating
llama-3.3-70b-versatile in June 2026) without watching each provider's
changelog yourself — the relevant badge turns red on its own.

## News sources (NewsAPI + GDELT)
Two news sources feed the same keyword-prefilter → LLM-judgement pipeline:
- NewsAPI (key required, 100 req/day free) — collect_news.py, 10 queries × 10 articles.
- GDELT (no key, effectively unlimited) — collect_gdelt.py writes data/raw_gdelt.json,
  which collect_news.py also reads. GDELT monitors worldwide news, updates every 15 min,
  and has no hard quota — so it broadens coverage without touching NewsAPI's daily cap.
Both are merged and de-duplicated before filtering.

## First-party translation (MyMemory, free)
First-party feed items (English titles/summaries) are auto-translated to Korean
via the free MyMemory API (no key, no signup; ~5,000 words/day anonymous). If a
call fails or the limit is hit, the original English text is used instead. The
English original is always kept in raw_title / raw_desc / raw_url regardless.
Machine translation is rougher than the Gemini-written news summaries, but keeps
the dashboard Korean without extra cost.

## Managing interest keywords (interests.txt)
Topics you especially want to track live in `interests.txt`, one per line
('#' = comment). These keywords (default: AI, LLM, GEO, zero-click) are merged
into the news search queries and the keyword pre-filter, and passed to the Gemini
filter as priority topics. Edit the file to tune what the collector pays extra
attention to — same idea as feeds.txt, but for subject keywords.

## Managing feeds (feeds.txt)
First-party sources live in `feeds.txt`, one per line as `Label | URL`.
Edit that file to add/remove sources — the daily job reads it each run.
Seeded with AI platforms (ChatGPT, Gemini, Claude, Perplexity, Copilot) and
companies (Apple, LG, Whirlpool). Some vendors lack a stable official RSS;
those lines have a note with a mirror option if one stops working.

## Tuning
- Add/remove countries: edit COUNTRIES in collect_news.py and REGIONS/COUNTRIES in build.py.
- Broaden/narrow collection: edit QUERIES in collect_news.py.
- Change refresh time: edit the cron in daily-update.yml (UTC).
- Make repo private: works, but Pages may need a paid plan for private repos —
  keep it public, or host the built index.html elsewhere.

## Honesty notes for the team
- "Relevant" is decided by an LLM, so an occasional miss/false-positive happens.
- impact_direction is an estimate. There are no attribution percentages in this
  dashboard by design — it shows what happened and a directional read, not a
  causal split.
- This tracks EXTERNAL events only. Joining to internal samsung.com traffic/
  revenue is a separate, later step done in your own secure environment.
