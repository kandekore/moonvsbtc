# 🌕 Bitcoin vs The Moon

> Can lunar cycles tell us anything useful about Bitcoin?

A public longitudinal experiment testing whether lunar cycles and Bitcoin's
astrological natal chart show any useful relationship with market behaviour —
considered alongside conventional technical analysis, price structure, volume,
market regime and real-world catalysts.

It is **not** a claim that the Moon predicts Bitcoin. Observations are recorded
**before** events and results recorded afterwards, **including the failures**.

**New to the codebase?** Read [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) first —
it carries the vision, methodology, privacy boundary and editorial rules.

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env          # SQLite default works out of the box
python -c "import secrets; print(secrets.token_urlsafe(48))"   # → SECRET_KEY

python manage.py init-db
python manage.py bootstrap        # frozen protocols, news sources, settings
python manage.py create-admin     # your Editor account
python manage.py seed-archive     # Aug/Sep 2026 reconstructed DRAFTS
python manage.py run              # http://127.0.0.1:5000
```

Then sign in at `/account/login` and open `/admin/`.

**No `OPENAI_API_KEY` is required.** Without one, briefings, outlooks and the
Companion return a complete deterministic summary computed from market, lunar,
natal and protocol data, at zero cost. Adding the key activates the AI write-up
with no other change.

---

## Architecture

**Python-first. One Flask process. No JavaScript framework.**

The public editorial/SEO site and the private research laboratory are the same
WSGI application. Server-rendered Jinja gives canonical URLs, per-page metadata,
structured data and a real sitemap — which a websocket app cannot — and a single
process is the simplest thing to run under LiteSpeed/Passenger.

```
btcmoon/
├── app.py          Flask factory        ├── news/         RSS ingest, dedupe, scoring
├── config.py       env configuration    ├── ai/           OpenAI adapter, cost ledger, budget
├── db.py           SQLAlchemy engine    ├── editorial/    lifecycle + privacy serializers
├── models/         22 tables            ├── web/          public blueprint, SEO, queries
├── research/       legacy adapter,      ├── admin/        private lab + Companion
│                   Pattern Fit,         ├── auth/         login, roles, entitlements
│                   frozen protocols     └── seeds/        bootstrap + archive
├── lunar/          phases, strength
├── astrology/      natal chart, transits, outlooks
└── market_data/    provider adapters

jobs/               cron entry points     moon_engine.py   LEGACY — do not modify
migrations/         Alembic               app.py           LEGACY Streamlit (optional)
tests/              153 tests             manage.py        CLI
```

---

## The research methodology

`moon_engine.py` is **provenance-sensitive and deliberately unchanged**. It is the
canonical implementation of the published website methodology; nothing in
`btcmoon/` reimplements its maths.

| Parameter | Value |
|---|---|
| Price | Yahoo Finance BTC-USD daily Close |
| Phases | PyEphem, reduced to calendar dates |
| Pivots | `scipy.signal.find_peaks`, spacing 30, prominence 15% of median |
| Max lag | ±14 calendar days |
| Signed lag | `pivot_date − moon_date` (positive = pivot **after** the moon) |

**Pinned by regression tests** (`tests/test_legacy_methodology.py`):

- Recent two-year Full-Moon benchmark: mean **+4.4 d**, median +4, SD 4.2, **n=5**
- 2017–2026: **71%** of matched major highs after the Full Moon, mean **+3.2**, median **+6**

```bash
pytest tests/test_legacy_methodology.py   # run this before touching research code
```

If it fails, you have changed a published result.

### The research constitution

Lag windows, pivot definitions, scoring weights and the strength formula are
**never** changed because recent price action did not fit. A genuine change is a
new versioned `ResearchProtocol`. Frozen protocols raise on write.

Where a historical figure and the current code disagree, **both are recorded**
rather than reconciled — see [`PROJECT_CONTEXT.md §3`](PROJECT_CONTEXT.md).

---

## The privacy boundary

Private chat, trade positions, leverage, balances, P&L, stops and targets are
**private by default and never exposed publicly**. This is enforced in code:

- `Conversation` and `Message` have **no public serializer at all** — asking for
  one raises `PrivateDataLeak`.
- Every public query filters to `PUBLISHED + PUBLIC` at the database level.
- Promoting anything out of chat always produces a **draft**.

Covered by `tests/test_privacy.py`.

---

## Editorial guarantees

| Guarantee | Enforced by |
|---|---|
| Published predictions are immutable | `Prediction.__setattr__` raises; corrections append as `Result` |
| Publication dates are never faked | `observed_at` ≠ `published_at`; `publish()` always stamps now |
| Reconstructed entries are labelled | Visible notice rendered from `provenance` |
| Frozen protocols cannot be edited | `ResearchProtocol.__setattr__` raises |
| Failures stay on the record | Outcomes are five-valued, never a win percentage |

---

## Scheduled jobs

All run from cron with no browser session, and are idempotent.

```bash
python -m jobs.morning_brief       # 07:00 — private research briefing
python -m jobs.evening_brief       # 18:00 — private research briefing
python -m jobs.ingest_news         # hourly — RSS, zero AI cost
python -m jobs.daily_outlook       # tomorrow's natal outlook, as a DRAFT
python -m jobs.snapshot_market     # daily market snapshot
python -m jobs.evaluate_protocols  # re-measure frozen protocols (never edits them)
```

Every run is logged to `scheduled_job_runs` and visible at `/admin/jobs/`.

---

## AI cost control

- Budget checked **before** every call; ledger written **after** every call
- Model per task — cheap for classification, strong for synthesis
- Warnings at **50% / 75% / 90%**, then a **hard monthly ceiling**
- At the ceiling, AI generation stops; **the site, news, market data and cron keep running**
- Unpriced models use a pessimistic fallback rate and are flagged, so nothing
  silently reports $0.00

Dashboard at `/admin/costs/`. Settings at `/admin/settings/` (no deploy needed).

---

## Free access

Everything is free through **31 December 2026**. The entitlement and paywall
machinery is built and tested but disabled by configuration. Subscriber roles are
a separate axis from admin permissions.

---

## Testing

```bash
pytest                                  # 153 tests
pytest tests/test_legacy_methodology.py # the published research results
pytest tests/test_privacy.py            # the privacy boundary
pytest tests/test_immutability.py       # immutable predictions, frozen protocols
```

---

## Deployment

See [`DEPLOYMENT.md`](DEPLOYMENT.md) — LiteSpeed + MySQL, cPanel "Setup Python
App" (Passenger/LSAPI), with a standalone + reverse-proxy alternative, exact cron
lines, MySQL setup and troubleshooting.

See [`ROADMAP.md`](ROADMAP.md) for what is done, what is next and the known
limitations.

---

## The legacy Streamlit dashboard

`app.py` is the original interactive pivot explorer. **Unchanged and still
working**, but not required — the public site, admin, Companion and every cron
job run without it.

```bash
pip install -r requirements-streamlit.txt
streamlit run app.py
```

It has no authentication of its own. Do not expose it without HTTP auth.

---

⚠️ **This is an ongoing experiment, not investment advice.** Astrology has no
established causal mechanism in financial markets. Nothing here should be used as
the basis for a trading decision.

Developed by [Darren Kandekore](https://darrenk.uk)
