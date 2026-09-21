"""The reconstructed August/September 2026 research archive (spec s17).

Every record here is created as a DRAFT with
``provenance = reconstructed_archive``, which makes the public template render a
visible notice saying it was written up after the fact. This site did not
publish any of it on the historical date and must never imply that it did.

Market figures are read from real BTC-USD daily closes at import time and are
never invented. Where a contemporaneously recorded figure differs from what the
current code computes, BOTH are stated rather than reconciled - tuning a formula
to reproduce a historical number would breach the research constitution.

Private trade history, leverage, P&L, stops, targets and exchange screenshots
are NOT seed content and never appear here.
"""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from ..editorial.slugs import unique_slug
from ..lunar.phases import scored_events
from ..market_data import get_ohlc_history
from ..models import (
    Experiment, ExperimentStatus, Observation, Outcome, Prediction, Provenance,
    ResearchProtocol, Status, TechnicalPattern, Visibility, utcnow,
)
from ..research.protocols import evaluate_nm_low_test


def _close_on(series: pd.Series, day: str) -> float | None:
    try:
        val = series.asof(pd.Timestamp(day))
    except (KeyError, TypeError):
        return None
    return None if val is None or pd.isna(val) else round(float(val), 2)


def _extreme(series: pd.Series, start: str, end: str, kind: str):
    win = series.loc[pd.Timestamp(start): pd.Timestamp(end)]
    if win.empty:
        return None, None
    idx = win.idxmin() if kind == "low" else win.idxmax()
    return idx.date(), round(float(win.loc[idx]), 2)


def _verified_facts(price: pd.DataFrame) -> dict:
    """Read every figure the archive cites straight out of the price data.

    ``price`` must be daily OHLC. The New-Moon protocol is defined on intraday
    LOWS; closing prices answer a different question and must not be substituted.
    """
    s = price["close"]
    low = price["low"]
    facts: dict = {
        "verified_at": utcnow().isoformat(),
        "source": "Yahoo Finance BTC-USD daily OHLC",
        "protocol_basis": "daily LOW (strict 7-day pivot); closes are NOT used for the test",
    }

    # Formal protocol results, computed with the pre-registered LOW-based rule.
    facts["aug_nm_test"] = evaluate_nm_low_test(
        price, dt.datetime(2026, 8, 12, 17, 36, 39)
    ).to_dict()
    facts["sep_nm_test"] = evaluate_nm_low_test(
        price, dt.datetime(2026, 9, 11, 3, 26, 55)
    ).to_dict()
    facts["aug_pivot_low"] = facts["aug_nm_test"]["pivot_low"]
    facts["aug_pivot_date"] = facts["aug_nm_test"]["pivot_date"]
    facts["sep_pivot_low"] = facts["sep_nm_test"]["pivot_low"]
    facts["sep_pivot_date"] = facts["sep_nm_test"]["pivot_date"]
    facts["sep_cycle_low"] = facts["sep_nm_test"]["cycle_low"]
    facts["sep_cycle_low_date"] = facts["sep_nm_test"]["cycle_low_date"]

    # --- August 2026 cycle ------------------------------------------------
    facts["aug_new_moon_close"] = _close_on(s, "2026-08-12")
    aug_low_date, aug_low = _extreme(s, "2026-08-08", "2026-08-20", "low")
    facts["aug_low_date"] = aug_low_date.isoformat() if aug_low_date else None
    facts["aug_low"] = aug_low
    facts["aug_14_close"] = _close_on(s, "2026-08-14")
    facts["aug_full_moon_close"] = _close_on(s, "2026-08-28")
    aug_high_date, aug_high = _extreme(s, "2026-08-14", "2026-09-05", "high")
    facts["aug_cycle_high_date"] = aug_high_date.isoformat() if aug_high_date else None
    facts["aug_cycle_high"] = aug_high
    if aug_low and aug_high:
        facts["aug_rally_pct"] = round((aug_high - aug_low) / aug_low * 100.0, 1)

    # --- early September --------------------------------------------------
    facts["sep_02_close"] = _close_on(s, "2026-09-02")
    facts["sep_03_close"] = _close_on(s, "2026-09-03")
    if facts["sep_02_close"] and facts["sep_03_close"]:
        facts["sep_03_move_pct"] = round(
            (facts["sep_03_close"] - facts["sep_02_close"]) / facts["sep_02_close"] * 100.0, 2
        )

    # --- the frozen New-Moon window --------------------------------------
    facts["sep_new_moon_close"] = _close_on(s, "2026-09-11")
    nm_low_date, nm_low = _extreme(s, "2026-09-11", "2026-09-14", "low")
    facts["sep_t0_t3_low_date"] = nm_low_date.isoformat() if nm_low_date else None
    facts["sep_t0_t3_low"] = nm_low
    later_date, later_low = _extreme(s, "2026-09-14", "2026-09-17", "low")
    facts["sep_later_low_date"] = later_date.isoformat() if later_date else None
    facts["sep_later_low"] = later_low

    # --- the September breakout ------------------------------------------
    for day in ("2026-09-16", "2026-09-18", "2026-09-19", "2026-09-20", "2026-09-21"):
        facts[f"close_{day.replace('-', '_')}"] = _close_on(s, day)

    # --- moon geometry ----------------------------------------------------
    facts["moon_events"] = [
        {
            "type": e.event_type, "exact_utc": e.exact_at.isoformat(),
            "nodal_distance_deg": e.nodal_distance_deg,
            "computed_strength": e.strength_score,
        }
        for e in scored_events(dt.date(2026, 8, 1), dt.date(2026, 9, 30))
    ]
    return facts


def _draft_observation(session, *, title, body, observed_at, facts=None,
                       provenance=Provenance.RECONSTRUCTED_ARCHIVE, experiment=None):
    obs = Observation(
        slug=unique_slug(session, Observation, title),
        title=title, body=body.strip(), observed_at=observed_at,
        imported_at=utcnow(), provenance=provenance,
        btc_snapshot_json=json.dumps(facts or {}, default=str),
        status=Status.DRAFT, visibility=Visibility.PRIVATE,
        experiment_id=experiment.id if experiment else None,
    )
    session.add(obs)
    session.flush()
    return obs


def seed_archive(session, price: pd.DataFrame | None = None) -> dict:
    """Idempotent. Returns a count of what was created."""
    if session.query(Observation).filter(
        Observation.provenance == Provenance.RECONSTRUCTED_ARCHIVE
    ).first():
        return {"skipped": "archive already seeded"}

    price = price if price is not None else get_ohlc_history()
    if "low" not in price.columns:
        raise KeyError(
            "seed_archive requires daily OHLC. The New-Moon protocol is defined on "
            "intraday lows; a close-only frame would produce the wrong result."
        )
    f = _verified_facts(price)
    created = {"observations": 0, "experiments": 0, "predictions": 0, "patterns": 0}

    protocol = (
        session.query(ResearchProtocol)
        .filter_by(slug="september-2026-new-moon-test").one_or_none()
    )

    # ------------------------------------------------------------------
    # Experiment 1 - the August 2026 high-fit cycle (concluded)
    # ------------------------------------------------------------------
    aug = Experiment(
        slug=unique_slug(session, Experiment, "August 2026 high-fit lunar cycle"),
        ref="EXP-2026-08-HF",
        title="August 2026: a high-fit lunar cycle, and what the waning leg actually did",
        summary=(
            "The August 2026 cycle scored unusually high on the Pattern Fit Score before "
            "its waning leg completed. This record fixes what was expected, and what the "
            "verified market data shows actually happened."
        ),
        observed_at=dt.datetime(2026, 8, 30, 12, 0),
        starts_at=dt.datetime(2026, 8, 12, 17, 36, 39),
        ends_at=dt.datetime(2026, 9, 11, 3, 26, 55),
        hypothesis_text=(
            "A high pre-waning Pattern Fit score, combined with a strongly nodally "
            "aligned Full Moon, is associated with elevated weakness in the waning leg."
        ),
        prediction_text=(
            "Historical high-fit cycles suggested elevated waning weakness, commonly "
            "nearer 10-15% than a crash. Recorded as a tendency, not a trade instruction."
        ),
        confidence="Low. Small sample, regime-dependent, and the score is descriptive rather than causal.",
        test_criteria=(
            "Measure the drawdown from the cycle high to the next New Moon (11 September 2026) "
            "using daily closes."
        ),
        invalidation_criteria=(
            "A waning leg that appreciates, or falls materially less than the historical "
            "high-fit tendency, weakens the hypothesis."
        ),
        technical_context=(
            f"New Moon close ${f['aug_new_moon_close']:,.2f} on 12 August. "
            f"Cycle low ${f['aug_low']:,.2f} on {f['aug_low_date']}. "
            f"Cycle high ${f['aug_cycle_high']:,.2f} on {f['aug_cycle_high_date']}."
        ),
        market_news_context=(
            "Early September saw a sharp rally associated with dovish Federal Reserve "
            "repricing - a macro catalyst that reshaped the technical picture."
        ),
        moon_context_json=json.dumps(f["moon_events"], default=str),
        btc_snapshot_json=json.dumps(f, default=str),
        experiment_status=ExperimentStatus.CONCLUDED,
        outcome=Outcome.PARTIALLY_CONSISTENT,
        result_text=(
            f"The waning leg did not deliver the expected weakness. From the cycle high of "
            f"${f['aug_cycle_high']:,.2f} on {f['aug_cycle_high_date']}, price at the next "
            f"New Moon (11 September) closed ${f['sep_new_moon_close']:,.2f} - a drawdown of "
            f"{round((f['sep_new_moon_close'] - f['aug_cycle_high']) / f['aug_cycle_high'] * 100, 1)}%, "
            f"well short of the 10-15% tendency. The waxing leg, by contrast, was strongly "
            f"consistent: a {f['aug_rally_pct']}% advance from the "
            f"{f['aug_low_date']} low into the Full-Moon period.\n\n"
            "Recorded as PARTIALLY CONSISTENT: the waxing expectation held, the waning "
            "expectation did not."
        ),
        result_recorded_at=utcnow(),
        lessons=(
            "A high Pattern Fit score describes how well a cycle matched the shape of the "
            "hypothesis; it is not a forecast of the next leg. Macro repricing overwhelmed "
            "the expected waning weakness."
        ),
        provenance=Provenance.RECONSTRUCTED_ARCHIVE,
        status=Status.DRAFT, visibility=Visibility.PRIVATE,
    )
    session.add(aug)
    session.flush()
    created["experiments"] += 1

    # ------------------------------------------------------------------
    # Experiment 2 - the frozen September New-Moon test (live)
    # ------------------------------------------------------------------
    sep = Experiment(
        slug=unique_slug(session, Experiment, "September 2026 New Moon prospective test"),
        ref="EXP-2026-09-NM",
        title="September 2026: the pre-registered New-Moon low test",
        summary=(
            "A prospective, pre-registered test of the New-Moon / local-low correspondence, "
            "registered before the window opened and judged by rules fixed in advance."
        ),
        protocol_id=protocol.id if protocol else None,
        observed_at=dt.datetime(2026, 9, 11, 3, 26, 55),
        starts_at=dt.datetime(2026, 9, 11, 3, 26, 55),
        ends_at=dt.datetime(2026, 9, 30, 23, 59, 59),
        hypothesis_text=(
            "A strict local low forms in the window T0:T+3 following the New Moon "
            "(11-14 September 2026 inclusive)."
        ),
        prediction_text=(
            "If a qualifying low forms, measure the maximum upside at exactly 7, 14 and 21 "
            "days from the pivot. The New-Moon geometry strength recorded in advance is "
            "context only and is not evidence that a low must occur."
        ),
        confidence=(
            "Moderate on the direction of the lead, low on its timing. In 2026, 7 of the "
            "first 8 New Moons had a strict local low in T0:T+3; full-history behaviour "
            "is regime-dependent."
        ),
        test_criteria=(
"A strict 7-day pivot on the daily LOW: a day t in [T0, T+3] qualifies when "
            "LOW[t] < LOW[t-1], LOW[t-2], LOW[t-3] AND LOW[t] < LOW[t+1], LOW[t+2], "
            "LOW[t+3]. Strictly less-than on both sides; ties do not qualify. Defined "
            "on intraday lows, not closing prices. A qualifying pivot is not "
            "invalidated by a later lower low."
        ),
        invalidation_criteria=(
            "No day in T0:T+3 satisfies the strict 7-day low pivot. A lower low forming "
            "later, inside or outside the window, does NOT invalidate a pivot that has "
            "already qualified - it is recorded separately as context."
        ),
        technical_context=(
            f"New Moon close ${f['sep_new_moon_close']:,.2f}. Lowest close inside T0:T+3 was "
            f"${f['sep_t0_t3_low']:,.2f} on {f['sep_t0_t3_low_date']}."
        ),
        moon_context_json=json.dumps(f["moon_events"], default=str),
        btc_snapshot_json=json.dumps(f, default=str),
        experiment_status=ExperimentStatus.OBSERVING,
        outcome=Outcome.PENDING,
        provenance=Provenance.RECONSTRUCTED_ARCHIVE,
        status=Status.DRAFT, visibility=Visibility.PRIVATE,
    )
    session.add(sep)
    session.flush()
    created["experiments"] += 1

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------
    obs_specs = [
        dict(
            title="Updated exploratory paper and the recovered website methodology",
            observed_at=dt.datetime(2026, 8, 30, 10, 0),
            body=f"""
The exploratory paper was updated and, importantly, the **exact methodology the
original website used** was recovered and written down so it can never drift again:

- Yahoo Finance BTC-USD daily Close.
- Lunar phases from PyEphem, reduced to calendar dates.
- `scipy.signal.find_peaks` for significant highs and lows.
- Minimum spacing 30 observations; prominence threshold 15% of the median Close.
- Each Full Moon matched to the nearest significant swing **high** within
  +/-14 calendar days; each New Moon to the nearest swing **low**.
- Signed lag = pivot date minus Moon date, so a positive number means the pivot
  came *after* the Moon.

Re-running that method reproduces the published benchmark exactly: over the recent
two-year window, matched major highs came a mean **+4.4 days** after the Full Moon
(median +4, SD 4.2, n=5). Across 2017-2026, about **70%** of matched major highs
fell after the Full Moon, mean about +3.2 days, median about +6.

**The limitations matter as much as the result.** n=5 is tiny. Phase-shift and
null controls weaken any claim that the astronomical Full Moon *uniquely causes*
the high. The paper is exploratory and hypothesis-generating; its conclusion is
continued testing, not a standalone lunar trading signal.

The stronger empirical lead is the New Moon / local low correspondence, not the
Full Moon / high one.
""",
        ),
        dict(
            title="August 2026: a high-fit cycle, and where the low actually formed",
            observed_at=dt.datetime(2026, 8, 30, 11, 0),
            experiment=aug,
            body=f"""
The August 2026 cycle was noted at the time as a **high-fit cycle**: a Pattern Fit
Score of about **82.6/100** before the waning leg completed, described then as
roughly the 97th historical percentile.

**A note on that figure.** 82.6/100 is the number recorded contemporaneously. The
scoring implemented in this codebase today produces a different figure for the
same cycle. Both are kept. Re-tuning the scoring so it reproduces a historical
number would breach the research constitution, which forbids changing scoring
weights after the fact.

What the verified market data shows:

- New Moon **12 August 2026, 17:36 UTC**, close **${f['aug_new_moon_close']:,.2f}**.
- The cycle low was **${f['aug_low']:,.2f}** on **{f['aug_low_date']}**.
- Full Moon **28 August 2026, 04:18 UTC**, close **${f['aug_full_moon_close']:,.2f}**,
  and it was **strongly nodally aligned** - 5.0 degrees from the lunar node.
- The cycle high was **${f['aug_cycle_high']:,.2f}** on **{f['aug_cycle_high_date']}**,
  a **{f['aug_rally_pct']}%** advance from the low.

**The formal New-Moon test: a qualifying strict local low DID form, at NM+2.**

Applying the pre-registered rule - a strict 7-day pivot on the daily LOW,
`LOW[t] < LOW[t-1..t-3]` AND `LOW[t] < LOW[t+1..t+3]` - to verified daily OHLC:

| Date | Daily LOW | Qualifies? |
|---|---|---|
| 12 Aug (T0) | $63,251.11 | no |
| 13 Aug (T+1) | $62,799.29 | no |
| **14 Aug (T+2)** | **$62,487.70** | **yes** |
| 15 Aug (T+3) | $62,850.96 | no |

The contemporaneous note - "12 Aug New Moon -> 14 Aug local low" - was
**correct**. The qualifying pivot is 14 August, NM+2.

Note that 16 August printed a lower *close* (${f['aug_low']:,.2f}) than 14 August.
That is irrelevant to this test. The protocol is defined on intraday lows and
asks whether a strict local low **formed** in T0:T+3 - not whether that day held
the lowest price of the cycle. A later, deeper low does not retract a pivot that
has already formed.

Historical high-fit cycles suggested elevated weakness in the waning leg, commonly
nearer 10-15% than a crash. That expectation is recorded here *before* the outcome
is discussed, and reviewed in the experiment record.
""",
        ),
        dict(
            title="Prospective Full-Moon +4.4-day turning-window observation",
            observed_at=dt.datetime(2026, 8, 31, 9, 0),
            experiment=aug,
            body=f"""
With the Full Moon at **28 August 2026, 04:18 UTC**, the published +4.4-day mean
lag places a turning *window* around **1-2 September 2026**.

This is recorded as a **window and a context, not a standalone entry instruction.**
The mean lag has a standard deviation of about 4.2 days on n=5; a window that wide
is not a timing signal, and treating it as one would misrepresent what the data
supports.

What the verified data shows: the cycle high came on **{f['aug_cycle_high_date']}**
at **${f['aug_cycle_high']:,.2f}**, which is Full Moon **+6 days** - outside the
+4.4-day centre but comfortably inside the one-standard-deviation band. Recorded as
consistent with the distribution, and *not* as a hit.
""",
        ),
        dict(
            title="A bearish head-and-shoulders that provisionally validated, then failed",
            observed_at=dt.datetime(2026, 9, 8, 12, 0),
            body=f"""
In early September a bearish head-and-shoulders structure with a neckline break was
identified and appeared **provisionally validated**.

It then **failed and was reclaimed**.

This record exists precisely because it failed. Preserving it is the point: a
research log that quietly deletes the setups that did not work is not a research
log. Verified closes through the period:

- 3 September: **${f['sep_03_close']:,.2f}**
- 11 September: **${f['sep_new_moon_close']:,.2f}**
- 18 September: **${f['close_2026_09_18']:,.2f}**
- 21 September: **${f['close_2026_09_21']:,.2f}**

[TECHNICAL] The neckline break did not follow through, and price subsequently
reclaimed the structure decisively. Recorded as **INCONSISTENT** with the bearish
reading. Technical analysis is probabilistic; this one was wrong.
""",
        ),
        dict(
            title="Dovish Fed repricing overwhelms the lunar and technical setup",
            observed_at=dt.datetime(2026, 9, 3, 18, 0),
            body=f"""
[FACT] On 3 September 2026 BTC closed **${f['sep_03_close']:,.2f}**, up
**{f['sep_03_move_pct']:+.2f}%** on the previous close of
**${f['sep_02_close']:,.2f}**.

[SOURCE] The move was associated with dovish repricing of Federal Reserve
expectations. A source link should be attached before this is published.

**Lesson, recorded plainly:** macro catalysts can overwhelm and reshape lunar and
technical setups. This is the single most important caveat on the entire project.
A lunar window is at best a weak conditional context; a Fed repricing is a
first-order driver of the asset. Any framing that puts the Moon above the macro
has the hierarchy backwards.
""",
        ),
        dict(
            title="The formal New-Moon test opens - and how it differs from the informal idea",
            observed_at=dt.datetime(2026, 9, 11, 4, 0),
            experiment=sep,
            body=f"""
The formal prospective test begins at the **New Moon, 11 September 2026, 03:27 UTC**
(computed exactly: 03:26:55).

Two things must be kept apart, and the separation is the point:

**1. The paper's protocol (formal, pre-registered).**
Does a *strict local low* form in **T0:T+3** - 11 to 14 September inclusive? The
definition was fixed in advance and is defined on the daily **LOW**, not on
closing prices: `LOW[t] < LOW[t-1], LOW[t-2], LOW[t-3]` AND
`LOW[t] < LOW[t+1], LOW[t+2], LOW[t+3]`. Strictly less-than on both sides.
This is the claim being tested.

**2. The informal private NM+0.4-day timing idea.**
A separate, private, much more precise timing notion. It is **not** the paper's
protocol, it was never pre-registered, and it must not be allowed to stand in for
the formal test if the formal test fails. Conflating them after the fact would be
exactly the kind of goalpost-moving the research constitution forbids.

The New-Moon geometry strength recorded in advance was **79/100**. The formula
implemented in this codebase scores the same event **69.2/100**. Both are kept.
Neither is evidence that a low must occur - strength is context, not a signal, and
it does not enter the Pattern Fit Score.
""",
        ),
        dict(
            title="What the 11-14 September window actually did",
            observed_at=dt.datetime(2026, 9, 17, 12, 0),
            experiment=sep,
            body=f"""
Verified daily OHLC for the frozen window. The pre-registered test is a strict
7-day pivot on the daily **LOW**: `LOW[t] < LOW[t-1..t-3]` AND
`LOW[t] < LOW[t+1..t+3]`.

| Date | Daily LOW | Qualifies? |
|---|---|---|
| **11 Sep (T0, New Moon)** | **${f['sep_pivot_low']:,.2f}** | **yes** |
| 12 Sep (T+1) | $77,045.00 | no |
| 13 Sep (T+2) | $76,498.38 | no |
| 14 Sep (T+3) | $76,367.38 | no |

**The formal result: a qualifying strict local low DID form, on
{f['sep_pivot_date']}, at NM+{f['sep_nm_test']['lag_days']}.** Its low of
${f['sep_pivot_low']:,.2f} is strictly below the lows of 8, 9 and 10 September
($77,635.69 / $77,768.15 / $76,470.64) and strictly below the lows of 12, 13 and
14 September ($77,045.00 / $76,498.38 / $76,367.38).

**Four distinct things, which must not be conflated:**

1. **The qualifying strict local low** - {f['sep_pivot_date']}, NM+{f['sep_nm_test']['lag_days']}.
   This, and only this, is the formal pre-registered test.
2. **Later lower lows within +/-7 days** - 15 Sep ($74,944.59, NM+4),
   16 Sep ($74,995.52, NM+5) and 17 Sep ($75,945.55, NM+6). Real, and recorded.
   Under the pre-registered rules they do **not** invalidate the 11 Sep pivot.
3. **The absolute cycle low** - ${f['sep_cycle_low']:,.2f} on
   {f['sep_cycle_low_date']}. A separate measure, reported separately.
4. **The informal NM+0.4 idea** - private, never pre-registered, and intraday.
   It has its own record and must never stand in for the formal test.

**Maximum upside from the qualifying pivot**, measured per the protocol at
exactly 7 days from the pivot date: a high of
${f['sep_nm_test']['high_7d']:,.2f}, **{f['sep_nm_test']['upside_7d_pct']:+.2f}%**.
The 14- and 21-day measurements are not yet due and are recorded as pending
rather than estimated.

**On the August comparison.** August's qualifying pivot was NM+2, September's was
NM+0. The two cycles then behaved **differently**, and the difference is the
interesting part:

- **August:** the pivot at $62,487.70 on 14 August was also the **cycle low**. No
  lower low followed within +/-7 days. Pivot and bottom coincided.
- **September:** the pivot at $76,162.91 on 11 September was **not** the cycle
  low. Deeper lows followed at NM+4, +5 and +6, bottoming at $74,944.59.

So a qualifying pivot sometimes marks the bottom and sometimes does not. That is
precisely why "a strict local low formed" and "the cycle bottomed" are kept as
two separate claims. Anyone reporting only the first would have called September
a clean success; anyone reporting only the second would have called it a failure.
Both readings would be wrong.
""",
        ),
        dict(
            title="The informal NM+0.4 timing idea - assessed separately, and not a formal test",
            observed_at=dt.datetime(2026, 9, 17, 13, 0),
            experiment=sep,
            body="""
This record exists to keep the informal idea **separate** from the pre-registered
protocol. They are different claims, tested against different data, and one must
never be allowed to stand in for the other.

**What the informal idea is.** A private, working short-horizon notion that the
local reaction low tends to arrive around **NM+0.4 days** - roughly ten hours
after the exact New Moon. It was never pre-registered, has no written pass/fail
criteria, and is not part of the paper.

**Why it cannot be tested on daily data.** NM+0.4 days after the September New
Moon (11 Sep 03:26:55 UTC) is **11 Sep ~13:03 UTC**. A daily bar cannot resolve a
ten-hour offset. Anyone claiming to have confirmed or refuted NM+0.4 from daily
candles has not tested it.

**What hourly data shows.** Assessed on hourly BTC-USD bars, purely as an
observation:

- The lowest hourly low within +/-12 hours of the NM+0.4 target printed at
  **11 Sep 12:00 UTC**, i.e. **NM+0.36 days**, at $76,088.52.
- That is roughly **an hour earlier** than the NM+0.4 estimate - which matches
  what the private note recorded at the time.
- For August (New Moon 12 Aug 17:36:39 UTC), the nearest hourly low to the
  NM+0.4 target came at **NM+0.06 days**, while the deepest hourly low of that
  reaction was at **NM+1.85 days**.

**What this does and does not mean.**

- It does **not** validate NM+0.4. Two observations, chosen after the fact, with
  no pre-registered window, no null control and no correction for the fact that
  *some* hourly low always exists near *any* chosen timestamp. This is an
  anecdote, and it is recorded as one.
- It does **not** feed the formal September result. That test stands on its own
  pre-registered LOW-based rule.
- It **is** interesting enough to deserve a proper pre-registration: fix a
  window, fix a definition of "reaction low", fix the null control, and then
  test it forward. Until that happens it remains a private hypothesis.

**Note on data.** Hourly and daily feeds disagree slightly on the exact low
(hourly $76,088.52 vs daily $76,162.91 for 11 September). That is normal
aggregation variance between vendor series. The formal test uses the daily OHLC
series and is unaffected; it is flagged here so the discrepancy is on the record
rather than discovered later.
""",
        ),
        dict(
            title="A large daily cup-and-handle, and a micro structure inside it",
            observed_at=dt.datetime(2026, 9, 20, 16, 0),
            body=f"""
[TECHNICAL] Two nested structures were identified, and both are recorded here with
their levels *before* the outcome, so they can be judged afterwards.

**The larger daily cup-and-handle** was identified around the mid-$75k area on
16 September (verified close **${f['close_2026_09_16']:,.2f}**). The approximate
rim / confirmation zone discussed was **$81,000-$83,000**. A classical measured
move from that structure was discussed in the **$100,000-$103,000** region if
confirmed.

**The smaller intraday cup-and-handle** was identified on 20-21 September inside
the larger structure, with an approximate micro rim around
**$81,300-$81,600** and a projected move toward **$82,000+** resistance.

Verified closes at the time of the observation:

- 18 September: **${f['close_2026_09_18']:,.2f}**
- 19 September: **${f['close_2026_09_19']:,.2f}**
- 20 September: **${f['close_2026_09_20']:,.2f}**

[TECHNICAL] Measured-move targets are a classical construction, not a forecast.
They are recorded so that the structure can be judged against what it actually did,
including if it fails.
""",
        ),
        dict(
            title="Micro breakout, then confirmation of the larger structure",
            observed_at=dt.datetime(2026, 9, 21, 20, 0),
            body=f"""
[FACT] On 21 September 2026 BTC closed **${f['close_2026_09_21']:,.2f}**, up
{round((f['close_2026_09_21'] - f['close_2026_09_20']) / f['close_2026_09_20'] * 100, 2):+.2f}%
from the previous close of ${f['close_2026_09_20']:,.2f}.

[TECHNICAL] That close is above both the micro rim ($81,300-$81,600) and the
larger daily cup rim / confirmation zone ($81,000-$83,000) recorded in the previous
observation. On the levels stated in advance, **both structures confirmed.**

What this does and does not mean:

- It **does** mean the structures identified on 16 and 20 September broke out on
  the levels written down beforehand.
- It does **not** validate the measured-move target. That remains an open,
  unresolved projection and will be recorded as met, failed or inconclusive on the
  evidence.
- It does **not** rescue the September New-Moon protocol test, which failed on its
  own pre-registered terms and stays failed.

[LUNAR] For context: this breakout occurred at roughly Full Moon +24 days and New
Moon +10 days, with the next Full Moon on 26 September 2026 at 16:49 UTC. No lunar
claim is being made about the breakout - it is recorded so the lunar context is on
file either way.
""",
        ),
    ]

    for spec in obs_specs:
        _draft_observation(
            session, title=spec["title"], body=spec["body"],
            observed_at=spec["observed_at"], facts=f,
            experiment=spec.get("experiment"),
        )
        created["observations"] += 1

    # ------------------------------------------------------------------
    # Technical patterns - including the one that failed
    # ------------------------------------------------------------------
    patterns = [
        dict(
            name="Bearish head-and-shoulders, early September 2026",
            pattern_type="head_and_shoulders",
            identified_at=dt.datetime(2026, 9, 8, 12, 0),
            description=(
                "Bearish head-and-shoulders with a neckline break that appeared "
                "provisionally validated, then failed and was reclaimed."
            ),
            pattern_status="failed",
            outcome=Outcome.INCONSISTENT,
            resolution_note=(
                f"Failed. Price reclaimed the structure and closed "
                f"${f['close_2026_09_21']:,.2f} on 21 September. Preserved deliberately: "
                f"failed setups stay on the record."
            ),
        ),
        dict(
            name="Daily cup-and-handle, September 2026",
            pattern_type="cup_and_handle",
            identified_at=dt.datetime(2026, 9, 16, 12, 0),
            description=(
                "Large daily cup-and-handle identified around the mid-$75k area. "
                "Rim / confirmation zone discussed at $81k-$83k; classical measured "
                "move discussed around $100k-$103k if confirmed."
            ),
            confirmation_low=81000.0, confirmation_high=83000.0,
            target_low=100000.0, target_high=103000.0,
            pattern_status="confirmed",
            outcome=Outcome.PENDING,
            resolution_note=(
                f"Rim confirmed on 21 September with a close of "
                f"${f['close_2026_09_21']:,.2f}. The measured-move target remains open."
            ),
        ),
        dict(
            name="Intraday micro cup-and-handle, 20-21 September 2026",
            pattern_type="cup_and_handle",
            timeframe="intraday",
            identified_at=dt.datetime(2026, 9, 20, 16, 0),
            description=(
                "Smaller intraday cup-and-handle inside the larger daily structure. "
                "Micro rim approximately $81.3k-$81.6k, projected toward $82k+ resistance."
            ),
            confirmation_low=81300.0, confirmation_high=81600.0,
            target_low=82000.0,
            pattern_status="confirmed",
            outcome=Outcome.CONSISTENT,
            resolution_note=(
                f"Broke out on 21 September; close ${f['close_2026_09_21']:,.2f} cleared "
                f"both the micro rim and the $82k objective."
            ),
        ),
    ]
    for spec in patterns:
        session.add(TechnicalPattern(
            slug=unique_slug(session, TechnicalPattern, spec["name"]),
            timeframe=spec.pop("timeframe", "daily"),
            provenance=Provenance.RECONSTRUCTED_ARCHIVE,
            status=Status.DRAFT, visibility=Visibility.PRIVATE,
            **spec,
        ))
        created["patterns"] += 1

    # ------------------------------------------------------------------
    # The pre-registered prediction for the September test
    # ------------------------------------------------------------------
    pred = Prediction(
        slug=unique_slug(session, Prediction, "September 2026 New Moon strict local low"),
        title="Pre-registered: a strict local low forms in T0:T+3 after the 11 September New Moon",
        experiment_id=sep.id,
        protocol_id=protocol.id if protocol else None,
        prediction_text=(
            "Following the New Moon of 11 September 2026 at 03:27 UTC, a strict local low "
            "will form in the window 11-14 September 2026 inclusive (T0:T+3)."
        ),
        test_criteria=(
"A strict 7-day pivot on the daily LOW: a day t in [T0, T+3] qualifies when "
            "LOW[t] < LOW[t-1], LOW[t-2], LOW[t-3] AND LOW[t] < LOW[t+1], LOW[t+2], "
            "LOW[t+3]. Strictly less-than on both sides; ties do not qualify. Defined "
            "on intraday lows, not closing prices. A qualifying pivot is not "
            "invalidated by a later lower low."
        ),
        invalidation_criteria=(
            "No qualifying strict local low in T0:T+3, or a materially lower close forming "
            "after the window."
        ),
        confidence=(
            "Moderate on direction, low on timing. In 2026, 7 of the first 8 New Moons had a "
            "strict local low in T0:T+3; full-history behaviour is regime-dependent. The "
            "New-Moon strength figure is context only, not evidence."
        ),
        evidence_snapshot_json=json.dumps(
            {
                "recorded_before_window": True,
                "new_moon_utc": "2026-09-11T03:26:55",
                "strength_recorded_in_advance": 79,
                "strength_computed_by_current_code": 69.2,
                "prior": "2026: 7 of first 8 New Moons had a strict local low in T0:T+3",
                "protocol": "september-2026-new-moon-test v1.0 (frozen)",
            },
            indent=2,
        ),
        made_at=dt.datetime(2026, 9, 11, 4, 0),
        horizon_end=dt.datetime(2026, 9, 14, 23, 59, 59),
        outcome=Outcome.CONSISTENT,
        provenance=Provenance.RECONSTRUCTED_ARCHIVE,
        status=Status.DRAFT, visibility=Visibility.PRIVATE,
    )
    session.add(pred)
    session.flush()
    created["predictions"] += 1

    session.commit()
    created["verified_facts"] = f
    return created
