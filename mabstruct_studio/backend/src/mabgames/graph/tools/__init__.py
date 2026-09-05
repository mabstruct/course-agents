"""Per-build tool closures.

Each factory returns tools bound to one build, so two builds can never share a
buffer or a slug. That is what makes the develop phase safe to fan out later (R7).
"""
