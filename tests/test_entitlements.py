"""Free through 31 Dec 2026, with the paywall machinery ready (spec s14)."""
from __future__ import annotations

import datetime as dt

from btcmoon.auth.decorators import has_entitlement, requires_entitlement
from btcmoon.config import Config
from btcmoon.models import Role, Subscription, User, utcnow


def test_free_until_is_end_of_2026():
    assert Config.free_until_date() == dt.date(2026, 12, 31)


def test_paywall_is_disabled_by_default():
    assert Config.PAYWALL_ENABLED is False


def test_nothing_is_gated_while_the_paywall_is_off(monkeypatch):
    monkeypatch.setattr(Config, "PAYWALL_ENABLED", False)
    assert requires_entitlement("outlooks") is False


def test_nothing_is_gated_during_the_free_period(monkeypatch):
    """Even with the paywall switched on, the free period wins until 2027."""
    monkeypatch.setattr(Config, "PAYWALL_ENABLED", True)
    monkeypatch.setattr(Config, "FREE_UNTIL", "2099-12-31")
    assert requires_entitlement("outlooks") is False


def test_gating_activates_after_the_free_period(monkeypatch):
    monkeypatch.setattr(Config, "PAYWALL_ENABLED", True)
    monkeypatch.setattr(Config, "FREE_UNTIL", "2020-01-01")
    assert requires_entitlement("outlooks") is True


def test_empty_entitlement_key_never_gates():
    assert requires_entitlement("") is False


def test_subscriber_entitlement_is_honoured(db_session):
    user = User(email=f"sub-{utcnow().timestamp()}@example.com", role=Role.SUBSCRIBER)
    user.set_password("a-very-long-password")
    db_session.add(user)
    db_session.flush()
    db_session.add(Subscription(user_id=user.id, plan="supporter", status="active",
                                entitlements="outlooks,archive"))
    db_session.flush()
    db_session.refresh(user)

    assert has_entitlement(user, "outlooks") is True
    assert has_entitlement(user, "archive") is True
    assert has_entitlement(user, "something-else") is False


def test_expired_subscription_grants_nothing(db_session):
    user = User(email=f"exp-{utcnow().timestamp()}@example.com", role=Role.SUBSCRIBER)
    user.set_password("a-very-long-password")
    db_session.add(user)
    db_session.flush()
    db_session.add(Subscription(user_id=user.id, status="active",
                                entitlements="outlooks",
                                ends_on=dt.date.today() - dt.timedelta(days=1)))
    db_session.flush()
    db_session.refresh(user)
    assert has_entitlement(user, "outlooks") is False


def test_admin_has_every_entitlement(db_session):
    admin = User(email=f"adm-{utcnow().timestamp()}@example.com", role=Role.ADMIN)
    admin.set_password("a-very-long-password")
    db_session.add(admin)
    db_session.flush()
    assert has_entitlement(admin, "anything-at-all") is True


def test_subscriber_role_does_not_grant_admin(db_session):
    """Subscriber auth and admin permissions are separate axes (spec s20)."""
    user = User(email=f"nope-{utcnow().timestamp()}@example.com", role=Role.SUBSCRIBER)
    db_session.add(user)
    db_session.flush()
    db_session.add(Subscription(user_id=user.id, status="active", entitlements="*"))
    db_session.flush()
    db_session.refresh(user)

    assert has_entitlement(user, "outlooks") is True   # full entitlements
    assert user.is_admin is False                       # but still not an admin


def test_web_registration_cannot_create_an_admin(client, db_session):
    email = f"selfreg-{int(utcnow().timestamp())}@example.com"
    client.post("/account/register", data={
        "email": email, "password": "a-very-long-password", "role": "admin",
        "display_name": "Sneaky",
    })
    user = db_session.query(User).filter_by(email=email).one_or_none()
    assert user is not None
    assert user.role == Role.READER
    assert user.is_admin is False
