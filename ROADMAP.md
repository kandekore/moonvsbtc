# ROADMAP.md

Status as of **21 September 2026**, ranked by impact. Everything in "Built" is
working and tested; everything below it is honestly not done.

---

## Built and working

| Area | State |
|---|---|
| Legacy methodology preserved | `moon_engine.py` unchanged; 8 regression tests pin the +4.4d, +3.2d/71% and pivot-count results |
| MySQL data model | 22 tables, Alembic migration, utf8mb4 |
| Public site | Home, Experiment, Observations, Predictions & Results, Natal Chart, Outlooks, Transit Calendar, Methodology, News, About |
| SEO | Canonical URLs, per-page metadata, OpenGraph, JSON-LD, `sitemap.xml`, `robots.txt`, clean slugs |
| Private admin + Companion | Authenticated, server-side authorised, with retrieval over experiments/predictions/protocols/lunar/natal/market/news |
| Editorial lifecycle | Draft → review → published; promotion from chat always creates drafts |
| Immutable predictions | Enforced in the model layer, not by convention |
| Provenance | `observed_at` vs `published_at`; reconstructed entries carry a visible notice |
| Frozen protocols | Website methodology v1.0 + September 2026 test, both frozen and immutable |
| News/RSS | 9 sources, dedupe, rule-based classification and scoring, zero AI cost |
| Twice-daily briefings | Cron-executable, idempotent, full deterministic fallback |
| BTC natal outlooks | Daily/monthly/yearly model + generator; daily created one day ahead as a draft |
| AI cost control | Per-call ledger, per-task model tiers, 50/75/90% warnings, hard ceiling |
| Entitlements | Built, tested, disabled by config; free through 31 Dec 2026 |
| Seed archive | 2 experiments, 9 observations, 1 prediction, 3 technical patterns — all drafts |
| Tests | 153 passing |

---

## 1 — Do these first (blocking a good launch)

### 1.1 Review and publish the seed archive
Nothing is public yet. The archive is sitting in `/admin/` as drafts. Read each
one, correct anything you remember differently, attach source links to the Fed
story, and publish. **~1 hour.**

### 1.2 Attach sources to the macro claims
`tests` and the spec both require sourced factual claims. The "dovish Fed
repricing" observation currently asserts the association without a link. Find the
contemporaneous source and add it before publishing that record. **~15 min.**

### 1.3 Provide `OPENAI_API_KEY`
Everything works without it, but the AI write-up, the Companion and the
prioritised briefings are the point of the research system. Set
`AI_MONTHLY_BUDGET_USD` first. **~5 min.**

### 1.4 Deploy and verify
Follow `DEPLOYMENT.md` Path A. **~1–2 hours** including DNS/SSL propagation.

### 1.5 Record the September result properly
The frozen T0:T+3 test **passed**: a qualifying strict local low formed on
11 September at NM+0 ($76,162.91). Create a formal `Result` against the
pre-registered prediction and publish both — including the separate facts that
deeper lows followed at NM+4/+5/+6 and that the absolute cycle low was $74,944.59
on 15 September. **~30 min.** Publish the distinction, not just the pass: the
value is in showing that a pivot forming and a cycle bottoming are different
claims.

---

## 2 — High value, not blocking

### 2.1 An OG image per record
There is one static OG image. Predictions and results would share far better with
a generated card showing the claim and its outcome. `tools/make_og_image.py`
already does Pillow rendering — extend it and call it on publish.

### 2.2 Email the briefing
The twice-daily briefing lands in the admin. It should arrive in your inbox at
07:00. Add an SMTP adapter and a `--email` flag to the brief jobs.

### 2.3 Newsletter / account follow-up
Free accounts exist but do nothing yet. Wire a simple "notify me when a
prediction resolves" email.

### 2.4 Statistical testing page
Numeric result data is being preserved deliberately. Once there are ~20 resolved
records, add a page that runs the phase-shift and null controls **live** and
publishes the output — including when it is unflattering.

### 2.5 Monthly and yearly outlooks
The model and generator support all three kinds; only `daily` has a cron job.
Add `jobs/monthly_outlook.py` and `jobs/yearly_outlook.py` (copy `daily_outlook.py`).

### 2.6 News classification quality
Rule-based classification mislabels some stories (a political-donation story
landed in `regulation`). Either tighten the keyword lists or run the cheap model
over *only* the items that already score above the homepage threshold — a handful
per day, negligible cost.

---

## 3 — Worth doing eventually

- **Pattern Fit percentile ranking.** The score is computed; the "97th percentile"
  framing needs a historical distribution computed across all cycles since 2014.
- **`TechnicalPattern` admin UI.** The model and seeds exist; there is no create
  form yet. Patterns are currently editable only through the generic content editor.
- **Experiment creation UI.** Experiments are seeded and editable but cannot be
  created from the admin. `content_new` supports articles, observations and
  predictions only.
- **Lunar/natal event persistence.** `LunarEvent` and `NatalEvent` tables exist and
  are unused — everything is computed on demand. Populate them if you want to
  query historical transits in SQL.
- **`MarketSnapshot` history.** Being written daily by cron but not yet surfaced
  anywhere in the UI.
- **Full-text search** across the journal.
- **RSS/Atom feed** for the site itself.
- **Redis** for rate limiting and the market cache if traffic ever justifies it.

---

## 4 — Known issues and honest limitations

### 4.0 The pivot-definition error (fixed 21 Sep 2026)
The New-Moon test was first implemented on daily **Close** with an invented
guard-window rule, and both August and September were wrongly recorded as
failures. Corrected to the paper's LOW-based strict 7-day pivot; both pass.
Protocol superseded to v1.1, v1.0 archived not deleted, existing databases
repaired by `bootstrap()`. Full account in `PROJECT_CONTEXT.md` §4.3.

**Guard against a recurrence:** `tests/test_research_services.py` now asserts the
protocol definition is LOW-based, that a close-only frame raises, and that the
paper's 7-of-8 claim reproduces exactly.

### 4.1 Two unreconciled historical figures
By design, per the research constitution:

| Figure | Recorded at the time | Current code |
|---|---|---|
| 11 Sep 2026 New Moon strength | 79/100 | 69.2/100 |
| Aug 2026 pre-waning Pattern Fit | 82.6/100 | differs |

Both are stated in the protocol and archive records. **Do not "fix" this by
tuning the formulas** — that is precisely what the constitution forbids. If you
recover the original scoring code, add it as a new versioned protocol.

### 4.1b Pattern Fit alignment components still use Close
`btcmoon/research/pattern_fit.py` locates the New-Moon low and Full-Moon high
using closing prices. The paper does not state which basis the Pattern Fit Score
uses, so it has been **left as-is** rather than changed on assumption. If the
paper specifies intraday extremes, this needs a new scoring protocol version —
not an edit.

### 4.2 The measured-move target is unresolved
The daily cup-and-handle's $100k–$103k target is recorded as a contemporaneous
discussion, not a verified computation. It must be recorded as met, failed or
inconclusive on the evidence — not quietly dropped if it fails.

### 4.3 Small samples throughout
n=5 on the headline Full-Moon benchmark. The 2017–2026 figures use n=31. Nothing
here supports a strong claim, and the site says so.

### 4.4 Streamlit dashboard has no authentication
`app.py` is unchanged and still has no auth of its own. If you expose it, put it
behind HTTP auth. It is not part of the deployment.

### 4.5 `daily_outlook` cron creates drafts only
Deliberate. If no one publishes them, the "Tomorrow's outlook" homepage slot stays
empty. Either publish daily, or add `--publish` to the cron line and accept that
outlooks then publish unreviewed.

### 4.6 Cron timezone
Server cron is usually UTC. The recommended lines assume you have checked. BST/GMT
will shift the briefing by an hour twice a year unless you set `CRON_TZ`.

### 4.7 Rate limiting is per-process
`memory://` does not coordinate across workers. Fine for one Passenger process;
point at Redis if you scale out.
