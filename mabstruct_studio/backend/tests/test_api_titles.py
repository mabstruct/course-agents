"""R7 over HTTP: the leaderboard and the production candidate for a title."""

import uuid

from mabgames.domain import repository as repo

IDEAS = [
    {
        "sub_title": "A Mouth The Size Of Weather",
        "genre": "arcade",
        "style": "neon vector",
        "reason": "one clean verb",
        "description": "Swallow the sky.",
        "features": ["one-button"],
    },
    {
        "sub_title": "Digestive Cosmology",
        "genre": "puzzle",
        "style": "hand-inked",
        "reason": "the joke survives",
        "description": "Route stars through a gut.",
        "features": ["node routing"],
    },
]

BRIEF = {"game_title": "The Big Swallow", "game_goal": "swallow everything"}


def _two_deployed_builds(session):
    """Two ideas, each built and live, written straight to the domain — no graph."""
    title = repo.get_or_create_title(session, "The Big Swallow")
    first, second = repo.record_ideas(session, title.id, IDEAS)
    older = repo.record_build(
        session, first.id, repo.record_design(session, first.id, BRIEF).id, tier0_pass=True
    )
    repo.record_deploy(session, older.id, slug="older", site_url="https://older.here.now", deployed=True)
    newer = repo.record_build(
        session, second.id, repo.record_design(session, second.id, BRIEF).id, tier0_pass=True
    )
    repo.record_deploy(session, newer.id, slug="newer", site_url="https://newer.here.now", deployed=True)
    return title, older, newer


def test_unrated_title_falls_back_to_the_newest_live_build(client, session):
    title, older, newer = _two_deployed_builds(session)

    board = client.get(f"/api/titles/{title.id}/leaderboard").json()
    assert [row["id"] for row in board] == [str(newer.id), str(older.id)]
    assert all(row["score"] is None and row["ratings"] == 0 for row in board)
    assert board[0]["site_url"] == "https://newer.here.now"

    candidate = client.get(f"/api/titles/{title.id}/candidate").json()
    assert candidate["id"] == str(newer.id)


def test_a_rating_reorders_the_board_and_moves_the_candidate(client, session):
    """R7/Q1 — the human 1-5 rating is the only ranking signal."""
    title, older, newer = _two_deployed_builds(session)
    repo.record_feedback(session, older.id, rating=5, comment="perfect")
    repo.record_feedback(session, older.id, rating=4)
    repo.record_feedback(session, newer.id, rating=2, comment="floaty")
    repo.record_feedback(session, newer.id, comment="no number, just a note")

    board = client.get(f"/api/titles/{title.id}/leaderboard").json()
    assert [(row["id"], row["score"], row["ratings"]) for row in board] == [
        (str(older.id), 4.5, 2),
        (str(newer.id), 2.0, 1),
    ]

    candidate = client.get(f"/api/titles/{title.id}/candidate").json()
    assert candidate["id"] == str(older.id)
    assert candidate["score"] == 4.5
    assert candidate["site_url"] == "https://older.here.now"


def test_a_title_with_no_live_build_has_no_candidate_yet(client, session):
    title = repo.get_or_create_title(session, "The Big Swallow")
    (idea,) = repo.record_ideas(session, title.id, IDEAS[:1])
    build = repo.record_build(
        session, idea.id, repo.record_design(session, idea.id, BRIEF).id, tier0_pass=False
    )
    repo.record_deploy(session, build.id, deployed=False)

    board = client.get(f"/api/titles/{title.id}/leaderboard").json()
    assert len(board) == 1 and board[0]["site_url"] is None, "a skipped deploy is listed but unplayable"
    assert client.get(f"/api/titles/{title.id}/candidate").status_code == 404


def test_unknown_titles_are_404(client):
    missing = uuid.uuid4()
    assert client.get(f"/api/titles/{missing}/leaderboard").status_code == 404
    assert client.get(f"/api/titles/{missing}/candidate").status_code == 404


def test_a_run_through_the_pipeline_shows_up_on_the_board(client):
    """The build the graph made is the fallback candidate the moment it is live."""
    run = client.post("/api/runs", json={"game_title": "The Big Swallow"}).json()
    chosen = run["awaiting"]["ideas"][2]["idea_id"]
    client.post(f"/api/runs/{run['run_id']}/select", json={"idea_id": chosen})
    client.post(f"/api/runs/{run['run_id']}/build", json={"approved": True})

    candidate = client.get(f"/api/titles/{run['title_id']}/candidate").json()
    assert candidate["idea_id"] == chosen
    assert candidate["tier0_pass"] is True
    assert candidate["site_url"] == "https://hazy-hazel-6pws.here.now"
