"""The chunked write protocol. Every rejection is a returned string, never a raise."""

import pytest

from mabgames.graph.tools.html_writer import make_dev_tools
from mabgames.graph.validation import MAX_JS_CHUNK_CHARS

START = "<!DOCTYPE html><html><body><canvas></canvas><script>"
END = "</script></body></html>"


@pytest.fixture(name="tools")
def tools_fixture(tmp_path):
    write, verify = make_dev_tools(tmp_path, "The Big Swallow", "build-1")
    return write, verify, tmp_path / "The Big Swallow" / "build-1" / "index.html"


def test_nothing_lands_on_disk_until_end(tools):
    write, _, path = tools
    assert "Buffered start" in write.invoke({"content": START, "part": "start"})
    assert "Buffered js" in write.invoke({"content": "const a = 1;", "part": "js"})
    assert not path.exists(), "the file must not appear until part=end"

    result = write.invoke({"content": END, "part": "end"})
    assert path.exists()
    assert "Tier-0 validation: PASS" in result
    assert "const a = 1;" in path.read_text()


def test_js_before_start_is_rejected(tools):
    write, _, path = tools
    assert write.invoke({"content": "const a = 1;", "part": "js"}).startswith("Write rejected")
    assert not path.exists()


def test_an_oversized_chunk_is_rejected(tools):
    write, _, _ = tools
    write.invoke({"content": START, "part": "start"})
    result = write.invoke({"content": "x" * (MAX_JS_CHUNK_CHARS + 1), "part": "js"})
    assert "chunk too large" in result


def test_a_start_that_closes_the_script_is_rejected(tools):
    write, _, _ = tools
    result = write.invoke({"content": START + "let a=1;" + END, "part": "start"})
    assert "must NOT close" in result


def test_html_inside_a_js_chunk_is_rejected(tools):
    write, _, _ = tools
    write.invoke({"content": START, "part": "start"})
    result = write.invoke({"content": "const a=1;</script><body>", "part": "js"})
    assert "raw JavaScript only" in result


def test_a_bad_part_name_and_empty_content_are_rejected(tools):
    write, _, _ = tools
    assert "part must be" in write.invoke({"content": "x", "part": "middle"})
    assert "content is empty" in write.invoke({"content": "   ", "part": "start"})


def test_end_reports_a_tier0_failure_without_raising(tools):
    write, verify, path = tools
    write.invoke({"content": START, "part": "start"})
    write.invoke({"content": "const a = ;", "part": "js"})
    result = write.invoke({"content": END, "part": "end"})

    assert path.exists(), "the file is still written — the failure is recorded, not thrown"
    assert "Tier-0 validation: FAIL" in result
    assert "Tier-0 validation: FAIL" in verify.invoke({})


def test_each_build_gets_its_own_buffer(tmp_path):
    """Two builds must not interleave — this is what makes fan-out safe (R7)."""
    write_a, _ = make_dev_tools(tmp_path, "T", "build-a")
    write_b, _ = make_dev_tools(tmp_path, "T", "build-b")

    write_a.invoke({"content": START, "part": "start"})
    # b has its own empty buffer, so a js chunk is out of sequence for it.
    assert "call part=start" in write_b.invoke({"content": "const b=1;", "part": "js"})

    write_a.invoke({"content": "const a=1;", "part": "js"})
    write_a.invoke({"content": END, "part": "end"})
    assert (tmp_path / "T" / "build-a" / "index.html").exists()
    assert not (tmp_path / "T" / "build-b").exists()
