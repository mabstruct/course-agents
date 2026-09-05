"""Tier-0 static validation: exactly one inline <script> block that node can parse.

Ported from the notebook. Tier-0 is recorded on every build and gates deploys
deterministically, but it never ranks (R7/Q1) — it measures "not broken", not
"good".

Tier-1 (the `node:vm` smoke test) is not ported. It lives in
`mabstruct_experimenting.ipynb` and becomes relevant when the app runs several
ideas per title.
"""

import re
import subprocess
import tempfile
from pathlib import Path

MAX_JS_CHUNK_CHARS = 6000

# Inline blocks only — a `src=` script is somebody else's code.
SCRIPT_BLOCK_RE = re.compile(
    r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)

NODE_MISSING = "node is not installed — cannot run JS parse check"


def run_static_validation(html_path: Path) -> dict:
    """Tier 0: single inline script block + `node --check`.

    Returns `{"pass": bool, "issues": list[str], "checks": dict}`. Never raises —
    a failure is recorded, not thrown.
    """
    issues: list[str] = []
    checks: dict = {}

    if not html_path.exists():
        return {"pass": False, "issues": [f"missing file: {html_path}"], "checks": checks}

    html = html_path.read_text(encoding="utf-8")
    checks["bytes"] = len(html)
    script_blocks = [block.strip() for block in SCRIPT_BLOCK_RE.findall(html) if block.strip()]
    checks["script_blocks"] = len(script_blocks)
    if len(script_blocks) != 1:
        issues.append(f"expected exactly 1 inline <script> block, found {len(script_blocks)}")

    for index, block in enumerate(script_blocks):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=f"_{index}.js", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(block)
            tmp_path = Path(tmp.name)
        try:
            proc = subprocess.run(
                ["node", "--check", str(tmp_path)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode != 0:
                message = (proc.stderr or proc.stdout or "parse failed").strip()
                issues.append(f"script block {index}: {message}")
        except FileNotFoundError:
            # Distinguishable from invalid JS on purpose: a machine without node
            # blocks every deploy, and that should not read as a broken game.
            issues.append(NODE_MISSING)
            checks["node_missing"] = True
            break
        except subprocess.TimeoutExpired:
            issues.append(f"script block {index}: node --check timed out")
        finally:
            tmp_path.unlink(missing_ok=True)

    return {"pass": not issues, "issues": issues, "checks": checks}


def node_is_missing(validation: dict) -> bool:
    """True when Tier-0 failed only because `node` is not on PATH."""
    return bool(validation.get("checks", {}).get("node_missing"))
