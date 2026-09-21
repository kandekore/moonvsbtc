"""Store the daily BTC market snapshot.

    python -m jobs.snapshot_market [--force]

Cron: 5 0 * * *
"""
from __future__ import annotations

import sys

from btcmoon.market_data import get_price_history, latest_snapshot

from .base import run_job


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    force = "--force" in argv

    def work(session, run):
        price = get_price_history(force_refresh=True)
        snap = latest_snapshot(session, price)
        session.commit()
        return f"snapshot {snap.snapshot_date} close=${snap.close:,.2f}"

    return run_job("snapshot_market", work, force=force)


if __name__ == "__main__":
    raise SystemExit(main())
