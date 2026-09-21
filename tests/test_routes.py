"""Public routes, SEO surfaces and admin authorization."""
from __future__ import annotations

import datetime as dt

import pytest

from btcmoon.models import Article, Provenance, Role, Status, User, Visibility, utcnow

PUBLIC_PATHS = [
    "/", "/experiment/", "/observations/", "/predictions/", "/btc-natal-chart/",
    "/outlooks/", "/methodology/", "/news/", "/about/", "/research/",
    "/transit-calendar/", "/sitemap.xml", "/robots.txt",
    "/account/login", "/account/register",
]

ADMIN_PATHS = [
    "/admin/", "/admin/companion/", "/admin/briefings/", "/admin/costs/",
    "/admin/news/", "/admin/jobs/", "/admin/settings/",
    "/admin/content/articles/", "/admin/content/predictions/",
]


@pytest.mark.parametrize("path", PUBLIC_PATHS)
def test_public_pages_render(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_admin_requires_authentication(client, path):
    resp = client.get(path)
    assert resp.status_code in (302, 401), f"{path} was not protected"
    if resp.status_code == 302:
        assert "/account/login" in resp.headers["Location"]


def test_non_admin_user_is_forbidden_from_admin(app, client, db_session):
    """A signed-in reader gets 403, not a login redirect - they ARE authenticated,
    they are simply not authorised."""
    email = f"reader-{int(utcnow().timestamp() * 1000)}@example.com"
    password = "a-very-long-password"
    user = User(email=email, role=Role.READER)
    user.set_password(password)
    db_session.add(user)
    db_session.commit()

    resp = client.post("/account/login", data={"email": email, "password": password})
    assert resp.status_code == 302, "login did not succeed"

    assert client.get("/admin/").status_code == 403


def test_admin_user_reaches_the_laboratory(app, client, db_session):
    email = f"editor-{int(utcnow().timestamp() * 1000)}@example.com"
    password = "a-very-long-password"
    admin = User(email=email, role=Role.ADMIN)
    admin.set_password(password)
    db_session.add(admin)
    db_session.commit()

    client.post("/account/login", data={"email": email, "password": password})
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert "Private research laboratory" in resp.get_data(as_text=True)


def test_wrong_password_is_rejected(app, client, db_session):
    email = f"wrong-{int(utcnow().timestamp() * 1000)}@example.com"
    user = User(email=email, role=Role.ADMIN)
    user.set_password("the-correct-password")
    db_session.add(user)
    db_session.commit()

    resp = client.post("/account/login",
                       data={"email": email, "password": "not-the-password"})
    assert resp.status_code == 200          # re-renders the form, no redirect
    assert client.get("/admin/").status_code in (302, 401)


def test_missing_page_returns_404(client):
    assert client.get("/no-such-page/").status_code == 404
    assert client.get("/research/not-a-real-slug/").status_code == 404
    assert client.get("/predictions/not-a-real-slug/").status_code == 404


def test_unpublished_article_is_not_reachable_by_url(client, db_session):
    db_session.add(Article(slug="secret-draft", title="Secret draft",
                           status=Status.DRAFT, visibility=Visibility.PRIVATE))
    db_session.commit()
    assert client.get("/research/secret-draft/").status_code == 404


def test_published_article_is_reachable(client, db_session):
    db_session.add(Article(
        slug="live-article", title="A live article",
        body_markdown="## Heading\n\nSome **text**.",
        summary="A summary.", status=Status.PUBLISHED,
        visibility=Visibility.PUBLIC, published_at=utcnow(),
        provenance=Provenance.EDITOR,
    ))
    db_session.commit()
    resp = client.get("/research/live-article/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "A live article" in body
    assert "<h2" in body                       # markdown rendered
    assert "application/ld+json" in body       # structured data present


def test_robots_blocks_private_areas(client):
    body = client.get("/robots.txt").get_data(as_text=True)
    assert "Disallow: /admin/" in body
    assert "Disallow: /account/" in body
    assert "Sitemap:" in body


def test_sitemap_lists_only_published_content(client, db_session):
    db_session.add_all([
        Article(slug="sm-published", title="Published", status=Status.PUBLISHED,
                visibility=Visibility.PUBLIC, published_at=utcnow()),
        Article(slug="sm-draft", title="Draft", status=Status.DRAFT,
                visibility=Visibility.PRIVATE),
    ])
    db_session.commit()
    body = client.get("/sitemap.xml").get_data(as_text=True)
    assert "sm-published" in body
    assert "sm-draft" not in body
    assert body.startswith('<?xml')


def test_every_public_page_carries_the_experiment_disclaimer(client):
    for path in ("/", "/methodology/", "/btc-natal-chart/"):
        body = client.get(path).get_data(as_text=True)
        assert "not investment advice" in body.lower()


def test_natal_page_states_its_assumptions(client):
    body = client.get("/btc-natal-chart/").get_data(as_text=True)
    assert "2009-01-03T18:15:05" in body
    assert "no established causal mechanism" in body.lower()


def test_markdown_output_is_sanitised(client, db_session):
    """AI-drafted markdown is never trusted into the DOM unescaped."""
    db_session.add(Article(
        slug="xss-test", title="Sanitising test",
        body_markdown='Hello <script>alert("xss")</script> world '
                      '<img src=x onerror="alert(1)">',
        status=Status.PUBLISHED, visibility=Visibility.PUBLIC,
        published_at=utcnow(),
    ))
    db_session.commit()
    body = client.get("/research/xss-test/").get_data(as_text=True)
    assert "<script>" not in body
    assert "onerror" not in body
