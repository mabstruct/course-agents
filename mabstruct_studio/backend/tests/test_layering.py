"""The architectural decision, enforced.

`graph/` holds pure state transformers that must stay runnable in the spike
notebook; the API persists their output by consuming the update stream. That
only holds while nothing under `graph/` reaches for the database — which is a
rule a test can keep and a convention cannot.

AST over the source rather than a `sys.modules` probe: deterministic,
order-independent, and it catches a lazy import inside a function body.
"""

import ast
from pathlib import Path

import mabgames.graph

GRAPH_DIR = Path(mabgames.graph.__file__).parent


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return modules


def test_graph_never_imports_the_domain():
    checked = 0
    for path in GRAPH_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text())
        offenders = [m for m in _imported_modules(tree) if m.startswith("mabgames.domain")]
        assert not offenders, f"{path.name} imports {offenders}"
        checked += 1
    assert checked >= 8, "expected the whole graph package to be scanned"
