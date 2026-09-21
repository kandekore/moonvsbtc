"""Generate tomorrow's BTC natal outlook as a DRAFT.

    python -m jobs.daily_outlook [--force] [--days N] [--publish]

Cron: 0 19 * * *

Daily outlooks are generated one day in advance (spec s14). They are created as
drafts: nothing reaches the public site without the Editor publishing it. The
``--publish`` flag exists for the Editor's own convenience and is deliberately
NOT part of the recommended cron line.
"""
from __future__ import annotations

import datetime as dt
import sys

from btcmoon.astrology.outlooks import build_outlook
from btcmoon.editorial import publish
from btcmoon.models import OutlookKind

from .base import run_job


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    force = "--force" in argv
    auto_publish = "--publish" in argv
    days = 1
    if "--days" in argv:
        try:
            days = int(argv[argv.index("--days") + 1])
        except (IndexError, ValueError):
            days = 1

    target = dt.date.today() + dt.timedelta(days=days)

    def work(session, run):
        outlook = build_outlook(session, target, OutlookKind.DAILY)
        if auto_publish:
            publish(session, outlook)
        session.commit()
        return (
            f"outlook #{outlook.id} for {target.isoformat()} "
            f"status={outlook.status} ai={outlook.ai_generated} "
            f"cost=${outlook.estimated_cost_usd:.4f}"
        )

    return run_job("daily_outlook", work, key_suffix=target.isoformat(), force=force)


if __name__ == "__main__":
    raise SystemExit(main())
