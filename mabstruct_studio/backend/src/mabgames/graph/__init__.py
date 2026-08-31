"""AD2 — the LangGraph pipeline, ported from `mabstruct_studio.ipynb`.

Empty for now. What lands here, and the two rough edges the port closes:

* `state.py`, `prompts.py`, `models.py`, then `ideation.py`, `design.py`,
  `develop.py`, `deploy.py` and `tools/`.
* The notebook runs DEVELOP and DEPLOY as separate single-node graphs driven by
  hand-assembled state, so their node bodies read shapes that only that state
  has. Here all four phases join **one** graph.
* `CHOSEN_IDEA_INDEX = 0` becomes R2's `interrupt()` and a stored human choice.

Port from the notebook; do not fork it. The develop phase's model config,
streaming behaviour, retry middleware, chunked tool protocol and Tier-0
validation were won the hard way and carry over as-is.
"""
