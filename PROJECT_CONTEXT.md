# PROJECT_CONTEXT.md

**Read this first in any new Claude session.** It carries the product vision,
research methodology, privacy boundary, editorial rules and deployment shape so
none of it has to be re-explained.

---

## 1. What this is

**Bitcoin vs The Moon** is a public longitudinal experiment investigating
whether lunar cycles and Bitcoin's astrological natal chart show any useful
relationship with Bitcoin market behaviour, **considered alongside** conventional
technical analysis, price structure, volume, market regime and real-world
catalysts.

It is **not** a generic crypto-news portal, and **not** a claim that the Moon
predicts Bitcoin. The central proposition is a question:

> "Can lunar cycles tell us anything useful about Bitcoin? We are testing the
> hypothesis publicly — recording observations before events and then recording
> what actually happened, including failures."

**Roles.** The human owner (Darren Kandekore) is **Editor and Chief Scientist**.
The AI is **Researcher, Tester, Journalist and Astrologer**: it gathers evidence,
performs calculations, monitors active experiments, drafts analysis and maintains
records. **The human decides what is published.** Nothing publishes itself.

---

## 2. The privacy boundary (non-negotiable)

The private Companion is **the laboratory**. Private chat, screenshots, trade
positions, leverage, exchange balances, P&L, stop losses, take profits and
personal trading decisions are **private by default and never exposed** through
public pages or APIs.

This is enforced in code, not by convention:

- `Conversation` and `Message` have **no public serializer at all**.
  `btcmoon/editorial/serializers.py:assert_public` raises `PrivateDataLeak` if
  anything tries. Covered by `tests/test_privacy.py`.
- Every public query in `btcmoon/web/queries.py` filters to
  `status == PUBLISHED AND visibility == PUBLIC` **at the database level**.
- `FORBIDDEN_PUBLIC_FIELDS` blocks private field names from any public payload.
- Promoting something out of chat (`Create Observation`, `Create Hypothesis`,
  `Create Prediction`, `Draft Article`, `Record Result`, `Attach to Experiment`,
  `Archive/Ignore`) always produces a **DRAFT**. The Editor publishes explicitly.

Public material may discuss market hypotheses and lessons. It must not include
private trading details unless the Editor deliberately writes them into the
public draft themselves.

---

## 3. Research methodology — do not rewrite history

### The legacy website methodology

`moon_engine.py` at the repository root is **provenance-sensitive and
deliberately unchanged**. It is the canonical implementation. `btcmoon/research/legacy.py`
calls it with the documented parameters; nothing reimplements its maths.

The parameters **are** the methodology:

| Parameter | Value |
|---|---|
| Price source | Yahoo Finance BTC-USD daily Close (auto-adjusted) |
| Phases | PyEphem `next_full_moon` / `next_new_moon`, reduced to calendar dates |
| Pivots | `scipy.signal.find_peaks` |
| Minimum pivot spacing | 30 observations |
| Prominence threshold | 15% of median Close |
| Maximum lag | ±14 calendar days |
| Signed lag | `pivot_date − moon_date` (positive = pivot **after** the moon) |
| Full Moon matches | nearest significant swing **high** within ±14 days |
| New Moon matches | nearest significant swing **low** within ±14 days |

### Published benchmarks (pinned by regression tests)

`tests/test_legacy_methodology.py` fails if any of these move:

- **Recent two-year Full-Moon benchmark:** mean **+4.4 days**, median +4, SD 4.2, **n=5**.
- **2017–2026:** **71%** of matched major highs after the Full Moon, mean **+3.2**, median **+6**, n=31.
- Full history (2014→): 47 matched tops, 45 matched bottoms, 48 swing highs, 46 swing lows.

### What the research actually says

- The work is **exploratory and hypothesis-generating**. Its conclusion is
  continued testing, **not** a standalone lunar trading signal.
- Phase-shift and null controls **weaken** any claim that the astronomical Full
  Moon *uniquely causes* the high.
- The **New Moon / local low** correspondence is the **stronger** empirical lead.
  In 2026, 7 of the first 8 New Moons had a strict local low in T0:T+3.
- **Nodal strength is not a reliable timing predictor.** The amplitude result is
  conditional and unvalidated prospectively: *after* a New-Moon-associated low has
  already formed, stronger New Moons historically correlated with larger
  subsequent 7/14/21-day rallies.
- **Macro catalysts can overwhelm and reshape lunar and technical setups.** This
  is the single most important caveat on the whole project.

### Pattern Fit Score — frozen at 100 points

25 New-Moon low alignment · 25 waxing appreciation · 25 Full-Moon high
alignment · 25 waning weakening. **Nodal strength and market state are stored
separately and never inflate the score.**

### The research constitution

**Protocol changes are versioned. Never silently alter lag windows, pivot
definitions, scoring weights or the strength formula because recent price action
did not fit.** A genuine change is a new `ResearchProtocol` version with a
`supersedes` link. Frozen protocols raise `ImmutableAfterPublishError` on write.

**Where a historical figure and the current code disagree, both are recorded.**
Two live examples, deliberately left unreconciled:

| Figure | Recorded at the time | Current code |
|---|---|---|
| 11 Sep 2026 New Moon strength | 79/100 | 69.2/100 |
| Aug 2026 pre-waning Pattern Fit | 82.6/100 | differs |

Tuning a formula to reproduce a historical number would breach the constitution.

---

## 4. The frozen September 2026 protocol

Registered before the window opened, in
`btcmoon/research/protocols.py:SEPTEMBER_2026_PROTOCOL`:

- New Moon **11 Sep 2026 03:27 UTC** (computed exactly: 03:26:55).
- **Primary test:** does a strict local low form in **T0:T+3** (11–14 Sep)?
- **Strict local low** = a daily close on a day in [T0, T+3] strictly lower than
  every other close in [T0−2, T+8]. Fixed in advance.
- New-Moon strength 79/100 recorded in advance — **context only, not evidence
  that a low must occur**.
- If a qualifying low forms, measure maximum upside at exactly **7, 14 and 21
  days** from the pivot.
- Full Moon **26 Sep 2026 16:49 UTC** (computed: 16:48:57).
- Then assess waxing return, cycle-high alignment and the website-defined
  major-high relationship. Final review after 30 Sep.
- **Amendment policy: none.**

### The verified outcome

**The T0:T+3 test FAILED**, and the system reports it as failed:

- Lowest close in the window: **13 Sep, $76,838.16** (NM+2).
- But a **lower** close came **15 Sep at $75,612.51** (NM+4), outside the window.
- By the pre-registered rules that is not a strict local low.

August 2026 shows the **same shape**: first local low 14 Aug (NM+2), true cycle
low 16 Aug at $62,818.65 (NM+4). **Two cycles is not evidence** — it is a
hypothesis worth pre-registering for the next cycle rather than fitting to these two.

Keep the paper's formal T0:T+3 protocol **distinct** from the informal private
NM+0.4-day timing idea. Conflating them after the fact is exactly the
goalpost-moving the constitution forbids.

---

## 5. Editorial rules

- **Published predictions are immutable.** Text, test criteria, invalidation
  criteria, evidence snapshot and horizon all raise on write once published.
  Corrections are appended as new `Result` records with their own timestamp.
- **Never fake a historical publication date.** `observed_at` (what the content is
  *about*) and `published_at` (when this site published it) are separate columns.
  `publish()` always stamps *now*.
- **Reconstructed archive entries are labelled** with a visible notice saying they
  were written up after the fact and were not published here on the historical date.
- **Failures, misses and inconclusive results are publishable** and must never be
  hidden or softened.
- Outcomes are **Consistent / Partially Consistent / Inconsistent / Invalidated /
  Inconclusive**. Deliberately **not** a win percentage. Numeric data is preserved
  for later statistical testing.
- **Voice:** intelligent, curious, evidence-aware, readable, not sensational.
  Prefer "consistent with", "corresponded with", "failed", "inconclusive",
  "requires further testing" over causal certainty.
- Always distinguish `[FACT]` / `[SOURCE]` / `[TECHNICAL]` / `[LUNAR]` / `[ASTRO]` /
  `[HYPOTHESIS]` / `[PREDICTION]` / `[RESULT]`. These tags are enforced in the
  prompts (`btcmoon/ai/prompts.py`).
- **News is subordinate.** It is context for the experiment, not the site's
  identity. Only 3–5 genuinely important developments appear on the homepage.
  Link and attribute; never republish a full copyrighted article.
- Nothing is investment advice. The site must never become a personalised
  trade-instruction service.

---

## 6. Architecture

**Python-first. One Flask process. No JavaScript framework.**

```
btcmoon/
  app.py            Flask application factory
  config.py         all configuration, from environment variables
  db.py             SQLAlchemy engine/session (MySQL prod, SQLite dev)
  models/           22 tables: core, research, content, data
  research/         legacy adapter, Pattern Fit, frozen protocols
  lunar/            exact phase instants, nodal distance, strength score
  astrology/        BTC natal chart, transits, outlook builder
  market_data/      provider adapters + derived technical context
  news/             RSS ingestion, dedupe, rule-based classify/score
  ai/               OpenAI adapter, prompts, pricing, cost ledger, budget guard
  editorial/        lifecycle, slugs, PUBLIC SERIALIZERS (privacy boundary)
  web/              public blueprint, queries, SEO, filters
  admin/            private laboratory blueprint + Companion
  auth/             login, admin_required, entitlements
  seeds/            bootstrap + reconstructed archive
  templates/ static/
jobs/               cron entry points (python -m jobs.<name>)
migrations/         Alembic
tests/              153 tests
moon_engine.py      LEGACY — provenance-sensitive, do not modify
app.py              LEGACY Streamlit dashboard — optional, still works
manage.py           CLI
```

**Why Flask rather than Streamlit for the public site:** articles need canonical
URLs, per-page metadata, OpenGraph, JSON-LD structured data, a real `sitemap.xml`
and crawlable server-rendered HTML. Streamlit is a websocket app and gives none of
those. Admin and Companion live in the *same* Flask app rather than a second
framework, because one WSGI process is materially simpler to run under
LiteSpeed/Passenger. The Streamlit dashboard is **retained unchanged** as an
optional private research tool.

---

## 7. AI and cost control

- Every call goes through `AiClient.complete()`, which checks the budget
  **before** the call and writes to the `ai_usage` ledger **after** it.
- **Model per task** (`TASK_MODEL_TIER`): classification/summaries on the cheap
  model, synthesis/articles on the strong one. Overridable per task in
  `/admin/settings/` without a deploy.
- **Hard ceiling.** At the monthly budget, all non-essential AI generation stops.
  The public site, news ingestion, market data, scheduled jobs and the admin area
  keep running. Warnings at 50% / 75% / 90%.
- **Cheap-and-deterministic first.** RSS → dedupe → rule-based relevance →
  database. No AI runs per news item. The strong model is reserved for scheduled
  briefs, active experiment analysis, outlooks and editor-approved writing.
- **Graceful degradation.** With no `OPENAI_API_KEY`, briefings, outlooks and the
  Companion return a **complete deterministic summary** computed from market,
  lunar, natal and protocol data — at zero cost. This is a working state, not an
  error state.
- Unpriced models fall back to a pessimistic rate and are flagged in the ledger,
  so an unknown model can never silently report $0.00.

---

## 8. Free period and the paywall

Everything is free through **31 December 2026**. The entitlement/subscription
machinery is built and tested but **disabled by configuration**
(`PAYWALL_ENABLED=false`). Even with it switched on, `FREE_UNTIL` wins until 2027.
Subscriber roles are a **separate axis** from admin permissions — a subscriber with
`*` entitlements is still not an admin.

---

## 9. Where things live

| Task | File |
|---|---|
| Change the lunar methodology | **Don't.** Add a new versioned protocol. |
| Add a news source | `btcmoon/news/feeds.py` |
| Change a model or budget | `/admin/settings/` (runtime) or `.env` (default) |
| Add a public page | `btcmoon/web/views.py` + `btcmoon/templates/public/` |
| Add a scheduled job | `jobs/` — copy the shape of `jobs/ingest_news.py` |
| Change the privacy rules | `btcmoon/editorial/serializers.py` + tests |
| Adjust the natal chart | `btcmoon/astrology/natal.py` (`BTC_NATAL_MOMENT`) |

**Before changing research code, run `pytest tests/test_legacy_methodology.py`.**
If it fails, you have changed a published result.
