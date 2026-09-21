"""Passenger entry point for cPanel/LiteSpeed "Setup Python App".

cPanel's Python App manager (Passenger + LSAPI) looks for this file in the
application root and imports ``application`` from it.

Two things matter here and are easy to get wrong:

1. Passenger does not necessarily run with the application root on sys.path,
   so we add it explicitly.
2. Passenger does not load .env for you. ``btcmoon.config`` calls
   ``load_dotenv()`` at import time, which reads .env from the current working
   directory - so we chdir to the application root first.

After ANY code change you must restart the app:  touch tmp/restart.txt
"""
from __future__ import annotations

import os
import sys

APP_ROOT = os.path.dirname(os.path.abspath(__file__))

if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

# So load_dotenv() finds .env and relative paths (.cache) resolve correctly.
os.chdir(APP_ROOT)

from btcmoon.app import create_app  # noqa: E402  (must follow the path setup)

application = create_app()
