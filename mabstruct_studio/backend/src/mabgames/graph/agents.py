"""Models, tools and agents — the notebook's model cell, made lazy.

**This is the one deliberate deviation from the notebook, and it is forced.**
The notebook builds `ChatOpenAI(...)`, `TavilySearch(...)` and both agents at
module scope. `ChatOpenAI` *raises* at construction when no key is in the
environment, so a literal port would make `import mabgames.graph` fail without
keys — breaking AD3's rule that nothing works at import time, and making every
test need a paid key. Factories defer construction instead.

Note `Settings` reads the parent repo's `.env` via pydantic-settings, which does
**not** populate `os.environ`. The key has to be passed explicitly; the provider
SDKs cannot pick it up on their own.

The notebook's "swap one variable to change model" convention survives: the model
ids are still module-level constants, only the client construction moved.
"""

from functools import lru_cache

import anthropic
import httpx
import openai
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware
from langchain_anthropic import ChatAnthropic
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch

from mabgames.config import get_settings
from mabgames.graph.models import GameDesignBrief, GameIdeaList
from mabgames.graph.prompts import (
    DESIGN_SYSTEM_PROMPT,
    DEPLOYMENT_SYSTEM_PROMPT,
    DEVELOP_SYSTEM_PROMPT,
    IDEATION_SYSTEM_PROMPT,
)

# Swap these lines to pick the model under test.
# OpenAI reasoning models need reasoning_effort="none" when tools are bound.
IDEATION_MODEL_ID = "gpt-5.6-sol"
DESIGN_MODEL_ID = "gpt-5.6-terra"
# Deployment is mechanical tool-calling (publish -> verify -> notify), not authoring.
DEPLOY_MODEL_ID = "gpt-5.6-luna"

SEARCH_MAX_RESULTS = 5


@lru_cache
def search_tool() -> TavilySearch:
    return TavilySearch(
        max_results=SEARCH_MAX_RESULTS,
        tavily_api_key=get_settings().tavily_api_key,
    )


@lru_cache
def ideation_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=IDEATION_MODEL_ID,
        reasoning_effort="none",
        api_key=get_settings().openai_api_key,
    )


@lru_cache
def design_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=DESIGN_MODEL_ID,
        reasoning_effort="none",
        api_key=get_settings().openai_api_key,
    )


def make_ideation_agent():
    return create_agent(
        model=ideation_model(),
        system_prompt=IDEATION_SYSTEM_PROMPT,
        tools=[search_tool()],
        response_format=GameIdeaList,
    )


def make_design_agent():
    return create_agent(
        model=design_model(),
        system_prompt=DESIGN_SYSTEM_PROMPT,
        tools=[search_tool()],
        response_format=GameDesignBrief,
    )


# --------------------------------------------------------------------------- #
# DEVELOP — the delicate one. Every constant here was won the hard way.
# --------------------------------------------------------------------------- #

# Develop needs many long tool steps (start + js chunks + end + verify).
DEVELOP_RECURSION_LIMIT = 200


@lru_cache
def develop_model() -> ChatAnthropic:
    """Opus 5 for develop.

    Do NOT switch to the string form "anthropic:claude-opus-5" — it resolves to
    max_tokens=4096, which truncates tool arguments mid-JSON. `streaming=True` is
    required at large max_tokens or the HTTP request times out.
    `default_request_timeout` is a per-read idle timeout: fail fast on a stalled
    stream rather than hang for the whole build.
    """
    return ChatAnthropic(
        model="claude-opus-5",
        max_tokens=32000,
        streaming=True,
        effort="medium",              # trims thinking spend for mechanical code emission
        default_request_timeout=300,
        max_retries=2,
        api_key=get_settings().anthropic_api_key,
    )


@lru_cache
def deploy_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=DEPLOY_MODEL_ID,
        reasoning_effort="none",
        api_key=get_settings().openai_api_key,
    )


# Transport faults surface while the SSE body is being consumed, which is outside
# the SDK retry loop (it covers sending the request and receiving headers only).
# Retrying here re-issues one model call instead of losing the whole build.
DEVELOP_TRANSPORT_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.ReadTimeout,
    anthropic.APIConnectionError,  # APITimeoutError subclasses this
    anthropic.InternalServerError,
    anthropic.RateLimitError,
    openai.APIConnectionError,
    openai.InternalServerError,
    openai.RateLimitError,
)


def make_develop_middleware(model) -> list:
    """Built per model, not once at import.

    The notebook made this a module-level list mutated in place by an `isinstance`
    check against an already-constructed model — which cannot survive lazy model
    construction. The rule it encodes still holds: the Anthropic caching
    middleware is added **only** for ChatAnthropic. On other providers it warns
    every turn and caches nothing.
    """
    middleware = [
        ModelRetryMiddleware(
            max_retries=3,
            retry_on=DEVELOP_TRANSPORT_ERRORS,
            on_failure="error",  # raise, so develop_node can still salvage the file on disk
            initial_delay=2.0,
        ),
    ]
    if isinstance(model, ChatAnthropic):
        middleware.append(AnthropicPromptCachingMiddleware())
    return middleware


def make_develop_agent(tools: list):
    """Built per build — its tools are a per-build closure, so it cannot be cached."""
    model = develop_model()
    return create_agent(
        model=model,
        system_prompt=DEVELOP_SYSTEM_PROMPT,
        tools=tools,
        middleware=make_develop_middleware(model),
    )


def make_deploy_agent(tools: list):
    return create_agent(
        model=deploy_model(),
        system_prompt=DEPLOYMENT_SYSTEM_PROMPT,
        tools=tools,
    )
