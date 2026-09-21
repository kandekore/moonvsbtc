"""Re-evaluate every frozen protocol against the latest market data.

    python -m jobs.evaluate_protocols [--force]

Cron: 30 0 * * *

This NEVER modifies a protocol. It only measures the world against the rules
that were registered in advance, and writes the measurement into the job detail
so the Editor can see it in the admin.
"""
from __future__ import annotations

import datetime as dt
import json
import sys

from btcmoon.market_data import get_price_history
from btcmoon.models import ResearchProtocol
from btcmoon.research import evaluate_nm_low_test

from .base import run_job


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    force = "--force" in argv

    def work(session, run):
        price = get_price_history(force_refresh=True)
        findings = []
        for proto in session.query(ResearchProtocol).filter(
            ResearchProtocol.is_frozen.is_(True)
        ).all():
            rules = json.loads(proto.rules_json or "{}")
            nm_raw = rules.get("new_moon_utc")
            if not nm_raw:
                continue
            nm_date = dt.datetime.fromisoformat(nm_raw.replace("Z", "")).date()
            test = evaluate_nm_low_test(price, nm_date)
            findings.append({"protocol": proto.slug, "result": test.to_dict()})
        session.commit()
        return json.dumps(findings, indent=2) if findings else "no dated protocols to evaluate"

    return run_job("evaluate_protocols", work, force=force)


if __name__ == "__main__":
    raise SystemExit(main())
