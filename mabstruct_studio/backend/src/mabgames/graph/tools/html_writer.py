"""The chunked HTML-writing protocol: start -> js x N -> end.

Ported from the notebook, rejection rules intact. The develop agent never writes
HTML into chat; it calls this tool in a strict sequence, and the file only lands
on disk on `part=end`.

Every rejection is a *returned string*, never an exception — the agent reads it
as tool output and corrects itself. The buffer lives in the closure, so each
build gets its own and parallel workers cannot interleave.

Known rough edge, deliberately kept: the buffer is in-process memory. If the
process dies mid-assembly every chunk is lost and the build restarts from
`part=start`. Persisting partial assembly is real work for a case that costs one
retry.
"""

from pathlib import Path

from langchain_core.tools import tool

from mabgames.graph.paths import build_html_path
from mabgames.graph.validation import MAX_JS_CHUNK_CHARS, run_static_validation


def make_dev_tools(builds_dir: Path, game_title: str, build_id: str) -> list:
    """Per-build HTML assembly tools (safe for parallel develop workers)."""
    buffer: list[str] = []

    @tool
    def write_game_html_part(content: str, part: str) -> str:
        """Assemble a single-file HTML game across start → js chunks → end."""
        nonlocal buffer

        if not content or not str(content).strip():
            return "Write rejected: content is empty."

        normalized = part.strip().lower()
        if normalized not in {"start", "js", "end"}:
            return 'Write rejected: part must be "start", "js", or "end".'

        # The size gate applies to start and js only — end carries the closing
        # tags and may legitimately be larger.
        if normalized in {"start", "js"} and len(content) > MAX_JS_CHUNK_CHARS:
            return (
                f"Write rejected: chunk too large ({len(content)} chars). "
                f"Split into pieces under {MAX_JS_CHUNK_CHARS} characters."
            )

        if normalized == "start":
            buffer.clear()
            lower = content.lower()
            if not lower.lstrip().startswith("<!doctype html"):
                return "Write rejected: start must begin with <!DOCTYPE html>"
            if "<script" not in lower:
                return "Write rejected: start must open exactly one <script> block"
            if "</script>" in lower or "</html>" in lower:
                return (
                    "Write rejected: start must NOT close </script> or </html>. "
                    "Use part=js for code and part=end for closing tags."
                )
            buffer.append(content)
            return f"Buffered start ({len(content)} chars). Next: part=js, then part=end."

        if normalized == "js":
            if not buffer:
                return "Write rejected: call part=start before part=js."
            lower = content.lower()
            for tag in ("<script", "</script>", "</html>", "<!doctype", "</body>", "<body"):
                if tag in lower:
                    return f"Write rejected: js part must be raw JavaScript only (found {tag})."
            buffer.append(content)
            total = sum(len(piece) for piece in buffer)
            return f"Buffered js ({len(content)} chars). Assembly total: {total} chars."

        if not buffer:
            return "Write rejected: call part=start before part=end."
        lower = content.lower()
        if "</script>" not in lower or "</html>" not in lower:
            return "Write rejected: end must include </script></body></html>."

        buffer.append(content)
        full = "".join(buffer)
        path = build_html_path(builds_dir, game_title, build_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(full, encoding="utf-8")
        buffer.clear()

        validation = run_static_validation(path)
        status = "PASS" if validation["pass"] else "FAIL"
        lines = [f"Wrote {path} ({len(full)} bytes)", f"Tier-0 validation: {status}"]
        if validation["issues"]:
            lines.append("Issues: " + "; ".join(validation["issues"]))
        elif validation["pass"]:
            lines.append("Single inline script block parsed successfully.")
        if not validation["pass"]:
            lines.append("Fix issues and rewrite using part=start again.")
        return "\n".join(lines)

    @tool
    def verify_game_html() -> str:
        """Run Tier-0 validation on the current build's index.html."""
        path = build_html_path(builds_dir, game_title, build_id)
        validation = run_static_validation(path)
        status = "PASS" if validation["pass"] else "FAIL"
        lines = [f"Tier-0 validation: {status}", f"File: {path}"]
        if validation["issues"]:
            lines.append("Issues:")
            lines.extend(f"- {issue}" for issue in validation["issues"])
        return "\n".join(lines)

    return [write_game_html_part, verify_game_html]
