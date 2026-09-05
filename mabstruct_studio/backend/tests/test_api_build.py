"""The build gate over HTTP, including the background hand-off."""

import uuid

from fakes import BROKEN_GAME_HTML


def _to_the_gate(client, title="The Big Swallow"):
    run = client.post("/api/runs", json={"game_title": title}).json()
    chosen = run["awaiting"]["ideas"][2]["idea_id"]
    at_gate = client.post(f"/api/runs/{run['run_id']}/select", json={"idea_id": chosen}).json()
    return at_gate


def test_the_gate_returns_the_brief_to_read(client):
    at_gate = _to_the_gate(client)

    assert at_gate["status"] == "awaiting_build_approval"
    assert at_gate["awaiting"]["kind"] == "approve_build"
    brief = at_gate["awaiting"]["brief"]
    assert brief["game_sub_title"] == "Idea 2"
    assert brief["game_goal"] == "swallow everything"


def test_approving_returns_202_and_the_build_completes(client):
    """202 because the real runner is a thread; tests run it inline."""
    at_gate = _to_the_gate(client)
    run_id = at_gate["run_id"]

    response = client.post(f"/api/runs/{run_id}/build", json={"approved": True})
    assert response.status_code == 202

    done = client.get(f"/api/runs/{run_id}").json()
    assert done["status"] == "completed"
    assert len(done["builds"]) == 1
    assert done["builds"][0]["tier0_pass"] is True
    assert done["deploys"][0]["site_url"] == "https://hazy-hazel-6pws.here.now"


def test_rejecting_is_immediate_and_builds_nothing(client):
    at_gate = _to_the_gate(client)
    run_id = at_gate["run_id"]

    response = client.post(f"/api/runs/{run_id}/build", json={"approved": False})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"

    after = client.get(f"/api/runs/{run_id}").json()
    assert after["builds"] == [] and after["deploys"] == []


def test_a_build_is_fetchable_by_id(client):
    at_gate = _to_the_gate(client)
    run_id = at_gate["run_id"]
    client.post(f"/api/runs/{run_id}/build", json={"approved": True})

    build_id = client.get(f"/api/runs/{run_id}").json()["builds"][0]["id"]
    build = client.get(f"/api/builds/{build_id}").json()

    assert build["tier0_pass"] is True
    assert build_id in build["html_path"], "the build owns its directory"
    assert client.get(f"/api/builds/{uuid.uuid4()}").status_code == 404


def test_approving_before_the_gate_is_a_conflict(client):
    """A run still awaiting an idea choice cannot be built."""
    run = client.post("/api/runs", json={"game_title": "The Big Swallow"}).json()

    response = client.post(f"/api/runs/{run['run_id']}/build", json={"approved": True})
    assert response.status_code == 409


def test_approving_twice_is_a_conflict(client):
    at_gate = _to_the_gate(client)
    run_id = at_gate["run_id"]
    client.post(f"/api/runs/{run_id}/build", json={"approved": True})

    again = client.post(f"/api/runs/{run_id}/build", json={"approved": True})
    assert again.status_code == 409


def test_a_failing_build_still_completes_the_run_with_a_recorded_failure(client, agents):
    """Tier-0 failure is data, not an exception — the run finishes, unhappily."""
    agents.develop.html = BROKEN_GAME_HTML
    at_gate = _to_the_gate(client)
    run_id = at_gate["run_id"]

    assert client.post(f"/api/runs/{run_id}/build", json={"approved": True}).status_code == 202

    done = client.get(f"/api/runs/{run_id}").json()
    assert done["status"] == "completed"
    assert done["builds"][0]["tier0_pass"] is False
    assert done["deploys"][0]["deployed"] is False
    assert done["deploys"][0]["slug"] == ""


def test_ideas_reach_deployed_status_through_the_api(client):
    """R3 end to end: ideated -> designed -> deployed, all derived."""
    at_gate = _to_the_gate(client)
    run_id, title_id = at_gate["run_id"], at_gate["title_id"]

    ideas = client.get(f"/api/titles/{title_id}/ideas").json()
    assert sorted(i["status"] for i in ideas) == ["designed"] + ["ideated"] * 4

    client.post(f"/api/runs/{run_id}/build", json={"approved": True})
    ideas = client.get(f"/api/titles/{title_id}/ideas").json()
    assert sorted(i["status"] for i in ideas) == ["deployed"] + ["ideated"] * 4
