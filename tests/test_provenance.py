"""Historical provenance: never fake a publication date (spec s10, Appendix)."""
from __future__ import annotations

import datetime as dt

from btcmoon.editorial import publish
from btcmoon.editorial.serializers import provenance_notice
from btcmoon.models import (
    Article, Observation, Provenance, Status, Visibility, utcnow,
)


def test_observed_at_and_published_at_are_separate_columns(db_session):
    """The date something happened and the date we published it are not the same."""
    observed = dt.datetime(2026, 8, 30, 10, 0)
    obs = Observation(slug="aug-note", title="August note", observed_at=observed,
                      provenance=Provenance.RECONSTRUCTED_ARCHIVE)
    db_session.add(obs)
    db_session.flush()
    publish(db_session, obs)

    assert obs.observed_at == observed
    assert obs.published_at is not None
    assert obs.published_at > observed          # published later, honestly


def test_publishing_never_backdates(db_session):
    """Publication time is always now, even for a historical piece."""
    before = utcnow()
    art = Article(slug="recon", title="Reconstructed piece",
                  observed_at=dt.datetime(2026, 8, 12, 9, 0),
                  provenance=Provenance.RECONSTRUCTED_ARCHIVE)
    db_session.add(art)
    db_session.flush()
    publish(db_session, art)

    assert art.published_at >= before
    assert art.published_at.date() == dt.date.today()
    assert art.observed_at.date() == dt.date(2026, 8, 12)


def test_reconstructed_records_carry_a_visible_notice(db_session):
    art = Article(
        slug="recon-2", title="Reconstructed",
        observed_at=dt.datetime(2026, 8, 30, 10, 0),
        published_at=utcnow(),
        provenance=Provenance.RECONSTRUCTED_ARCHIVE,
        status=Status.PUBLISHED, visibility=Visibility.PUBLIC,
    )
    notice = provenance_notice(art)
    assert notice is not None
    assert "Reconstructed archive entry" in notice
    assert "not published on this site at the time" in notice
    assert "2026-08-30" in notice


def test_research_paper_provenance_also_flagged(db_session):
    art = Article(slug="paper", title="From the paper",
                  observed_at=dt.datetime(2026, 8, 30), published_at=utcnow(),
                  provenance=Provenance.RESEARCH_PAPER,
                  status=Status.PUBLISHED, visibility=Visibility.PUBLIC)
    assert "exploratory research paper" in provenance_notice(art)


def test_genuinely_prospective_posts_carry_no_reconstruction_notice(db_session):
    art = Article(slug="live", title="Written today about today",
                  observed_at=utcnow(), published_at=utcnow(),
                  provenance=Provenance.EDITOR,
                  status=Status.PUBLISHED, visibility=Visibility.PUBLIC)
    assert provenance_notice(art) is None


def test_automated_research_is_not_treated_as_reconstruction(db_session):
    art = Article(slug="auto", title="Job-generated", published_at=utcnow(),
                  provenance=Provenance.AUTOMATED_RESEARCH,
                  status=Status.PUBLISHED, visibility=Visibility.PUBLIC)
    assert provenance_notice(art) is None


def test_retrospective_provenances_are_exactly_these_two():
    assert set(Provenance.RETROSPECTIVE) == {
        Provenance.RESEARCH_PAPER, Provenance.RECONSTRUCTED_ARCHIVE,
    }


def test_seeded_archive_is_draft_and_reconstructed(db_session, ohlc_df):
    """The seed import must never publish itself."""
    from btcmoon.research.protocols import seed_protocols
    from btcmoon.seeds.archive import seed_archive

    seed_protocols(db_session)
    result = seed_archive(db_session, price=ohlc_df)
    assert result["observations"] > 0

    for obs in db_session.query(Observation).all():
        assert obs.status == Status.DRAFT
        assert obs.visibility == Visibility.PRIVATE
        assert obs.published_at is None
        assert obs.provenance == Provenance.RECONSTRUCTED_ARCHIVE
        # The observation date is historical; the import date is now.
        assert obs.observed_at < obs.imported_at
