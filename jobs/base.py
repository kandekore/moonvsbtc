"""Shared job runner: idempotency, logging and error capture (spec s6, s20)."""
from __future__ import annotations

import datetime as dt
import logging
import sys
import traceback
from contextlib import contextmanager

from btcmoon.db import SessionFactory
from btcmoon.models import JobStatus, ScheduledJobRun, utcnow

log = logging.getLogger("btcmoon.jobs")


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )


class JobSkipped(RuntimeError):
    """Raised when an idempotency key has already completed successfully."""


@contextmanager
def job_run(job_name: str, key_suffix: str | None = None, force: bool = False):
    """Run a job exactly once per idempotency key.

    Yields ``(session, run)``. On success the run is marked ``success``; on an
    exception it is marked ``error`` with the traceback, and the exception is
    re-raised so cron sees a non-zero exit code.
    """
    suffix = key_suffix or dt.date.today().isoformat()
    key = f"{job_name}:{suffix}"
    session = SessionFactory()

    existing = session.query(ScheduledJobRun).filter_by(idempotency_key=key).one_or_none()
    if existing and existing.status == JobStatus.SUCCESS and not force:
        log.info("Job %s already completed for key %s; skipping.", job_name, key)
        session.close()
        raise JobSkipped(key)

    if existing:
        run = existing
        run.attempt += 1
        run.status = JobStatus.RUNNING
        run.started_at = utcnow()
        run.finished_at = None
        run.error = ""
    else:
        run = ScheduledJobRun(job_name=job_name, idempotency_key=key,
                              status=JobStatus.RUNNING)
        session.add(run)
    session.commit()

    try:
        yield session, run
    except Exception as exc:
        session.rollback()
        run.status = JobStatus.ERROR
        run.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"[:60000]
        run.finished_at = utcnow()
        session.commit()
        log.error("Job %s FAILED: %s", job_name, exc)
        raise
    else:
        run.status = JobStatus.SUCCESS
        run.finished_at = utcnow()
        session.commit()
        log.info("Job %s completed in %.1fs: %s",
                 job_name, run.duration_seconds or 0.0, run.detail[:200])
    finally:
        session.close()


def run_job(job_name: str, fn, key_suffix: str | None = None, force: bool = False) -> int:
    """Entry point wrapper returning a process exit code."""
    configure_logging()
    try:
        with job_run(job_name, key_suffix, force) as (session, run):
            detail = fn(session, run)
            if detail:
                run.detail = str(detail)[:60000]
    except JobSkipped:
        return 0
    except Exception:
        return 1
    return 0
