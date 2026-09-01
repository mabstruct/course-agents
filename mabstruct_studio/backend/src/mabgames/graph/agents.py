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

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch

from mabgames.config import get_settings
from mabgames.graph.models import GameDesignBrief, GameIdeaList
from mabgames.graph.prompts import (
    DESIGN_SYSTEM_PROMPT,
    IDEATION_SYSTEM_PROMPT,
)

# Swap these lines to pick the model under test.
# OpenAI reasoning models need reasoning_effort="none" when tools are bound.
IDEATION_MODEL_ID = "gpt-5.6-sol"
DESIGN_MODEL_ID = "gpt-5.6-terra"

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
