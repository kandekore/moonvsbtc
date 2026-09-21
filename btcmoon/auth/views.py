"""Sign-in for the Editor, and free reader accounts.

There is NO public signup for admin (spec s20). Admin users are created from
the command line with ``python manage.py create-admin``.
"""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..db import Session
from ..models import Role, User, utcnow

bp = Blueprint("auth", __name__)


def _safe_next(target: str | None) -> str:
    """Only allow same-site redirects."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return url_for("public.home")
    return target


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("public.home"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = Session.query(User).filter_by(email=email).one_or_none()

        if user and user.is_active and user.check_password(password):
            login_user(user, remember=bool(request.form.get("remember")))
            user.last_login_at = utcnow()
            Session.commit()
            return redirect(_safe_next(request.args.get("next")))

        # Deliberately identical message for unknown user and bad password.
        flash("Incorrect email or password.", "error")

    return render_template("auth/login.html", title="Sign in")


@bp.route("/logout", methods=["POST", "GET"])
@login_required
def logout():
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("public.home"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    """Free reader accounts.

    Everything is free through 31 Dec 2026; an account exists so the newsletter
    and, later, subscriber entitlements have something to hang off. A reader
    account can never become an admin account through this route.
    """
    if current_user.is_authenticated:
        return redirect(url_for("public.home"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        display = (request.form.get("display_name") or "").strip()

        if not email or "@" not in email:
            flash("Please enter a valid email address.", "error")
        elif len(password) < 10:
            flash("Please choose a password of at least 10 characters.", "error")
        elif Session.query(User.id).filter_by(email=email).first():
            flash("That email address is already registered.", "error")
        else:
            user = User(email=email, display_name=display or email.split("@")[0],
                        role=Role.READER)   # never Role.ADMIN from a web form
            user.set_password(password)
            Session.add(user)
            Session.commit()
            login_user(user)
            flash("Account created. Everything is free through 31 December 2026.", "success")
            return redirect(url_for("public.home"))

    return render_template("auth/register.html", title="Create a free account")
