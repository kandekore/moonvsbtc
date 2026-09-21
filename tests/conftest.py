"""Shared test fixtures.

Every test runs against SQLite in a temp file and a frozen BTC price CSV, so
the suite never touches MySQL, the network or the user's real database.
"""
from __future__ import annotations

import os
import pathlib
import tempfile

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
PRICE_CSV = FIXTURES / "btc_daily_20260921.csv"

# Point the app at a throwaway database *before* btcmoon.db is imported.
_tmpdir = tempfile.mkdtemp(prefix="btcmoon-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmpdir}/test.db"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["AI_ENABLED"] = "false"
os.environ["OPENAI_API_KEY"] = ""


@pytest.fixture(scope="session")
def price_df():
    """The frozen BTC-USD daily close history used by the regression tests."""
    import pandas as pd

    df = pd.read_csv(PRICE_CSV, index_col=0, parse_dates=True)
    df.index.name = "Date"
    return df


@pytest.fixture()
def db_session():
    from btcmoon.db import Base, SessionFactory, engine

    Base.metadata.create_all(engine)
    s = SessionFactory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture()
def app():
    from btcmoon.app import create_app
    from btcmoon.db import Base, engine

    Base.metadata.create_all(engine)
    application = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    return application


@pytest.fixture()
def client(app):
    return app.test_client()
