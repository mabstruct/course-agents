# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## The goal

**Build MABSTRUCT Studio: the application defined in [`REQUIREMENTS.md`](./REQUIREMENTS.md).**

**This is a learning project.** It exists to learn the multi-agent pipeline, not to operate a
game studio. Where a decision offers a simple option and a thorough one, take the simple one
and name the rough edge instead of engineering it away; deferring a requirement outright is a
legitimate answer. Several rough edges below are deliberate — don't file them as bugs.

That file is the authoritative spec for this project — read it before any design or
implementation work here. In short: keep the LangGraph pipeline that the notebook proved,
and wrap it in the three things the notebook cannot do —

- **persistence**, so ideas, designs, builds and deployments outlive the kernel (R1, R3, R6);
- **a human decision point**, so a person picks which idea proceeds to DESIGN and the run
  resumes from that choice days later (R2);
- **a feedback loop**, so deployed games can be rated, refurbished, ranked, and so lessons
  compound into later games (R4, R5, R7).

**Status: the whole pipeline runs in the app** — `IDEATION → SELECT → DESIGN → APPROVE →
DEVELOP → DEPLOY`, in one graph, persisted, with two human decision points. A title becomes a
playable game at a live here.now URL. Proven end to end. R1, R2, R3, R6 delivered. **R7's
read side is exposed**: `GET /api/titles/{id}/leaderboard` and `.../candidate` compute
live from `repository.leaderboard` / `production_candidate`; the `candidates` cache table
stays unpopulated until the start page needs it. **R4 (feedback/refurb) is the next slice** —
`repository.record_feedback` is tested but has no route, so nothing can rate a build over
HTTP yet, and `builds.refurb_of` is still unused. Everything below *The reference
implementation* describes the notebook — the thing being ported *from*, not the target.

### Where application code goes

Settled in AD6/AD7 (ACCEPTED). Put new app code here, not in the notebook:

```
mabstruct_studio/
├── mabstruct_studio.ipynb          # spike environment — stays at root
├── mabstruct_experimenting.ipynb
├── dev-output/                     # gitignored notebook output
├── backend/                        # EXISTS
│   ├── pyproject.toml              # uv workspace member; package name `mabgames`
│   ├── src/mabgames/
│   │   ├── domain/                 # AD1 — models.py, db.py, repository.py  [built]
│   │   ├── graph/                  # AD2 — all four phases + two gates      [built]
│   │   │   └── tools/              #       html_writer, herenow, notify
│   │   ├── api/                    # AD3 — routes + lifecycle.py (the seam) [built]
│   │   └── config.py               # env, keys, paths                       [built]
│   └── tests/                      # pytest — 68 tests, no LLM, no network
└── frontend/                       # AD4 — TS + Vite                        [not started]
```

- Imports read `from mabgames.domain import Idea` — the directory is `backend/`, the package
  is `mabgames`. Don't put the layer name in the package.
- **`domain/` is a sibling of `graph/`, never nested inside it.** AD1 turns on the domain
  schema outliving the pipeline; nesting would undo that.
- **Tests live with their runner.** pytest under `backend/tests/`, Vitest with the frontend.
  There is no top-level `tests/`; `e2e/` appears only when a real cross-stack test exists.
- **Backend dependencies:** `uv add <pkg>` from `backend/`. The parent repo stays the place
  to add anything the *notebooks* need. One shared `.venv` at the repo root still serves both.
  The root `pyproject.toml` carries `[tool.uv.workspace]` plus a dev-group dependency on
  `mabgames` (`tool.uv.sources` → `workspace = true`), so a plain `uv sync` at the repo root
  installs the backend editable into the shared venv — and the spike notebooks can
  `import mabgames` when porting. Declare what the backend imports in `backend/pyproject.toml`
  even when the parent already has it; nothing should ride in on the course repo's list.
- **Run the tests:** `cd backend && ../../.venv/bin/python -m pytest`. No test calls an LLM —
  `build_studio_graph` takes its agents as arguments, so tests use the real graph, interrupt
  and checkpointer with fake agents. There is still no linter, and no frontend yet.
- **Run the app:** `cd backend && ../../.venv/bin/python -m uvicorn mabgames.api.app:app`.
  It writes `backend/mabgames.db` (durable) and `backend/checkpoints.db` (disposable), both
  gitignored.

### Working rules

- `REQUIREMENTS.md` is a living document, and **AD1–AD7 are now ACCEPTED with Q1–Q5
  resolved** — nothing blocks implementation. Don't re-litigate a settled decision; the
  rationale and the rejected alternatives are recorded there. If one genuinely needs
  reopening, change that file in the same commit as the code that acts on it.
- **The decisions that shape code**, so a fresh session doesn't re-derive them:

  | Decision | Consequence in code |
  | --- | --- |
  | Per-stage records, status derived (R3) | No `status` column. Status = newest stage row for an idea. |
  | Refurb at DEVELOP first, DESIGN later (R4) | `builds.refurb_of` + `refurb_entry` (`design`\|`develop`). |
  | Learnings deferred (R5) | Nothing appended to phase prompts. The Store layer stays unbuilt. |
  | Rank on human rating 1–5 only (R7/Q1) | Tier-0 is recorded and gates deploys, but never ranks. Unrated title → newest Tier-0-passing deploy is the candidate. |
  | Build owns the URL (Q4/AD5) | One here.now site per build; nothing overwrites. Slug lives in `deploys`, never in a file under `dev-output/`. here.now slugs are random — never write code that requests a hostname. |
  | Self-hosted FastAPI, **kept mountable** (Q5/AD3) | `api/` is real, but must run standalone *or* mounted into the LangGraph server via `langgraph.json`'s `http.app`. No work in `main`; DB session and startup as dependencies + lifespan. That keeps Q5 reversible. |
  | SQLite + SQLModel (AD1) | Same Pydantic idiom as the graph's structured outputs. Postgres = URL change + migration. |

- **Three things to carry forward, not forget:** keep the domain API mountable (above), stand
  up the owned-subdomain start page once the app runs, and revisit R5 once there is history.
- **The notebook is the spike environment. Port from it; do not fork it.** New phases get
  prototyped in a notebook and moved into the app — the notebook stays the place to
  experiment.
- **The API persists; graph nodes never do.** Nodes are pure state transformers that must not
  import `mabgames.domain` (enforced by `tests/test_layering.py`, by AST). `api/lifecycle.py`
  consumes `stream_mode="updates"` and maps node name → repository call via `PERSISTERS`.
  Adding a phase means adding an entry there or to `NO_PERSIST` — `test_every_graph_node_is_
  accounted_for` fails otherwise. Commit per node, never one transaction over the run: that
  makes persistence granularity match checkpoint granularity.
- **Everything expensive is injected, and that is not stylistic — it is what keeps tests off
  the network and off the model API.** `build_studio_graph` takes `ideation_agent`,
  `design_agent`, `develop_agent_factory`, `deploy_agent_factory`, `dev_tools_factory`,
  `deploy_tools_factory` and `builds_dir`. DEVELOP and DEPLOY take agent *factories* because
  their tools are closures over one build. **Never bind a real factory as a default argument**
  — the node captures it when the graph is built, so a later monkeypatch silently does nothing
  and the test publishes to here.now for real. That happened once; injection is the fix.
- **Three things that bite, learned the hard way:**
  - Pydantic objects in graph state must be added to `graph.studio.STATE_TYPES`, or the
    checkpoint serializer warns and will eventually refuse. That allowlist pins module paths —
    moving `graph/models.py` orphans every paused run.
  - `ChatOpenAI` raises at construction with no key and pydantic-settings does not populate
    `os.environ`, so models are built by factories in `graph/agents.py` that pass `api_key=`.
    Never construct a model at module scope. The same applies to `DEVELOP_MIDDLEWARE`, which
    is now `make_develop_middleware(model)`.
  - **`create_db_and_tables()` has run out of road.** It creates missing tables but never
    alters existing ones. Adding `awaiting_build_approval` widened a `VARCHAR(18)` column that
    SQLite happily ignored and Postgres would have rejected. The next schema change needs a
    real migration.
- Keep the expensive knowledge intact when porting. The develop phase's model config,
  streaming behaviour, retry middleware, chunked tool protocol and Tier-0 validation were
  all won the hard way (see *The develop phase* below).

## The reference implementation

`mabstruct_studio` is an experimental **multi-agent game studio** built on LangGraph: a
pipeline that turns a single game title into a playable single-file HTML5 browser game,
published to a live URL.

```
IDEATION --> DESIGN --> DEVELOP --> DEPLOY (here.now)
```

Everything currently lives in two Jupyter notebooks — there is no package, module, or
entrypoint. `mabstruct_studio` is a subdirectory of the larger `pingmab-agents` course repo
(the parent `.venv`, `pyproject.toml`, and `.env` are shared).

- **`mabstruct_studio.ipynb`** — the maintained notebook. Covers IDEATION → DESIGN →
  DEVELOP → DEPLOY for a single idea, no fan-out. The test phase was deliberately removed
  (commit `beb5eae8`).
- **`mabstruct_experimenting.ipynb`** — the spike/scratch notebook. Keeps the code that was
  pulled out of the studio notebook: `Send`-based parallel fan-out (`fan_out_develop` →
  `develop_one`), the Tier-1 test node, and `run_static_validation_full`. Look here first
  when re-adding a feature; port from here rather than rewriting. Both become relevant again
  once the app runs several ideas per title (R7).

## Running

**Python environment:** the parent repo's venv, `/Users/mab/dev/agents/pingmab-agents/.venv`
(Python 3.12.12, managed by `uv`). There is no venv inside `mabstruct_studio/`. Both
notebooks are already pinned to it — kernelspec `python3`, display name `.venv` — and it is
the only registered Jupyter kernel. If the kernel picker offers anything else (system
Python, a Cursor-created env), it is the wrong one and imports like `langchain_anthropic`
will fail.

```bash
cd /Users/mab/dev/agents/pingmab-agents   # parent repo owns the venv and pyproject.toml
uv sync                                    # install/refresh deps
.venv/bin/jupyter lab                      # or open the notebook in Cursor/VS Code
```

Run project code outside Jupyter with that same interpreter — `.venv/bin/python`, never bare
`python3` (only stdlib-only one-liners like the one below are safe with the system Python).
Add dependencies with `uv add <pkg>` from the parent repo, not `pip install`.

Read a notebook's code without launching Jupyter:

```bash
python3 -c "import json; nb=json.load(open('mabstruct_studio.ipynb')); print('\n'.join(''.join(c['source']) for c in nb['cells'] if c['cell_type']=='code'))"
```

Notebooks no longer depend on the kernel's cwd: `NOTEBOOK_DIR` is resolved from the notebook
file's own location (see *The develop phase* below), so `dev-output/` always lands next to
the notebook.

There is no test suite and no linter. The only automated checks are the in-notebook
validation tiers (below). `node` must be on PATH — Tier-0 shells out to `node --check`.

### API keys

`load_dotenv(override=True)` reads the parent repo's `.env`. Used: `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `TAVILY_API_KEY` (web search), `TELEGRAM_BOT_TOKEN` +
`TELEGRAM_CHAT_ID` (push notifications via the `send_push_notification` tool),
`HERE_NOW_API_KEY` (deploy — see below), and `LANGSMITH_*` for tracing (the cell after the
imports prints whether tracing is live).

## Architecture (as the notebook has it)

### State

One `GameStudioState` TypedDict flows through every graph:

```python
game_title: str
game_ideation: GameIdeaList | None
game_designs: Annotated[list[GameDesignRecord], operator.add]
game_developments: Annotated[list[GameDevelopRecord], operator.add]
game_deployments: Annotated[list[GameDeployRecord], operator.add]
game_html_path: str | None
deployment_url: str | None
```

List fields use `Annotated[..., operator.add]` so parallel workers can append without
clobbering. Records are joined by **`idea_id`** — a UUID assigned in `ideation_node` after
the LLM returns (the LLM never generates it). `GameIdea → GameDesignRecord →
GameDevelopRecord → GameDeployRecord` all carry it. There is no test/`game_tests` field; the
test phase lives only in the experimenting notebook.

### Per-phase models

Models are declared in one cell and swapped by reassigning a single variable
(`LLM_DEVELOP_MODEL = LLM_DEVELOP_OPUS_MODEL`). Keep that pattern — don't inline model IDs
in nodes. Several Opus-vs-Fable develop comparisons have been run; recording those results
is R7's job, and today they exist only in the operator's head.

The develop model is the delicate one, and the comments in that cell record hard-won
constraints:

- Use `ChatAnthropic(...)`, **not** the `"anthropic:claude-opus-5"` string form — the string
  defaults to `max_tokens=4096`, which truncates tool arguments mid-JSON.
- `streaming=True` is required at large `max_tokens` or the HTTP request times out.
- `ModelRetryMiddleware` retries transport faults (`DEVELOP_TRANSPORT_ERRORS`) because those
  surface while the SSE body streams — outside the SDK's own retry window.
- `AnthropicPromptCachingMiddleware` is appended **only** when the model is a
  `ChatAnthropic`; on other providers it warns every turn and caches nothing.
- `gpt-5.6-sol` rejects any `reasoning_effort` other than `"none"` when tools are bound on
  chat completions.

### The develop phase (the interesting part)

The develop agent never writes HTML into chat. It calls `write_game_html_part(content,
part)` in a strict `start → js × N → end` sequence, built by `make_dev_tools(game_title,
idea_id)` — a closure so each parallel worker gets its own buffer. The tool aggressively
rejects malformed input (chunks over `MAX_JS_CHUNK_CHARS = 6000`, a `start` that closes
`</script>`, a `js` chunk containing HTML tags) and only writes to disk on `part=end`.

Output path is anchored to the **notebook's own directory**, not the kernel's cwd:
`_resolve_notebook_dir()` reads `__vsc_ipynb_file__` (VS Code/Cursor), then `__session__` /
`JPY_SESSION_NAME` (JupyterLab, Notebook 7), then falls back to walking up from cwd looking
for the notebook file. `STUDIO_OUTPUT_DIR = NOTEBOOK_DIR / "dev-output"`, giving
`mabstruct_studio/dev-output/<game_title>/<idea_id>/index.html` (the deploy node writes
`herenow.json` beside it; the experimenting notebook's test node writes `game_testing.json`
there too). The cell prints the resolved directory and how it was resolved, and warns loudly
if it had to fall back to cwd — that fallback is the one case where output could land
outside the `.gitignore` rule `mabstruct_studio/dev-output*/`. `develop_node` deletes any
stale `index.html` before the run so a leftover file can't be mistaken for this run's output.

**Validation tiers:**
- **Tier 0** (`run_static_validation`) — exactly one inline `<script>` block + `node --check`
  on it. Runs automatically on write and via the `verify_game_html` tool.
- **Tier 1** (`scripts/game_smoke_test.mjs`, deleted from the working tree but in git
  history; driven by the test node in the experimenting notebook) — executes the game JS in
  a hand-rolled DOM/canvas shim in `node:vm`, simulates a start click, and reports JSON.

On Tier-0 failure `develop_node` issues exactly **one** repair turn that continues the same
conversation — never a second full build. Failures are recorded in
`GameDevelopRecord.tier0_pass` + `summary` rather than raised.

### The deploy phase

`deployment_node` publishes the built `index.html` to [here.now](https://here.now) and
records a `GameDeployRecord` (`slug`, `site_url`, `deployed`, `summary`).

- **The Tier-0 gate is deterministic, not the agent's call.** `DEPLOY_REQUIRE_TIER0 = True`
  skips the deploy when the matching `GameDevelopRecord.tier0_pass` is false, and records a
  skipped deploy instead of raising.
- **Publishing is three steps** — create/update → upload → finalize. Nothing is live until
  finalize succeeds; it is idempotent by `versionId` and answers `409 finalize_in_flight` +
  `Retry-After` while another finalize holds the same version (wait and retry, not a
  failure). Re-publishing identical bytes deduplicates server-side, so the upload loop is
  driven off `uploads`, not the manifest.
- **here.now does not let a caller choose its slug**, so a stable URL means creating the site
  once and updating that slug forever after via `PUT /api/v1/publish/{slug}`; a 404 there
  means the recorded site is gone and a new one is created.
- **The API key has two spellings.** `_herenow_api_key()` accepts `HERE_NOW_API_KEY` (the
  parent repo's `.env`) and `HERENOW_API_KEY` (the here.now skill and the CrewAI tool), then
  falls back to `~/.herenow/credentials`. Without a key, every publish is an anonymous site
  that expires 24 hours later — the record carries a warning when that happens.
- **The registry file, not the agent's summary, is the source of truth** for what went live:
  an agent can describe a deploy it never made, but only `publish_game_site` writes
  `herenow.json`.

### Known rough edges

Both of these are reasons the application exists — fix them in the app, not by patching the
notebook into something it isn't.

**The pipeline is not one graph.** The composed `studio` graph is IDEATION → DESIGN only.
DEVELOP and DEPLOY each run in their own single-node graph (`dev_studio`, `deploy_studio`)
driven by hand-assembled state — the `dev_state = initial_state.copy()` cell sets
`game_ideation` to a bare `list[GameIdea]` and `game_designs` to a bare `GameDesignBrief`.
So `develop_node` reads `state["game_ideation"][0]` and `design.game_sub_title`, and
`deployment_node` reads `state["game_ideation"][CHOSEN_IDEA_INDEX]` — shapes that match that
hand-built state, not `GameIdeaList` / `GameDesignRecord`. Wiring all four phases into one
graph means reconciling those accessors.

**Idea selection is a constant.** `CHOSEN_IDEA_INDEX = 0`, hand-edited. R2 replaces it with
an `interrupt()` and a human choice that survives the session.

**Deployment identity lives in a copied file.** `dev-output/<title>/<idea_id>/herenow.json`
travels with the build folder, so copying a build copies its slug. All three builds under
`dev-output/The Big Swallow/` currently name the same slug `hazy-hazel-6pws` and have
overwritten each other; here.now version history needs a paid plan, so those overwrites are
not restorable. AD5 moves slug ownership into the domain DB — blocked on Q4 (what owns a
stable playtest URL: title, idea, or build label). The deploy-phase review session covering
this is parked; see `REQUIREMENTS.md`.

## Conventions

- Prompts are module-level f-strings named `<PHASE>_SYSTEM_PROMPT` /
  `<PHASE>_HUMAN_PROMPT`, all sharing `MABSTRUCT_GAMESTUDIO_BACKGROUNDER` (sci-fi, cosmic,
  slightly surreal single-player browser games). Keep new phases on that naming.
- Agents are built with `create_agent(model=..., system_prompt=..., tools=...,
  response_format=SomePydanticModel)` and read back via `agent_result["structured_response"]`.
- Each phase gets a node function plus a small standalone `StateGraph` for testing it in
  isolation (`dev_builder` / `dev_studio`, `deploy_builder` / `deploy_studio`) before it
  joins the main graph.
- Every graph cell ends with `display(Image(graph.get_graph().draw_mermaid_png()))`.
- `_message_text(message)` exists because Anthropic models return content as a list of
  blocks (thinking + text); never assume `message.content` is a string.
- Commit messages follow `type(mabstruct): summary`.

## Notes

- `.venv/` is at the parent repo root, not here.
- `memory.db` (SQLite checkpointer) is written next to the notebook and is disposable. So is
  everything under `dev-output/`. The domain DB that AD1 introduces will *not* be — it
  becomes the durable asset of this project.
- The "Persisting to SQLite" / "Adding a UI" / "Recap" cells at the end are leftover course
  scaffolding referencing a `graph`/`spanish` state that this notebook doesn't define — they
  are not part of the studio pipeline.
- Cell numbers drift as the notebook is edited; this file refers to cells by their content.
