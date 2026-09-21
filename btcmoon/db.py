"""SQLAlchemy engine/session plumbing.

Works standalone (for cron jobs) and inside Flask (scoped to the request).
Production is MySQL/utf8mb4; SQLite is a local-development convenience only.
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker

from .config import Config


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    kwargs: dict = {"echo": Config.SQLALCHEMY_ECHO, "future": True}
    if url.startswith("mysql"):
        kwargs.update(
            pool_pre_ping=True,
            pool_recycle=280,          # below MySQL's default wait_timeout
            connect_args={"charset": "utf8mb4"},
        )
    elif url.startswith("sqlite"):
        kwargs.update(connect_args={"check_same_thread": False})
    return kwargs


engine = create_engine(Config.DATABASE_URL, **_engine_kwargs(Config.DATABASE_URL))

if Config.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - dev only
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
Session = scoped_session(SessionFactory)


@contextmanager
def session_scope():
    """Transactional scope for scripts and jobs."""
    s = SessionFactory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def init_db() -> None:
    """Create all tables directly (used for tests and first-run bootstrap).

    Production schema changes go through Alembic; this is the fast path.
    """
    from . import models  # noqa: F401  (registers mappers)

    Base.metadata.create_all(engine)
