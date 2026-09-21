"""Flask application factory.

Architecture note (spec s5): the public editorial/SEO site and the private
admin/Companion both live in this ONE Flask process. Server-rendered Jinja
pages give us canonical URLs, metadata, structured data and a sitemap that a
Streamlit-only site cannot, and a single WSGI app is the simplest thing to run
under LiteSpeed/Passenger. The existing Streamlit dashboard is retained,
unchanged, as an optional private research tool - see DEPLOYMENT.md.
"""
from __future__ import annotations

import datetime as dt

from flask import Flask, g, render_template, request

from .config import Config
from .db import Session


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static",
    )
    app.config.from_object(Config)
    app.config.setdefault("TESTING", False)
    if overrides:
        app.config.update(overrides)

    _register_extensions(app)
    _register_blueprints(app)
    _register_context(app)
    _register_errors(app)

    @app.teardown_appcontext
    def _remove_session(_exc=None):
        Session.remove()

    return app


def _register_extensions(app: Flask) -> None:
    from flask_login import LoginManager
    from flask_wtf.csrf import CSRFProtect

    if app.config.get("WTF_CSRF_ENABLED", True):
        CSRFProtect(app)

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.session_protection = "strong"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        from .models import User

        try:
            return Session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    # Rate limiting protects the AI endpoints (spec s20).
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address

        limiter = Limiter(
            get_remote_address,
            app=app,
            default_limits=[],
            storage_uri=app.config.get("RATELIMIT_STORAGE_URI", "memory://"),
            enabled=not app.config.get("TESTING", False),
        )
        app.extensions["limiter"] = limiter
    except Exception:                       # limiter is a nice-to-have, not a hard dep
        app.extensions["limiter"] = None


def _register_blueprints(app: Flask) -> None:
    from .admin.views import bp as admin_bp
    from .auth.views import bp as auth_bp
    from .web.views import bp as public_bp
    from .web.seo import bp as seo_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(seo_bp)
    app.register_blueprint(auth_bp, url_prefix="/account")
    app.register_blueprint(admin_bp, url_prefix="/admin")


def _register_context(app: Flask) -> None:
    from .web.filters import register_filters

    register_filters(app)

    @app.context_processor
    def inject_globals():
        from .models import Status, Visibility

        free_until = Config.free_until_date()
        return {
            "SITE_NAME": Config.SITE_NAME,
            "SITE_URL": Config.SITE_URL,
            "SITE_TAGLINE": Config.SITE_TAGLINE,
            "EDITOR_NAME": Config.EDITOR_NAME,
            "PAYWALL_ENABLED": Config.PAYWALL_ENABLED,
            "FREE_UNTIL": free_until,
            "IS_FREE_PERIOD": dt.date.today() <= free_until,
            "now": dt.datetime.now(),
            "current_year": dt.date.today().year,
            "Status": Status,
            "Visibility": Visibility,
        }


def _register_errors(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(500)
    def server_error(_e):
        Session.rollback()
        return render_template("errors/500.html"), 500
