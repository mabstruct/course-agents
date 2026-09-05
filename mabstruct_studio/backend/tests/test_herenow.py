"""The three-step publish, against a stubbed transport — no network."""

import pytest
from fakes import CREATED, FINALIZED, FakeResponse, FakeSession

from mabgames.graph.tools.herenow import HereNowClient


@pytest.fixture(name="html")
def html_fixture(tmp_path):
    path = tmp_path / "index.html"
    path.write_text("<!DOCTYPE html><html><body><script>1;</script></body></html>")
    return path


def test_create_upload_finalize_in_order(html):
    session = FakeSession([FakeResponse(payload=CREATED), FakeResponse(), FakeResponse(payload=FINALIZED)])
    result = HereNowClient(api_key="k", session=session).publish(html, display_name="Game")

    assert [m for m, _ in session.calls] == ["POST", "PUT", "POST"]
    assert session.calls[0][1].endswith("/api/v1/publish")
    assert session.calls[1][1] == "https://upload.example/put"
    assert session.calls[2][1].endswith("/finalize")
    assert result["slug"] == "hazy-hazel-6pws"
    assert result["site_url"] == "https://hazy-hazel-6pws.here.now"
    assert result["updated_existing"] is False


def test_finalize_waits_out_a_409_then_succeeds(html, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("mabgames.graph.tools.herenow.time.sleep", slept.append)

    session = FakeSession([
        FakeResponse(payload=CREATED),
        FakeResponse(),
        FakeResponse(409, text="finalize_in_flight", headers={"Retry-After": "7"}),
        FakeResponse(payload=FINALIZED),
    ])
    result = HereNowClient(api_key="k", session=session).publish(html)

    assert slept == [7.0], "Retry-After must be honoured, not a fixed delay"
    assert result["slug"] == "hazy-hazel-6pws"


def test_a_404_on_update_falls_through_to_create(html):
    """A recorded site that no longer exists means create a new one, not fail."""
    session = FakeSession([
        FakeResponse(404),
        FakeResponse(payload=CREATED),
        FakeResponse(),
        FakeResponse(payload=FINALIZED),
    ])
    result = HereNowClient(api_key="k", session=session).publish(html, slug="gone-4ever")

    assert [m for m, _ in session.calls] == ["PUT", "POST", "PUT", "POST"]
    assert result["updated_existing"] is False, "a stale slug reports 'newly created'"


def test_upload_loop_is_driven_by_uploads_not_the_manifest(html):
    """Identical bytes deduplicate server-side: no upload targets, no PUTs."""
    deduped = {**CREATED, "upload": {**CREATED["upload"], "uploads": []}}
    session = FakeSession([FakeResponse(payload=deduped), FakeResponse(payload={**FINALIZED, "unchanged": True})])

    result = HereNowClient(api_key="k", session=session).publish(html)

    assert [m for m, _ in session.calls] == ["POST", "POST"], "no upload PUT"
    assert result["unchanged"] is True


def test_no_key_means_an_anonymous_site(html):
    session = FakeSession([FakeResponse(payload=CREATED), FakeResponse(), FakeResponse(payload=FINALIZED)])
    client = HereNowClient(api_key=None, session=session)
    assert client.anonymous is True
    assert client.publish(html)["anonymous"] is True


def test_a_key_is_sent_as_a_bearer_token(html):
    client = HereNowClient(api_key="secret")
    assert client._headers()["Authorization"] == "Bearer secret"
    assert "Authorization" not in HereNowClient(api_key=None)._headers()
