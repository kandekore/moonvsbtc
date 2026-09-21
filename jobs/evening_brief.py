"""Evening research briefing.

    python -m jobs.evening_brief [--force]

Cron: 0 18 * * *  (Europe/London)
"""
from __future__ import annotations

import sys

from btcmoon.models import BriefingKind

from .base import run_job
from .briefing import generate_briefing


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    force = "--force" in argv

    def work(session, run):
        b = generate_briefing(session, BriefingKind.EVENING, job_run_id=run.id)
        session.commit()
        return f"briefing #{b.id} triage={b.triage} ai={b.ai_generated} cost=${b.estimated_cost_usd:.4f}"

    return run_job("evening_brief", work, force=force)


if __name__ == "__main__":
    raise SystemExit(main())
