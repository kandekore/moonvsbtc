"""Generic WSGI entry point.

    gunicorn  -w 3 -b 127.0.0.1:8000 wsgi:application
    uwsgi     --module wsgi:application
"""
from __future__ import annotations

from btcmoon.app import create_app

application = create_app()
app = application

if __name__ == "__main__":
    application.run(host="127.0.0.1", port=5000)
