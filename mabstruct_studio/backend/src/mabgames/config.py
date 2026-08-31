"""Environment, keys and paths.

AD3 requires the API to stay mountable — runnable standalone *or* mounted into a
LangGraph server via `langgraph.json`'s `http.app`. That means no work at import
time and nothing here assuming it owns the process: settings are resolved lazily
through `get_settings()` and injected as a dependency.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py -> mabgames -> src -> backend -> mabstruct_studio -> repo root
BACKEND_DIR = Path(__file__).resolve().parents[2]
STUDIO_DIR = BACKEND_DIR.parent
REPO_ROOT = STUDIO_DIR.parent


class Settings(BaseSettings):
    """Read from the parent repo's `.env`, overridable by real env vars."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # AD1 — the durable asset. Unlike the notebook's memory.db, this is not
    # disposable. Postgres later is a URL change plus a migration.
    database_url: str = Field(default=f"sqlite:///{BACKEND_DIR / 'mabgames.db'}")
    sql_echo: bool = False

    # AD1 — the checkpointer, which *is* disposable. Separate file, separate job:
    # it persists a thread's state so R2's interrupt can be resumed days later.
    checkpoint_path: Path = BACKEND_DIR / "checkpoints.db"

    # Builds are keyed by build id, not idea id (Q4/AD5: the build owns the URL),
    # so app output cannot collide with the notebook's <title>/<idea_id>/ folders.
    # No herenow.json is written here — `deploys.slug` is the only slug of record.
    builds_dir: Path = STUDIO_DIR / "dev-output"

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    tavily_api_key: str | None = None

    # here.now's key has two spellings in the wild: the parent repo's .env uses
    # HERE_NOW_API_KEY, the here.now skill and CrewAI tool use HERENOW_API_KEY.
    here_now_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("HERE_NOW_API_KEY", "HERENOW_API_KEY"),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
