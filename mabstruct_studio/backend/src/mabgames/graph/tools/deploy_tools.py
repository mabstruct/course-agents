"""Per-build here.now deployment tools.

**The registry, not the agent's summary, is the source of truth for what went
live.** An agent can describe a deploy it never made; only `publish_game_site`
writes this dict. That guarantee is ported from the notebook unchanged.

What did change: the notebook wrote it to `herenow.json` *inside the build
folder*, so copying a build copied its slug — which is how three builds ended up
overwriting one here.now site. AD5/Q4 moves slug ownership into the domain DB, so
the registry is now an in-memory dict handed back to the node, and the API writes
`deploys.slug`. Same anti-hallucination property, no filesystem identity to
duplicate.
"""

import time
from pathlib import Path

import requests
from langchain_core.tools import tool

from mabgames.graph.paths import build_html_path
from mabgames.graph.tools.herenow import HereNowClient
from mabgames.graph.validation import run_static_validation

# A build that failed Tier-0 is broken JavaScript. Publishing it only wastes a
# playtester's time, so the gate is on by default. It is deterministic — never
# the agent's call.
DEPLOY_REQUIRE_TIER0 = True

STUDIO_NAME = "MABSTRUCT GAMESTUDIO"


def make_deploy_tools(
    builds_dir: Path,
    game_title: str,
    build_id: str,
    sub_title: str = "",
    client: HereNowClient | None = None,
    notify_tool=None,
) -> tuple[list, dict]:
    """Returns `(tools, registry)`. The node reads `registry`, never the summary."""
    herenow = client or HereNowClient()
    registry: dict = {}

    @tool
    def publish_game_site() -> str:
        """Publish this build's index.html to here.now and return the live URL.

        Every build publishes to its own site, so nothing is ever overwritten.
        Call verify_deployed_site afterwards.
        """
        html_path = build_html_path(builds_dir, game_title, build_id)
        if not html_path.exists():
            return f"Publish rejected: no built game at {html_path}."

        validation = run_static_validation(html_path)
        if DEPLOY_REQUIRE_TIER0 and not validation["pass"]:
            return "Publish rejected: Tier-0 validation failed — " + "; ".join(validation["issues"])

        try:
            result = herenow.publish(
                html_path,
                display_name=f"{game_title} — {STUDIO_NAME}",
                display_description=sub_title,
                slug=registry.get("slug", ""),
            )
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            detail = exc.response.text[:400] if exc.response is not None else str(exc)
            return f"Publish failed: HTTP {status}: {detail}"
        except Exception as exc:
            return f"Publish failed: {type(exc).__name__}: {exc}"

        registry.update(
            {
                "slug": result["slug"],
                "site_url": result["site_url"],
                "version_id": result["version_id"],
                "anonymous": result["anonymous"],
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )

        lines = [
            f"Published {html_path.name} ({len(html_path.read_bytes())} bytes)",
            f"Live URL: {result['site_url']}",
            f"Slug: {result['slug']} ({'updated in place' if result['updated_existing'] else 'newly created'})",
        ]
        if result["anonymous"]:
            lines.append("Temporary site: expires in 24 hours (no API key found).")
            if result["claim_url"]:
                lines.append(f"Claim URL (shown once): {result['claim_url']}")
        else:
            lines.append("Permanent site: saved to the studio account.")
        if result["unchanged"]:
            lines.append("Content identical to the live version — no new version created.")
        lines.append("Access: public link, unlisted — share the URL only with the playtest circle.")
        return "\n".join(lines)

    @tool
    def verify_deployed_site() -> str:
        """Fetch the deployed URL and confirm here.now is really serving this game."""
        site_url = registry.get("site_url")
        if not site_url:
            return "Verify rejected: nothing published yet — call publish_game_site first."

        try:
            response = herenow.fetch(site_url)
        except Exception as exc:
            return f"Verify FAILED: {type(exc).__name__}: {exc}"

        if response.status_code != 200:
            return f"Verify FAILED: {site_url} returned HTTP {response.status_code}"

        body = response.text.lower()
        missing = [m for m in ("<!doctype html", "<canvas", "<script") if m not in body]
        if missing:
            return (
                f"Verify FAILED: {site_url} served HTTP 200 but is missing {', '.join(missing)} "
                f"({len(response.text)} bytes) — that is probably not the game."
            )

        return f"Verify PASS: {site_url} serving {len(response.text)} bytes of game HTML."

    tools = [publish_game_site, verify_deployed_site]
    if notify_tool is not None:
        tools.append(notify_tool)
    return tools, registry
