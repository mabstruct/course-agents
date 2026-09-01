"""The domain schema's two load-bearing behaviours: derived status and ranking."""

import pytest

from mabgames.domain import repository as repo
from mabgames.domain.models import IdeaStatus, RefurbEntry

IDEAS = [
    {
        "sub_title": "A Mouth The Size Of Weather",
        "genre": "arcade",
        "style": "neon vector",
        "reason": "one clean verb, endlessly escalating",
        "description": "Swallow the sky before it swallows you.",
        "features": ["one-button", "escalating scale", "no fail state"],
    },
    {
        "sub_title": "Digestive Cosmology",
        "genre": "puzzle",
        "style": "hand-inked",
        "reason": "the joke survives repetition",
        "description": "Route stars through a gut that has opinions.",
        "features": ["node routing", "peristalsis timing"],
    },
]

BRIEF = {"game_title": "The Big Swallow", "game_goal": "swallow everything"}


def test_ideas_persist_under_one_title(session):
    """R1 + R6 — every idea is stored, grouped by title, addressable later."""
    title = repo.get_or_create_title(session, "The Big Swallow")
    again = repo.get_or_create_title(session, "The Big Swallow")
    assert again.id == title.id, "R6's grouping key must not duplicate"

    ideas = repo.record_ideas(session, title.id, IDEAS)
    assert len(ideas) == 2, "rejected ideas are R7's comparison set — store them all"
    assert all(idea.id is not None for idea in ideas)
    assert ideas[0].features == ["one-button", "escalating scale", "no fail state"]


def test_status_is_derived_from_stage_rows(session):
    """R3 — status is the newest stage row, not a column."""
    title = repo.get_or_create_title(session, "The Big Swallow")
    idea, other = repo.record_ideas(session, title.id, IDEAS)

    assert repo.idea_status(session, idea) is IdeaStatus.IDEATED

    design = repo.record_design(session, idea.id, BRIEF)
    assert repo.idea_status(session, idea) is IdeaStatus.DESIGNED

    build = repo.record_build(
        session, idea.id, design.id, html_path="/tmp/index.html", tier0_pass=True
    )
    assert repo.idea_status(session, idea) is IdeaStatus.DEVELOPED

    repo.record_deploy(
        session, build.id, slug="hazy-hazel-6pws", site_url="https://x", deployed=True
    )
    assert repo.idea_status(session, idea) is IdeaStatus.DEPLOYED

    repo.reject_idea(session, other.id)
    assert repo.idea_status(session, other) is IdeaStatus.REJECTED


def test_failed_build_and_skipped_deploy(session):
    """A Tier-0 failure is recorded, not raised, and blocks the deploy."""
    title = repo.get_or_create_title(session, "The Big Swallow")
    (idea,) = repo.record_ideas(session, title.id, IDEAS[:1])
    design = repo.record_design(session, idea.id, BRIEF)
    build = repo.record_build(session, idea.id, design.id, tier0_pass=False)

    repo.record_deploy(session, build.id, deployed=False, summary="Tier-0 gate: skipped")
    assert repo.idea_status(session, idea) is IdeaStatus.FAILED


def test_a_later_failure_does_not_unship_a_deployed_idea(session):
    """An idea that reached `deployed` stays deployed when a refurb build fails."""
    title = repo.get_or_create_title(session, "The Big Swallow")
    (idea,) = repo.record_ideas(session, title.id, IDEAS[:1])
    design = repo.record_design(session, idea.id, BRIEF)

    shipped = repo.record_build(session, idea.id, design.id, tier0_pass=True)
    repo.record_deploy(session, shipped.id, slug="a", deployed=True)
    repo.record_build(
        session,
        idea.id,
        design.id,
        tier0_pass=False,
        refurb_of=shipped.id,
        refurb_entry=RefurbEntry.DEVELOP,
    )

    assert repo.idea_status(session, idea) is IdeaStatus.DEPLOYED


def test_refurb_lineage_is_answerable_per_build(session):
    """R4/Q3 — `refurb_of` + `refurb_entry` carry the chain."""
    title = repo.get_or_create_title(session, "The Big Swallow")
    (idea,) = repo.record_ideas(session, title.id, IDEAS[:1])
    design = repo.record_design(session, idea.id, BRIEF)

    first = repo.record_build(session, idea.id, design.id, tier0_pass=True)
    patched = repo.record_build(
        session,
        idea.id,
        design.id,
        tier0_pass=True,
        refurb_of=first.id,
        refurb_entry=RefurbEntry.DEVELOP,
    )

    lineage = repo.build_lineage(session, patched)
    assert [b.id for b in lineage] == [patched.id, first.id]
    assert patched.refurb_entry is RefurbEntry.DEVELOP


def test_candidate_falls_back_then_defers_to_rating(session):
    """R7/Q1 — rank on the human 1-5 rating; unrated titles fall back."""
    title = repo.get_or_create_title(session, "The Big Swallow")
    good, better = repo.record_ideas(session, title.id, IDEAS)

    good_design = repo.record_design(session, good.id, BRIEF)
    better_design = repo.record_design(session, better.id, BRIEF)

    older = repo.record_build(session, good.id, good_design.id, tier0_pass=True)
    repo.record_deploy(session, older.id, slug="older", deployed=True)
    newer = repo.record_build(session, better.id, better_design.id, tier0_pass=True)
    repo.record_deploy(session, newer.id, slug="newer", deployed=True)

    # No ratings anywhere: the newest Tier-0-passing deploy is the candidate.
    assert repo.production_candidate(session, title.id).id == newer.id

    # One rating flips it, however old the build is.
    repo.record_feedback(session, older.id, rating=5, comment="perfect")
    repo.record_feedback(session, newer.id, rating=2, comment="floaty")
    assert repo.production_candidate(session, title.id).id == older.id

    ranked = repo.leaderboard(session, title.id)
    assert [score for _, score in ranked] == [5.0, 2.0]

    cached = repo.recompute_candidate(session, title.id)
    assert cached.build_id == older.id


def test_a_tier0_failure_is_never_the_fallback_candidate(session):
    """Tier-0 gates deploys but never ranks — a failing build cannot be candidate."""
    title = repo.get_or_create_title(session, "The Big Swallow")
    (idea,) = repo.record_ideas(session, title.id, IDEAS[:1])
    design = repo.record_design(session, idea.id, BRIEF)

    build = repo.record_build(session, idea.id, design.id, tier0_pass=False)
    repo.record_deploy(session, build.id, deployed=False)

    assert repo.production_candidate(session, title.id) is None
    assert repo.recompute_candidate(session, title.id) is None


def test_unrated_builds_rank_below_rated_ones(session):
    title = repo.get_or_create_title(session, "The Big Swallow")
    (idea,) = repo.record_ideas(session, title.id, IDEAS[:1])
    design = repo.record_design(session, idea.id, BRIEF)

    rated = repo.record_build(session, idea.id, design.id, tier0_pass=True)
    unrated = repo.record_build(session, idea.id, design.id, tier0_pass=True)
    repo.record_feedback(session, rated.id, rating=1, comment="barely works")

    ranked = repo.leaderboard(session, title.id)
    assert [b.id for b, _ in ranked] == [rated.id, unrated.id]
    assert ranked[1][1] is None


def test_rating_outside_1_to_5_is_refused(session):
    title = repo.get_or_create_title(session, "The Big Swallow")
    (idea,) = repo.record_ideas(session, title.id, IDEAS[:1])
    design = repo.record_design(session, idea.id, BRIEF)
    build = repo.record_build(session, idea.id, design.id, tier0_pass=True)

    with pytest.raises(ValueError):
        repo.record_feedback(session, build.id, rating=6)

    # A comment with no rating is legitimate: it is an R4 refurb request.
    note = repo.record_feedback(session, build.id, comment="the controls feel floaty")
    assert note.rating is None


def test_record_ideas_honours_a_supplied_id(session):
    """The pipeline assigns idea_id in graph state; the row must carry the same one."""
    import uuid

    title = repo.get_or_create_title(session, "The Big Swallow")
    assigned = str(uuid.uuid4())

    (idea,) = repo.record_ideas(session, title.id, [{**IDEAS[0], "idea_id": assigned}])

    assert str(idea.id) == assigned


def test_record_ideas_still_mints_an_id_when_none_is_given(session):
    title = repo.get_or_create_title(session, "The Big Swallow")
    (idea,) = repo.record_ideas(session, title.id, IDEAS[:1])
    assert idea.id is not None
