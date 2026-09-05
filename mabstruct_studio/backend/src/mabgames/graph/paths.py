"""Where a build's files live.

Replaces the notebook's `_resolve_notebook_dir()` entirely — the kernel-injected
globals (`__vsc_ipynb_file__`, `__session__`), the `JPY_SESSION_NAME` lookup, the
walk up from cwd hunting for a `.ipynb`, and the bare-cwd fallback that could
land output outside the gitignore rule. A package knows where it is;
`Settings.builds_dir` is resolved from the package's own location.

**Builds are keyed by build id, not idea id** (Q4/AD5: the build owns its URL and
its directory). Build ids are fresh UUIDs, so app output cannot collide with the
notebook's existing `<title>/<idea_id>/` folders.
"""

from pathlib import Path


def build_dir(builds_dir: Path, game_title: str, build_id: str) -> Path:
    return Path(builds_dir) / game_title / build_id


def build_html_path(builds_dir: Path, game_title: str, build_id: str) -> Path:
    """The single-file game. `game_title` is used raw, spaces and all."""
    return build_dir(builds_dir, game_title, build_id) / "index.html"
