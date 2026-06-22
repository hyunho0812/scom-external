# Quarterly blind-spot review — samsung.com external tracker

Automation (news + stats + first-party feeds) catches most things, but some
factors slip through every automated net. This list is the human layer: ~30
minutes once a quarter to check what the machines structurally can't.

Mark each done, add anything found straight into `data/events.json` (same
fields as other events). Date each review.

## Why this exists
- News API misses slow STATES (aging, middle-class growth) and sub-threshold events.
- Stats API only covers indicators you wired up — not culture, sentiment, or novelty.
- First-party feeds only cover sources you listed — new platforms aren't on the list yet.
The checklist targets exactly those gaps.

---

## Review date: __________   Reviewer: __________

### 1. New platforms / channels (the "we didn't know it existed" gap)
- [ ] Any new social or content platform gaining traction in our 12 markets?
      (TikTok-style entrants, regional apps, new AI search tools)
- [ ] Any platform we depend on that launched a feature changing discovery/checkout?
- [ ] If found → add as `category: platform` or `marketing`, set scope.

### 2. Slow demographic / structural trends (the "too gradual" gap)
- [ ] Skim World Bank / national-statistics dashboards for each key market:
      aging, urbanization, smartphone penetration, middle-class size.
- [ ] Anything the monthly stats job didn't flag because it stayed under threshold
      but feels directionally important over 3-5 years?
- [ ] If found → `category: social_issue` or `economy`, horizon `months`.

### 3. Culture / calendar (the "not newsworthy but matters" gap)
- [ ] Upcoming holidays, festivals, shopping events per market in the next quarter
      (regional ones the news won't headline).
- [ ] Cultural shifts in how people shop/research electronics locally.
- [ ] If found → `category: culture` or `holiday`.

### 4. Quiet competitor moves
- [ ] Check Apple / Xiaomi / Google / local rivals' sites & app-store listings
      for changes that didn't make headlines (pricing, regional launches, UI).
- [ ] If found → `category: competitor`.

### 5. Regulation in slow motion
- [ ] Any privacy / ad / AI rules progressing through legislatures (not yet enforced,
      so not yet "news") that will hit our markets? (EU AI Act phases, etc.)
- [ ] If found → `category: regulation`, horizon `months`.

### 6. Automation health check
- [ ] Skim the last quarter of auto-collected events: any obvious false positives
      to delete? Any category conspicuously empty (a sign the source list has a hole)?
- [ ] Adjust QUERIES (collect.py), INDICATORS (collect_stats.py), or FEEDS
      (collect_firstparty.py) to close any gap you noticed.

---

Honest note: even with all three automated layers plus this review, full coverage
is impossible — the goal is to make a *miss on something important* unlikely, not
to guarantee zero misses.
