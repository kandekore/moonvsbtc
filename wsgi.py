"""WSGI entry point.

    gunicorn -w 3 -b 127.0.0.1:8000 wsgi:application

``ProxyFix`` is applied because in production LiteSpeed terminates HTTPS and
forwards over plain HTTP to 127.0.0.1. Without it Flask believes every request
is http://, and canonical URLs, the sitemap and OpenGraph tags all emit the
wrong scheme. The proxy sets X-Forwarded-Proto (see
deploy/litespeed-cpanel-proxy.conf); we trust exactly one hop.
"""
from __future__ import annotations

import os

from werkzeug.middleware.proxy_fix import ProxyFix

from btcmoon.app import create_app

application = create_app()

# Only trust forwarded headers when something is actually in front of us.
# Set TRUST_PROXY=false if you ever expose gunicorn directly.
if os.getenv("TRUST_PROXY", "true").strip().lower() in {"1", "true", "yes", "on"}:
    application.wsgi_app = ProxyFix(
        application.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
    )

app = application

if __name__ == "__main__":
    application.run(host="127.0.0.1", port=5000)
