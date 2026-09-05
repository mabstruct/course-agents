# MABSTRUCT Studio — Requirements & Architecture Decisions

Status: **decisions settled 2026-08-31**, opened the same day. Living document —
requirements below the line are agreed intent; architecture decisions are proposals until
marked ACCEPTED. AD1–AD7 are ACCEPTED and Q1–Q5 are resolved; see *Decisions log*.

## Context

`mabstruct_studio.ipynb` proved the pipeline end to end:

```
IDEATION --> DESIGN --> DEVELOP --> DEPLOY(here.now)
```

It works, and it has taught us what the notebook cannot do:

- Every run starts from zero. Ideas exist only in kernel memory and are lost on restart.
- Idea selection is a hand-edited constant (`CHOSEN_IDEA_INDEX`), not a decision point.
- Nothing records that an idea was designed, built, or shipped — or how good the result was.
- Several develop-model comparisons (Opus vs Fable) were run, and the comparison lives
  only in the operator's head.
- Deploy overwrote one URL repeatedly because identity was carried by a copied file.

The next step is a **MABSTRUCT Studio application** that keeps the same LangGraph pipeline
but wraps it in persistence, a human decision point, and a feedback loop — so the studio
gets better at making games over time instead of restarting each session.

The notebook remains the reference implementation and the place to spike new phases.

### This is a learning project

Stated plainly because it governs every decision below: MABSTRUCT Studio exists to learn the
multi-agent pipeline, not to operate a game studio. Where a decision offers a simple option
and a thorough one, the simple one wins and the rough edge is named rather than engineered
away. Deferring a requirement outright is a legitimate answer here.

Decisions already taken on that basis — deliberate, not gaps awaiting a fix: ranking on a
single human rating rather than a composite (R7/Q1), deferring cross-game learnings entirely
(R5/Q2), and living with opaque deployed-game URLs (AD5).

---

## Requirements

Original lettering from the requirement package is kept in brackets for traceability.

### R1 — Ideas persist [a]

Game ideas survive process restart and are addressable later. Ideation writes every idea
it generates, not just the chosen one — rejected ideas are the comparison set for R7.

### R2 — Human-in-the-loop before DESIGN [b]

The pipeline pauses after IDEATION. A human browses stored ideas and selects which one
proceeds to DESIGN. The run resumes from that selection rather than restarting.

*Implication:* the pause must survive the UI session — the human may decide days later.

### R3 — Lifecycle status per idea [c]

Each idea carries an explicit status: `ideated → designed → developed → deployed`, plus
terminal/exceptional states (e.g. `rejected`, `failed`). Status is queryable and drives
what the UI offers for that idea.

**RESOLVED 2026-08-31 — per-stage records, status derived.** Each stage writes its own row;
status is the newest stage that has one. Re-runs append rather than clobber, stage timings
come for free, and the rows have to exist anyway: R7 needs several builds per idea and R4
needs feedback per build. A single enum column had nowhere to put build #2.

### R4 — Feedback loop after deploy [d]

After a game is deployed, a human can submit feedback against that specific build. That
feedback can be fed back into the pipeline to produce a refurbished version of the game.

**RESOLVED 2026-08-31 — both, but DEVELOP-patch ships first.** "The controls feel floaty"
re-enters at DEVELOP: same design, new build. "The concept is wrong" re-enters at DESIGN:
new design, new build. The human picks. DEVELOP-patch is the common case and much cheaper,
so it is built first; the DESIGN loop follows when a real case demands it.

*Consequence:* `builds` carries a self-reference (`refurb_of`) and a `refurb_entry` of
`design` | `develop`, so lineage is answerable per build.

### R5 — Learnings persist across games [e]

Lessons from every game development accumulate, so later games are produced better and
faster. This is the requirement that makes the studio compound rather than repeat.

**DEFERRED 2026-08-31.** Ship R1–R4 and R6–R7 first; revisit R5 once several titles have
shipped and there is a real history to learn from. Nothing is appended to phase prompts yet,
and the studio does not compound until this is built — that is accepted for now.

The Store layer in AD1 stays in the design so this has somewhere to land. Candidates, kept
for the revisit:
1. **Curated rules** appended to phase prompts (explicit, reviewable, manual to maintain).
2. **Few-shot exemplars** — feed the current best games as reference implementations.
3. **Retrieved learnings** — a Store with semantic search, queried at DESIGN/DEVELOP time.

These are not exclusive. (1) is cheapest; (3) is the LangGraph-native answer and the most
speculative. Do not build (3) before there is enough history to retrieve from. A fourth
option surfaced in the interview and is worth weighing then: a **retrospective node** that
drafts candidate learnings after each game for a human to approve into (1) — the argument
being that a hand-maintained rule list is the thing that reliably rots.

### R6 — Ideas grouped by game title [f]

The initial game title is the grouping key. All ideas generated for "The Big Swallow"
belong to that title, across runs and across time.

### R7 — Leaderboard and production candidate [g]

Where several ideas exist for one title, they are ranked. The top-ranked build is the
**production candidate** — always exactly one per title.

**RESOLVED 2026-08-31 — rank on human rating (1–5) from R4 feedback, and nothing else.**
One honest signal beats a composite whose weights were invented on zero data. Sparse and
subjective is accepted: an unrated build simply has no rank.

*Production-candidate fallback.* R7 wants exactly one candidate per title, but an unrated
title has no ranked build. The candidate is the highest-rated build for that title; with no
ratings at all, it falls back to the **newest deployed build that passed Tier-0**, so a
title always has one.

Other signals were considered and rejected *as the ranking score* — note that Tier-0 is
still recorded and still gates deploys, it just does not rank:

| Candidate signal | Cheap? | Honest? |
| --- | --- | --- |
| Human rating from R4 feedback | yes | yes, but sparse and subjective — **chosen** |
| Tier-0 / Tier-1 automated validation | yes | measures "not broken", not "good" |
| Playtest telemetry (session length, retries) | needs instrumentation in the game | strongest signal, most work |
| LLM-as-judge on the built game | moderate | unproven for playability |

Revisit once there are enough ratings that a composite could be fitted rather than guessed.

---

## Architecture decisions

Proposals with rationale. Alternatives are recorded because the reasoning matters more
than the conclusion — revisit these when an assumption changes.

### AD1 — Three persistence layers, kept separate — ACCEPTED 2026-08-31

The pipeline needs three different kinds of memory, and conflating them is the main risk
in this design.

| Layer | Technology | Holds | Serves |
| --- | --- | --- | --- |
| Checkpointer | `SqliteSaver` (Postgres later) | graph state snapshots per thread | R2 |
| **Domain DB** | SQLite + SQLModel (Postgres later) | titles, ideas, designs, builds, deployments, feedback, ratings | R1, R3, R4, R6, R7 |
| Store | LangGraph Store (KV, optional vectors) | cross-run learnings | R5 |

**Rationale.** LangGraph's own docs draw this line: checkpointers persist a *thread's*
state for short-term memory, HIL, and time travel; Stores persist application data *across*
threads for long-term memory. Neither is a queryable domain model. "All ideas for title X
ranked by score, with status" is a relational query against a schema we own — trying to
serve it from checkpoint blobs or KV namespaces means scanning and reassembling state that
was never indexed for it.

**Consequence.** The domain schema — not the graph — becomes the durable asset. The
notebook's `memory.db` stays disposable; the domain DB does not.

**Technology (decided 2026-08-31): SQLite + SQLModel.** SQLite is the right size for a
single-operator studio on one machine, and an ORM keeps "Postgres later" a URL change plus a
migration rather than a rewrite. SQLModel specifically because it is Pydantic-backed, and the
graph already expresses every structured output as a Pydantic model — one idiom, not two.
Raw SQL was considered and rejected: the hand-written migrations cost more than the ranking
queries save.

**Alternative rejected:** single SQLite file used as checkpointer *and* idea repository.
Cheaper on day one, but R7's ranking and R3's status queries have no good implementation
over checkpoint rows.

### AD2 — Keep LangGraph as the pipeline engine — ACCEPTED 2026-08-31

No change of engine. The phase nodes, prompts, structured outputs, and the chunked
HTML-writing tool contract port from the notebook as-is.

**Rationale.** The expensive knowledge in this project is in the develop phase — model
config, streaming at high `max_tokens`, retry middleware, the `start → js × N → end` tool
protocol, Tier-0 validation. That is all LangGraph/LangChain-shaped and should not be
rewritten to move house.

### AD3 — FastAPI service in front of the graph — ACCEPTED 2026-08-31

The pipeline runs behind an HTTP API rather than in the UI process.

**Rationale.** Two properties force it:
- **R2 pauses for a human.** `interrupt()` + `Command(resume=...)` persists the pause to
  the checkpointer, so the resume can happen in a different process, hours later. That is
  only worth anything if something outlives the UI session.
- **Develop runs take minutes.** They need to be background jobs with streamed progress,
  not blocking request handlers.

It also decouples AD4 — the frontend becomes swappable behind a stable contract.

**Alternative rejected:** UI calls the graph in-process. Simpler, but couples run lifetime
to session lifetime and makes AD4 irreversible.

**Q5 RESOLVED 2026-08-31 — self-hosted FastAPI, written so it can be mounted.**

*The first rationale was wrong and is corrected here.* It claimed the platform could not host
AD1's domain model, so running it would mean running a second service for the leaderboard,
status and feedback queries. It would not. A docs check on 2026-08-31 found that
`langgraph.json` takes an **`http.app`** key — an import path to a custom Starlette or FastAPI
application (`path/to/module.py:app_var`) that is mounted to extend or override the server's
default routes. `auth.path` and `encryption.path` hook custom auth and encryption the same
way. The domain API can live *inside* the LangGraph server.

**What actually decides it, then:**
- **No license question.** Deployment beyond Cloud comes as hybrid, standalone server, or
  self-hosted with a control plane; the licensing terms for self-hosted standalone were not
  established. Self-hosting FastAPI has no such unknown.
- **No LangSmith dependency in the runtime path.** The local LangGraph server requires a
  LangSmith API key (free). Tracing already uses one here, but a key that gates *tracing* is
  a different risk from a key that gates *the studio running at all*.
- **We own the process lifecycle** — migrations, startup, background runs — rather than
  fitting into theirs.

**The cost is real:** the run queue, streamed progress and HIL resume plumbing get written by
hand, and the platform supplies all of it.

**Consequence — keep the API mountable.** Because `http.app` takes a FastAPI app, the same
code can run standalone *or* inside the LangGraph server. Keep the domain API free of
assumptions about owning the process — DB session and startup as dependencies and a lifespan
handler, no work in `main` — and Q5 degrades from a decision into a deployment-time switch.

*Still worth checking* if the hand-written run lifecycle turns out to be a slog: the
licensing terms for a self-hosted standalone server. That is the one fact that would reopen
this. `langgraph dev` and Studio stay useful as debugging aids while porting, either way.

### AD4 — TypeScript + Vite frontend — ACCEPTED 2026-08-31

**Rationale.** The requirement set is app-shaped, not form-shaped: a leaderboard (R7),
status-filtered idea browsing (R3, R6), an embedded playable build, a feedback form (R4),
and live run progress. Gradio is excellent for a single input/output surface and gets
awkward across several stateful views. Vite is already used in this repo at
`6_mcp/frontend/`, so the toolchain is not foreign.

**Alternative considered:** Gradio. Faster to a working screen and Python-only — a real
advantage. Recommended *only* as a throwaway scaffold against the AD3 API while the real
frontend is built; not as the destination, because the leaderboard and preview views are
where it would be rewritten anyway.

**Consequence.** Two languages in the project. Accepted deliberately: AD3 makes the
boundary explicit, and the API contract is the thing worth getting right.

### AD5 — Deployment identity is owned by the domain DB — ACCEPTED 2026-08-31

The here.now slug for a build is recorded in the domain DB, not in a file inside the build
output directory.

**Rationale.** The notebook writes `dev-output/<title>/<idea_id>/herenow.json`. Copying a
build folder copies its slug, so distinct games silently claim one URL and overwrite each
other — this happened, and three builds ended up pointing at one site. Identity must live
where it cannot be duplicated by a filesystem copy.

**Q4 RESOLVED 2026-08-31 — the build owns the URL, plus one title-level alias.** Every build
publishes to its own site and nothing ever overwrites: R4 feedback names a build that stays
playable, and R7 can compare competing ideas side by side. One extra site per title serves
the production candidate for sharing.

*Cost, accepted:* one here.now site per build, so site count grows with every refurb.

**The title alias is DEFERRED to an owned subdomain (decided 2026-08-31).** here.now does not
let a caller choose a slug, so an alias can never be a chosen hostname like
`big-swallow.here.now`. Rather than re-publishing candidate bytes into a stand-in site, the
plan is:

1. Publish one here.now site whose `index.html` is a **start page** — a stable, referenced
   entry point that links out to the per-build slugs.
2. Point an **owned subdomain** at that site.

That gives one solid permanent URL — the **mabgames index** — without the alias having to
impersonate a build. Deferred until the application itself is running; nothing in the schema
depends on it, since `deploys.slug` already maps every build to its own site. The start page
becomes a consumer of the domain DB (it lists production candidates), not a publishing trick.

**Accepted rough edge: the games themselves keep curious URLs.** The subdomain fixes the
*entry point*, not the destinations — every game still lives at an opaque random slug like
`hazy-hazel-6pws`, and a player who bookmarks one has a meaningless address. That is
deliberate and not a gap to close: this is a learning project, and prettifying per-game URLs
buys nothing it would teach. The index page is what people are given; the slugs are what the
index links to.

---

### AD6 — Project structure: `backend/` + `frontend/`, package `mabgames` — ACCEPTED 2026-08-31

The application lives beside the notebooks, split by the boundary AD3 already draws.

```
mabstruct_studio/
├── mabstruct_studio.ipynb          # spike environment — stays at root
├── mabstruct_experimenting.ipynb
├── dev-output/                     # gitignored notebook output
├── backend/
│   ├── pyproject.toml              # see AD7
│   ├── src/mabgames/
│   │   ├── domain/                 # AD1 — schema, models, repository
│   │   ├── graph/                  # AD2 — phases ported from the notebook
│   │   │   ├── state.py  prompts.py  models.py
│   │   │   ├── ideation.py  design.py  develop.py  deploy.py
│   │   │   └── tools/              # write_game_html_part, here.now publish
│   │   ├── api/                    # AD3 — routes, run lifecycle
│   │   └── config.py               # env, keys, paths
│   └── tests/
└── frontend/                       # AD4 — TS + Vite
    ├── package.json
    └── src/
```

**Rationale.**

- **Plain directory names, no prefix.** `mabstruct_studio/` already namespaces them, and the
  repo precedent next door is `6_mcp/backend` + `6_mcp/frontend`. A `mabgames_*` directory
  prefix would also introduce a second brand for one project — everything else here says
  *mabstruct* (both notebooks, `MABSTRUCT_GAMESTUDIO_BACKGROUNDER`, the commit convention
  `type(mabstruct):`, both documents).
- **`mabgames` is the importable package**, which is where that name reads well:
  `from mabgames.domain import Idea`, not `from mabgames_backend.domain import Idea` — the
  layer is not worth repeating in every import line.
- **`domain/` is a sibling of `graph/`, not nested inside it.** AD1's whole argument is that
  the domain schema outlives the pipeline; nesting it under the graph would quietly undo that.
- **Tests live with their runner, not in one top-level `tests/`.** Two languages means two
  runners: pytest under `backend/tests/`, Vitest with the frontend. An `e2e/` directory gets
  added when there is an actual cross-stack test to put in it — not before.

*Depends on:* Q5. If LangGraph Platform's server wins, `api/` shrinks to whatever the
platform does not already supply, and may disappear.

**Alternative rejected:** `mabgames_backend/` + `mabgames_frontend/` with a top-level
`tests/`. Rejected on the redundant prefix, the second brand name, and the split-runner
problem above.

### AD7 — Backend is a uv workspace member — ACCEPTED 2026-08-31

`backend/pyproject.toml` declares the `mabgames` package and its own dependencies; the
parent repo gains `[tool.uv.workspace]` with `mabstruct_studio/backend` as a member.

**Rationale.** The application's dependency list stops being tangled with a course repo's.
One resolved lockfile and one shared `.venv` at the repo root still serve both, so the
notebooks keep working unchanged and there is still no venv inside `mabstruct_studio/`.

**Consequence.** Backend dependencies are added with `uv add <pkg>` from `backend/`, not from
the parent. The parent repo remains the place to add anything the notebooks need.

## Domain schema

**Implemented 2026-08-31** at `backend/src/mabgames/domain/models.py`, with the queries in
`repository.py` and tests in `backend/tests/`. Falls out of R3, R4, R6, R7 and Q4.

```
runs       (id, title_id, status, error, created_at, updated_at)
titles     (id, title, created_at)
ideas      (id, title_id, sub_title, genre, style, reason,
            description, features, created_at, rejected_at)
designs    (id, idea_id, brief, created_at)
builds     (id, idea_id, design_id, html_path, tier0_pass, summary,
            refurb_of, refurb_entry, created_at)
deploys    (id, build_id, slug, site_url, deployed, summary, created_at)
feedback   (id, build_id, rating, comment, created_at)
candidates (title_id, build_id, updated_at)
```

- **`runs` was added 2026-09-01**, beyond the original sketch, to serve R2. `Run.id` **is**
  the LangGraph `thread_id` — no second column to keep in sync. Without it, a run that has not
  finished IDEATION has produced no domain rows at all, so it would be invisible to the human
  who comes back days later in another process; and finding it would mean scanning checkpoint
  blobs, which is exactly what AD1 rejected. `status` is a cache of the checkpointer's truth
  (`running` | `awaiting_selection` | `completed` | `failed`), refreshed on every drain.
  *The division:* the domain DB answers what exists **across** runs; the checkpointer answers
  what **one** run is doing right now. Nothing is copied from graph state into the DB merely to
  make it queryable.
- `titles` is R6's grouping key; every idea for "The Big Swallow" hangs off one row.
- `ideas.id` **is** the notebook's `idea_id` — the UUID assigned after the LLM returns, which
  joins every later stage. `features` is a JSON column.
- `designs.brief` holds the whole `GameDesignBrief` as one JSON document. It is authored
  wholesale by the design agent and never queried field by field, so seventeen columns would
  buy nothing.
- `builds.refurb_of` + `refurb_entry` (`design` | `develop`) carry R4's lineage.
- `deploys.slug` is Q4/AD5's answer: slug identity lives here, never in a file inside the
  build directory that a copy could duplicate. **The app writes no `herenow.json`.**
- `deploys` gained `deployed` + `summary` beyond the original sketch, so a Tier-0 gate skip
  is a real row (`deployed=False`) rather than a missing one — matching the notebook, which
  records a skipped deploy instead of raising.
- `feedback.rating` (1–5) is the only ranking signal (R7/Q1), and is **optional**: "the
  controls feel floaty" is a useful refurb request whether or not a number came with it.

**Status (R3) is not a column** — it is derived by `repository.idea_status`. The rules,
because two of them are judgement calls rather than consequences:

1. `rejected` wins over everything. It is an explicit human act, and an idea can be rejected
   after it was built.
2. `deployed` if any build for the idea has a deploy with `deployed=True`.
3. `failed` if builds exist, none went live, and the **newest** one failed Tier-0. An earlier
   successful deploy outranks a later Tier-0 failure — the idea did reach `deployed`.
4. Otherwise `developed` → `designed` → `ideated`, by the newest stage row that exists.

**`candidates` is a cache, not a second source of truth.** `production_candidate` derives the
answer (highest mean rating, else newest Tier-0-passing deploy); `recompute_candidate` upserts
it so the AD5 start page can read one row per title instead of running the ranking query per
title. Call it after a deploy or a new rating.

*Rough edge, accepted:* rows are ordered by `created_at` at microsecond resolution, so two
rows written in the same microsecond have no defined order. This is a single-operator studio,
not a write-heavy service.

*Not yet built:* migrations. `create_db_and_tables()` creates what is missing and does not
alter what exists, which is enough while the schema is still moving and nothing is in it.

## Decisions log

Every question that was blocking work is now answered. Resolved 2026-08-31 unless noted.

| # | Question | Resolution | Lands in |
| --- | --- | --- | --- |
| Q1 | What score defines the "best" game? | Human rating 1–5 only; candidate falls back to newest Tier-0-passing deploy | R7 |
| Q2 | What mechanism carries learnings forward? | **Deferred** until several titles have shipped | R5 |
| Q3 | Does refurbishment re-enter at DESIGN or DEVELOP? | Both; DEVELOP-patch built first | R4 |
| Q4 | What owns a stable playtest URL? | The build. Title alias deferred to an owned subdomain over a here.now start page | AD5 |
| Q5 | Self-hosted FastAPI or LangGraph Platform server? | Self-hosted FastAPI, written mountable via `http.app`. Docs checked 2026-08-31; first rationale corrected | AD3 |
| — | Status: enum or per-stage records? | Per-stage records, status derived | R3 |
| — | What technology backs the domain DB? | SQLite + SQLModel | AD1 |
| — | Project structure and package naming | `backend/` + `frontend/`, package `mabgames` | AD6 |
| — | Backend dependency management | uv workspace member with its own pyproject | AD7 |

**Nothing blocks implementation.** Three things to carry forward rather than forget: keep the
domain API mountable so Q5 stays reversible, stand up the owned-subdomain start page once the
app runs, and revisit R5 once there is history.

### Delivered 2026-09-01 — R1, R2, R6

The first vertical slice runs: `IDEATION → SELECT (interrupt) → DESIGN`, persisted. Proven
end to end against a live server — ideation paused, the process was killed, a new process
picked the run up from the checkpoint and resumed it into DESIGN.

**Where persistence happens: the API, not the graph nodes.** The nodes stay pure state
transformers with no knowledge of the database, so they remain runnable in the spike notebook;
`api/lifecycle.py` consumes the graph's `stream_mode="updates"` output and calls the
repository. This costs almost nothing because the API must consume that stream anyway, and it
works because **the ideation delta arrives before `__interrupt__`** — the ideas are on disk
before the human is asked to choose between them. `tests/test_layering.py` enforces the rule
by AST: nothing under `graph/` may import `mabgames.domain`.

Two consequences worth not rediscovering:

- **Pydantic objects in graph state must be declared to the checkpoint serializer.** Without
  `JsonPlusSerializer(allowed_msgpack_modules=...)`, langgraph warns that deserializing
  `GameIdeaList` from a checkpoint *"will be blocked in a future version"* — and that load is
  precisely R2's resume path. `graph.studio.STATE_TYPES` is the allowlist, and it pins module
  paths: moving `graph/models.py` orphans every paused run.
- **`ChatOpenAI` raises at construction without a key**, and pydantic-settings does not
  populate `os.environ`. The notebook's module-level model cell therefore cannot port
  literally; `graph/agents.py` uses factories that pass `api_key=` explicitly. This is what
  keeps `import mabgames.graph` free of import-time work (AD3).

Still open in this slice, deliberately: ideas are not attributed to the run that produced
them, and there is no retry endpoint for a failed run.

### Delivered 2026-09-05 — the pipeline is whole

`IDEATION → SELECT → DESIGN → APPROVE → DEVELOP → DEPLOY`, in **one graph**. A title now
becomes a playable game at a live URL, with `builds` and `deploys` rows to show for it.
Proven end to end: ideation, design at the gate in 24s, then a 250s build and a 10s deploy
serving a real 35KB game.

This closes the notebook's last two rough edges. DEVELOP and DEPLOY are no longer separate
single-node graphs fed by hand-assembled state — both now select by `chosen_idea_id` rather
than by index — and `deploys.slug` has replaced `herenow.json`.

**A second pause, before DEVELOP.** R2 asks for one, before DESIGN; this adds another, at the
build gate. Taken deliberately: DEVELOP runs Opus at 32k `max_tokens` for minutes, and a human
who has just read the brief is the cheapest possible check on that spend. Rejecting costs one
design call instead of a whole build, and leaves the idea at `designed` — which the derived
status already reports, with no new state. `RunStatus` gains `awaiting_build_approval`,
`developing` and `deploying`.

**The build owns its identity, and mints it itself.** The API persists only *after* a node
returns, so the row cannot supply the id the node needs before it writes. `develop_node`
generates the `build_id` — exactly as `ideation_node` generates `idea_id` — writes to
`dev-output/<title>/<build_id>/`, and the API persists the row under that id. `record_build`
honours a supplied id for the same reason `record_ideas` does.

**The slug registry survived, as a dict.** The notebook read `herenow.json` back rather than
trusting the agent's summary, because *an agent can describe a deploy it never made*. That
guarantee is worth keeping; the file is not, since copying a build copied its slug. It is now
an in-memory dict the publish tool writes and the node reads, and the API persists it into
`deploys`. A test asserts that an agent claiming a deploy it never made produces
`deployed=False` and no slug.

**Long runs left the request.** `POST /runs/{id}/build` returns `202` and a daemon thread
drives the graph; the seam already writes status per node, so `GET /runs/{id}` reports
`developing` → `deploying` → `completed` with no new machinery. The thread needs its own
session — the request's is closed by then and `Session` is not thread-safe — so both the
session factory and the task runner are injected, which also keeps the test suite synchronous.

*Migration debt is now real.* The `runs.status` column was created as `VARCHAR(18)`, sized for
the longest name at the time; `AWAITING_BUILD_APPROVAL` is 23 characters. SQLite ignores
length constraints so the existing database kept working, but Postgres would not have. This is
the first change `create_db_and_tables()` could not have made honestly, and the next one needs
migrations.

## Parked

- **Deploy-phase review session.** Slug identity (Q4), the three colliding registries in
  `dev-output/`, and the stale build currently live at `hazy-hazel-6pws`. Deliberately
  deferred — see the session recap of 2026-08-31.
- **here.now version history** requires a paid plan, so overwrites are not restorable. This
  was an input to Q4, and build-level URLs answer it: nothing overwrites, so nothing needs
  restoring.
- **R5's learnings mechanism** (Q2), deferred until several titles have shipped.
- **Owned-subdomain start page** (the Q4 title alias), deferred until the application runs.
- **Licensing for a self-hosted standalone LangGraph Platform server** — unestablished, and
  the one fact that would reopen Q5.
- **Composite ranking** (Q1), revisit once enough ratings exist to fit weights rather than
  guess them.

## Notes

- **`CLAUDE.md` names this document as the project's authoritative spec.** Keep the two in
  step: when a decision here becomes ACCEPTED or an open question is answered, say so here
  in the same commit as the code that acts on it.
- The notebook stays the spike environment. Port *from* it into the app; do not fork it.
- `mabstruct_experimenting.ipynb` still holds the parallel `Send` fan-out and the Tier-1
  smoke test — both become relevant again once the app runs multiple ideas per title (R7).
