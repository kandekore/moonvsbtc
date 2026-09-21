"""RSS/news ingestion.

    python -m jobs.ingest_news [--force]

Cron: 15 * * * *  (hourly)

Deterministic and free: no AI call is made per item.
"""
from __future__ import annotations

import datetime as dt
import sys

from btcmoon.news import ingest_all

from .base import run_job


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    force = "--force" in argv

    def work(session, run):
        report = ingest_all(session)
        session.commit()
        return (
            f"feeds={report.fetched} inserted={report.inserted} "
            f"duplicates={report.duplicates} errors={len(report.errors)}"
            + (f" :: {'; '.join(report.errors[:5])}" if report.errors else "")
        )

    # Hourly, so the idempotency key includes the hour.
    key = dt.datetime.now().strftime("%Y-%m-%dT%H")
    return run_job("ingest_news", work, key_suffix=key, force=force)


if __name__ == "__main__":
    raise SystemExit(main())
