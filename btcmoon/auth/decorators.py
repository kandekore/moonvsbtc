"""Server-side authorization.

Admin is checked on the server on every request - never inferred from a
template or a client-side flag (spec s20). Subscriber entitlements are a
separate axis and can never grant admin.
"""
from __future__ import annotations

import datetime as dt
from functools import wraps

from flask import abort, redirect, request, url_for
from flask_login import current_user

from ..config import Config


def admin_required(view):
    """Only an active admin user may proceed."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.full_path))
        if not getattr(current_user, "is_admin", False):
            abort(403)
        return view(*args, **kwargs)

    return wrapper


def entitlement_required(key: str):
    """Gate content behind an entitlement.

    While ``PAYWALL_ENABLED`` is false, or we are inside the free period, this
    always allows access. The plumbing exists now so switching the paywall on
    later is a config change, not a rebuild (spec s14).
    """
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not requires_entitlement(key):
                return view(*args, **kwargs)
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.full_path))
            if not has_entitlement(current_user, key):
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def requires_entitlement(key: str) -> bool:
    """Is this entitlement actually enforced right now?"""
    if not key:
        return False
    if not Config.PAYWALL_ENABLED:
        return False
    return dt.date.today() > Config.free_until_date()


def has_entitlement(user, key: str) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_admin", False):
        return True
    today = dt.date.today()
    for sub in getattr(user, "subscriptions", []):
        if sub.status != "active":
            continue
        if sub.ends_on and sub.ends_on < today:
            continue
        granted = {e.strip() for e in (sub.entitlements or "").split(",") if e.strip()}
        if key in granted or "*" in granted:
            return True
    return False
