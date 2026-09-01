"""The HTTP contract for the slice."""

import uuid


def _start(client, title="The Big Swallow"):
    response = client.post("/api/runs", json={"game_title": title})
    assert response.status_code == 201, response.text
    return response.json()


def test_starting_a_run_returns_the_pending_choice(client):
    body = _start(client)

    assert body["status"] == "awaiting_selection"
    assert body["awaiting"]["kind"] == "select_idea"
    assert body["awaiting"]["game_title"] == "The Big Swallow"
    assert len(body["awaiting"]["ideas"]) == 5
    assert body["designs"] == []


def test_ideas_are_browsable_by_title_with_status(client):
    run = _start(client)

    ideas = client.get(f"/api/titles/{run['title_id']}/ideas").json()
    assert len(ideas) == 5
    assert {i["status"] for i in ideas} == {"ideated"}

    titles = client.get("/api/titles").json()
    assert [t["title"] for t in titles] == ["The Big Swallow"]


def test_selecting_an_idea_produces_a_design(client):
    run = _start(client)
    chosen = run["awaiting"]["ideas"][2]["idea_id"]

    body = client.post(f"/api/runs/{run['run_id']}/select", json={"idea_id": chosen}).json()

    assert body["status"] == "completed"
    assert body["awaiting"] is None
    assert len(body["designs"]) == 1
    assert body["designs"][0]["idea_id"] == chosen
    assert body["designs"][0]["brief"]["game_sub_title"] == "Idea 2"

    ideas = client.get(f"/api/titles/{run['title_id']}/ideas").json()
    statuses = {i["idea_id"]: i["status"] for i in ideas}
    assert statuses[chosen] == "designed"


def test_a_run_can_be_picked_up_later_by_id(client):
    """R2 — the human comes back and asks what this run is waiting on."""
    run = _start(client)

    body = client.get(f"/api/runs/{run['run_id']}").json()
    assert body["status"] == "awaiting_selection"
    assert len(body["awaiting"]["ideas"]) == 5


def test_runs_awaiting_a_human_are_listable(client):
    _start(client)
    _start(client, "Another Title")

    awaiting = client.get("/api/runs", params={"run_status": "awaiting_selection"}).json()
    assert len(awaiting) == 2
    assert len(client.get("/api/runs").json()) == 2


def test_selecting_an_idea_this_run_never_offered_is_refused(client):
    run = _start(client)

    response = client.post(
        f"/api/runs/{run['run_id']}/select", json={"idea_id": str(uuid.uuid4())}
    )
    assert response.status_code == 400

    # Still selectable — the paused thread was never advanced.
    still = client.get(f"/api/runs/{run['run_id']}").json()
    assert still["status"] == "awaiting_selection"
    ok = client.post(
        f"/api/runs/{run['run_id']}/select",
        json={"idea_id": run["awaiting"]["ideas"][0]["idea_id"]},
    )
    assert ok.status_code == 200


def test_selecting_twice_is_a_conflict(client):
    run = _start(client)
    chosen = run["awaiting"]["ideas"][0]["idea_id"]
    client.post(f"/api/runs/{run['run_id']}/select", json={"idea_id": chosen})

    again = client.post(f"/api/runs/{run['run_id']}/select", json={"idea_id": chosen})
    assert again.status_code == 409


def test_unknown_run_is_a_404(client):
    assert client.get(f"/api/runs/{uuid.uuid4()}").status_code == 404
    assert (
        client.post(f"/api/runs/{uuid.uuid4()}/select", json={"idea_id": str(uuid.uuid4())}).status_code
        == 404
    )
