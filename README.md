# samsung.com External Factors — free auto-updating web dashboard

This deploys a public dashboard URL that refreshes itself **every day with no
action from you**. Hosting and automation are free via GitHub Pages + Actions.

A live URL can only be created under your own GitHub account — these steps
produce it in about 15 minutes. After that you never touch it.

---

## What's in this folder
```
index.html                      ← the dashboard (Korean UI, trend graph), auto-generated
data/events.json                ← the event log (seeded with 10 events)
data/feed_state.json            ← remembers seen RSS entries (auto-managed)
scripts/collect.py              ← Layer 1 daily: news API → Claude relevance filter
scripts/collect_firstparty.py   ← Layer 3 daily: platform RSS/changelogs → FREE keyword filter
scripts/collect_stats.py        ← Layer 2 monthly: World Bank stats → slow-trend events
scripts/collect_wiki.py         ← daily: Wikipedia pageviews → competitor trend graph (Samsung/Apple/LG/Whirlpool)
scripts/build.py                ← daily: events.json → index.html (Korean UI: region/country/division/KPI filters)
feeds.txt                       ← first-party source list (edit to manage feeds)
QUARTERLY_REVIEW.md             ← human blind-spot checklist (run once a quarter)
.github/workflows/daily-update.yml ← the free daily cron that runs everything
```

## Three collection layers + a human layer
No single source sees everything. News covers sudden EVENTS but misses slow
STATES (aging) and sub-threshold changes (a tiny ChatGPT UI tweak). So:
1. **Layer 1 — news (daily):** broad pull, Claude filters for relevance.
2. **Layer 3 — first-party feeds (daily):** official platform blogs/release notes,
   so small changes are caught straight from the source, no press needed.
3. **Layer 2 — stats (monthly):** World Bank indicators; emits an event only when
   a slow trend (aging, GDP/capita, internet penetration) crosses a threshold.
4. **Quarterly human review:** `QUARTERLY_REVIEW.md` covers what no feed can —
   brand-new platforms, culture/calendar, quiet competitor moves, slow regulation.

Even with all four, full coverage is impossible — the aim is to make missing
something important *unlikely*, not guaranteed-never.

## How the daily loop works
Every morning GitHub Actions runs on its own:
1. `collect.py` pulls recent articles from a news API (broad — includes noise).
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

### 2. Add your API keys as secrets (both free)
- Repo ▸ Settings ▸ Secrets and variables ▸ Actions ▸ New repository secret.
- `GEMINI_API_KEY` — get it free at aistudio.google.com/apikey (sign in with a
  Google account, "Create API key"; no credit card). This powers the Layer 1
  LLM filter. Free tier ≈ 1,500 requests/day on Flash — plenty here.
- `NEWS_API_KEY` — free at newsapi.org (or adapt collect.py to another source).
- Secrets are encrypted and never appear in the page or logs.
- (Optional) the workflow sets GEMINI_MODEL to gemini-2.5-flash. If Google
  retires that name, change it in the workflow to the current free Flash model
  (e.g. a newer gemini-*-flash / flash-lite).

### 3. Turn on Pages
- Repo ▸ Settings ▸ Pages ▸ Source = "GitHub Actions". Save.

### 4. Run it once
- Repo ▸ Actions ▸ "daily-update" ▸ Run workflow. After it finishes,
  Settings ▸ Pages shows your live URL: `https://<you>.github.io/samsung-external/`.
- That's your team link. The cron (`0 21 * * *` = ~06:00 KST) refreshes it daily.

---

## Costs — everything is free
- GitHub Pages + Actions: free for public repos.
- Layer 1 news: news API free tier + **Gemini free tier** for the LLM filter.
  Hybrid order (keyword pre-filter → Gemini) keeps Gemini calls low so you stay
  inside the free daily quota. If the quota is hit (HTTP 429) or no Gemini key
  is set, it automatically falls back to the keyword decision — never stalls.
- Layer 3 first-party feeds: FREE keyword filter, no API calls.
- Layer 2 stats (World Bank): FREE, no key.
So the whole pipeline runs at $0. Note: free tiers can change their limits/policy
over time, and free-tier inputs (here: public news titles/summaries — nothing
sensitive) may be used by the provider for model improvement.

## Competitor trend graph (Wikipedia pageviews)
The dashboard shows a trend line: Samsung (always, baseline) + the selected
division's competitor total. Data is daily Wikipedia pageviews (collect_wiki.py,
free, no key) for Samsung/Apple/LG/Whirlpool — an interest/attention PROXY, not
real competitor web traffic. Events appear as numbered callout markers mapped to
a list under the graph. Division mapping: MX=Apple, VD=LG, DA=Whirlpool.

## Filter-model status badge (knowing when to swap models)
The dashboard shows a badge with the LLM model the filter uses, whether it's
alive, and when it was last checked. Each daily run, `check_model.py` pings the
Gemini models endpoint for the configured GEMINI_MODEL:
- **green "active ✓"** — model responds, nothing to do.
- **red "RETIRED — update GEMINI_MODEL"** — model returned 404/not-found (Google
  retired it). Swap GEMINI_MODEL in the workflow for a current free Flash model;
  collection keeps running on keyword fallback until you do.
- **amber "no key" / "check failed"** — no Gemini key set, or a transient error.
This is how you catch a model shutdown (like gemini-2.0-flash on 2026-06-01)
without watching Google's changelog yourself — the badge turns red on its own.

## Managing feeds (feeds.txt)
First-party sources live in `feeds.txt`, one per line as `Label | URL`.
Edit that file to add/remove sources — the daily job reads it each run.
Seeded with AI platforms (ChatGPT, Gemini, Claude, Perplexity, Copilot) and
competitors (Apple, LG, Whirlpool). Some vendors lack a stable official RSS;
those lines have a note with a mirror option if one stops working.

## Tuning
- Add/remove countries: edit COUNTRIES in collect.py and REGIONS/COUNTRIES in build.py.
- Broaden/narrow collection: edit QUERIES in collect.py.
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
