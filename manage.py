#!/usr/bin/env python
"""Management CLI.

    python manage.py init-db          # create tables directly (dev/first run)
    python manage.py bootstrap        # protocols, news sources, default settings
    python manage.py seed-archive     # reconstructed Aug/Sep 2026 drafts
    python manage.py create-admin     # create the Editor account (no web signup)
    python manage.py reset-password
    python manage.py status           # environment + data health check
    python manage.py run              # dev server
"""
from __future__ import annotations

import argparse
import getpass
import sys


def cmd_init_db(args) -> int:
    from btcmoon.db import init_db, engine

    init_db()
    print(f"Tables created on {engine.url.render_as_string(hide_password=True)}")
    return 0


def cmd_bootstrap(args) -> int:
    from btcmoon.db import SessionFactory
    from btcmoon.seeds import bootstrap

    with SessionFactory() as s:
        result = bootstrap(s)
    print(f"Bootstrap: {result}")
    return 0


def cmd_seed_archive(args) -> int:
    from btcmoon.db import SessionFactory
    from btcmoon.seeds import seed_archive

    with SessionFactory() as s:
        result = seed_archive(s)
    if "skipped" in result:
        print(f"Archive: {result['skipped']}")
        return 0
    print(
        f"Archive seeded as DRAFTS: {result['experiments']} experiments, "
        f"{result['observations']} observations, {result['predictions']} predictions, "
        f"{result['patterns']} technical patterns."
    )
    print("Nothing is public. Review and publish each record in /admin.")
    return 0


def cmd_create_admin(args) -> int:
    from btcmoon.db import SessionFactory
    from btcmoon.models import Role, User

    email = args.email or input("Admin email: ").strip().lower()
    if not email or "@" not in email:
        print("A valid email address is required.", file=sys.stderr)
        return 1

    with SessionFactory() as s:
        existing = s.query(User).filter_by(email=email).one_or_none()
        if existing:
            print(f"{email} already exists with role '{existing.role}'.", file=sys.stderr)
            return 1
        password = args.password or getpass.getpass("Password (min 12 chars): ")
        if len(password) < 12:
            print("Password must be at least 12 characters.", file=sys.stderr)
            return 1
        if not args.password:
            if password != getpass.getpass("Confirm password: "):
                print("Passwords do not match.", file=sys.stderr)
                return 1
        user = User(email=email, display_name=args.name or email.split("@")[0],
                    role=Role.ADMIN, is_active=True)
        user.set_password(password)
        s.add(user)
        s.commit()
    print(f"Admin created: {email}. Sign in at /account/login then go to /admin/.")
    return 0


def cmd_reset_password(args) -> int:
    from btcmoon.db import SessionFactory
    from btcmoon.models import User

    email = args.email or input("Email: ").strip().lower()
    with SessionFactory() as s:
        user = s.query(User).filter_by(email=email).one_or_none()
        if not user:
            print(f"No user {email}.", file=sys.stderr)
            return 1
        password = args.password or getpass.getpass("New password (min 12 chars): ")
        if len(password) < 12:
            print("Password must be at least 12 characters.", file=sys.stderr)
            return 1
        user.set_password(password)
        s.commit()
    print(f"Password updated for {email}.")
    return 0


def cmd_status(args) -> int:
    import datetime as dt

    from btcmoon.ai import AiClient, budget_status
    from btcmoon.config import Config
    from btcmoon.db import SessionFactory, engine
    from btcmoon.models import (
        Article, Experiment, NewsItem, Observation, Outlook, Prediction,
        ResearchBriefing, ResearchProtocol, ScheduledJobRun, Source, Status, User,
    )

    print("=" * 62)
    print(" Bitcoin vs The Moon - system status")
    print("=" * 62)
    print(f" Database : {engine.url.render_as_string(hide_password=True)}")
    print(f" Site URL : {Config.SITE_URL}")
    print(f" Free until: {Config.FREE_UNTIL}  (paywall enabled: {Config.PAYWALL_ENABLED})")

    with SessionFactory() as s:
        try:
            counts = {
                "users": s.query(User).count(),
                "admins": s.query(User).filter_by(role="admin").count(),
                "protocols": s.query(ResearchProtocol).count(),
                "experiments": s.query(Experiment).count(),
                "observations": s.query(Observation).count(),
                "predictions": s.query(Prediction).count(),
                "articles": s.query(Article).count(),
                "outlooks": s.query(Outlook).count(),
                "briefings": s.query(ResearchBriefing).count(),
                "news_sources": s.query(Source).count(),
                "news_items": s.query(NewsItem).count(),
                "job_runs": s.query(ScheduledJobRun).count(),
            }
        except Exception as exc:
            print(f"\n DATABASE ERROR: {exc}")
            print(" Run: python manage.py init-db")
            return 1

        print("\n Data:")
        for k, v in counts.items():
            print(f"   {k:16s} {v}")

        published = {
            "articles": s.query(Article).filter(Article.status == Status.PUBLISHED).count(),
            "observations": s.query(Observation).filter(Observation.status == Status.PUBLISHED).count(),
            "predictions": s.query(Prediction).filter(Prediction.status == Status.PUBLISHED).count(),
            "outlooks": s.query(Outlook).filter(Outlook.status == Status.PUBLISHED).count(),
        }
        print("\n Published (live on the public site):")
        for k, v in published.items():
            print(f"   {k:16s} {v}")

        b = budget_status(s)
        print(f"\n AI spend: ${b.month_spend:.4f} of ${b.month_budget:.2f} this month "
              f"({b.month_pct}%){'  [CEILING REACHED]' if b.blocked else ''}")

        ok, why = AiClient(s).availability()
        print(f" AI status: {'available' if ok else 'unavailable'}")
        if not ok:
            print(f"   {why}")

        if counts["admins"] == 0:
            print("\n  ! No admin user. Run: python manage.py create-admin")

    try:
        from btcmoon.market_data import technical_context

        t = technical_context()
        print(f"\n Market: BTC ${t['price']:,.2f} as of {t['as_of']} ({t['regime']})")
    except Exception as exc:
        print(f"\n Market data unavailable: {exc}")

    print("=" * 62)
    return 0


def cmd_run(args) -> int:
    from btcmoon.app import create_app

    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="manage.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create all tables directly").set_defaults(func=cmd_init_db)
    sub.add_parser("bootstrap", help="seed protocols, sources, settings").set_defaults(func=cmd_bootstrap)
    sub.add_parser("seed-archive", help="import the reconstructed Aug/Sep 2026 drafts").set_defaults(func=cmd_seed_archive)
    sub.add_parser("status", help="environment and data health check").set_defaults(func=cmd_status)

    p = sub.add_parser("create-admin", help="create an Editor account")
    p.add_argument("--email"); p.add_argument("--password"); p.add_argument("--name")
    p.set_defaults(func=cmd_create_admin)

    p = sub.add_parser("reset-password")
    p.add_argument("--email"); p.add_argument("--password")
    p.set_defaults(func=cmd_reset_password)

    p = sub.add_parser("run", help="development server (do NOT use in production)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--debug", action="store_true")
    p.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
