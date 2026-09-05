"""Stand-ins for the phase agents, so tests run the real graph without an LLM.

The seam is *agent* injection, not graph faking. Tests exercise the real
topology, the real interrupt, the real checkpointer and the real dispatch table
— only the two `create_agent` results are swapped. A hand-built fake graph would
test a graph nobody ships, and recorded chunks would skip the interrupt/resume
mechanics, which is where all the risk in this slice lives.
"""

from mabgames.graph.models import GameDesignBrief, GameIdea, GameIdeaList


class FakeAgent:
    """Stands in for `create_agent(...)`. Records prompts so tests can assert on them."""

    def __init__(self, structured_response):
        self.response = structured_response
        self.calls: list[str] = []

    def invoke(self, payload):
        self.calls.append(payload["messages"][0].content)
        return {"structured_response": self.response}


def fake_ideas(count: int = 5) -> GameIdeaList:
    """Ideas with NO idea_id — the node must mint them, exactly as the LLM leaves them."""
    return GameIdeaList(
        ideas=[
            GameIdea(
                sub_title=f"Idea {n}",
                genre="arcade",
                style="neon vector",
                reason=f"reason {n}",
                description=f"description {n}",
                features=[f"feature {n}a", f"feature {n}b"],
            )
            for n in range(count)
        ]
    )


def fake_brief(sub_title: str = "Idea 2") -> GameDesignBrief:
    return GameDesignBrief(
        game_title="The Big Swallow",
        game_sub_title=sub_title,
        game_description="Swallow the sky before it swallows you.",
        game_genre="arcade",
        game_theme="cosmic",
        game_mood="surreal",
        game_style="neon vector",
        game_goal="swallow everything",
        game_objective="survive the escalation",
        game_rules="one button",
        game_controls="space",
        game_instructions="press space",
        game_mechanics="peristalsis timing",
        game_sound="low hum",
        game_art="hand-inked",
        hints_for_the_team="keep the verb single",
    )


GOOD_GAME_HTML = (
    "<!DOCTYPE html><html><head><title>g</title></head><body>"
    "<canvas id=c></canvas><script>const s={t:0};"
    "function update(dt,st){st.t+=dt;}function render(st){}"
    "requestAnimationFrame(function f(){update(0.016,s);render(s);});"
    "</script></body></html>"
)

BROKEN_GAME_HTML = (
    "<!DOCTYPE html><html><body><canvas></canvas>"
    "<script>const a=;</script></body></html>"
)


class FakeBuildAgent:
    """A develop agent that writes a file through the real tool protocol.

    It drives `write_game_html_part` exactly as the model is asked to — start,
    js, end — so the tool's rules, the disk write and Tier-0 all really run.
    """

    def __init__(self, html: str = GOOD_GAME_HTML, calls: list | None = None):
        self.html = html
        self.tools = []
        self.calls = calls if calls is not None else []

    def __call__(self, tools):
        self.tools = tools
        return self

    def invoke(self, payload, config=None):
        self.calls.append(payload["messages"][0].content)
        writer = next(t for t in self.tools if t.name == "write_game_html_part")
        head, _, tail = self.html.partition("<script>")
        body, _, close = tail.partition("</script>")
        writer.invoke({"content": head + "<script>", "part": "start"})
        writer.invoke({"content": body, "part": "js"})
        writer.invoke({"content": "</script></body></html>", "part": "end"})
        return {"messages": [_FakeMessage("built the game")]}


class FakeDeployAgent:
    """A deploy agent that calls the real publish tool against a stubbed client."""

    def __init__(self, publish: bool = True):
        self.publish = publish
        self.tools = []
        self.calls: list[str] = []

    def __call__(self, tools):
        self.tools = tools
        return self

    def invoke(self, payload, config=None):
        self.calls.append(payload["messages"][0].content)
        if self.publish:
            tool = next(t for t in self.tools if t.name == "publish_game_site")
            tool.invoke({})
        # An agent that claims a deploy it never made — the registry must win.
        return {"messages": [_FakeMessage("Deployed to https://liar.example")]}


class _FakeMessage:
    def __init__(self, text: str):
        self.content = text
        self.tool_calls = []


# --------------------------------------------------------------------------- #
# here.now transport doubles
# --------------------------------------------------------------------------- #

import json as _json


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or _json.dumps(self._payload)
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeSession:
    """Records every call so the publish sequence can be asserted in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def _next(self, method, url):
        self.calls.append((method, url))
        if not self.responses:
            raise AssertionError(f"unexpected {method} {url} — no stubbed response left")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def post(self, url, **kw):
        return self._next("POST", url)

    def put(self, url, **kw):
        return self._next("PUT", url)

    def get(self, url, **kw):
        return self._next("GET", url)


CREATED = {
    "slug": "hazy-hazel-6pws",
    "siteUrl": "https://hazy-hazel-6pws.here.now",
    "upload": {
        "versionId": "v1",
        "finalizeUrl": "https://here.now/api/v1/publish/hazy-hazel-6pws/finalize",
        "uploads": [{"url": "https://upload.example/put", "headers": {}}],
    },
}
FINALIZED = {"slug": "hazy-hazel-6pws", "siteUrl": "https://hazy-hazel-6pws.here.now"}


def publish_responses():
    """One successful create -> upload -> finalize."""
    return [FakeResponse(payload=CREATED), FakeResponse(), FakeResponse(payload=FINALIZED)]
