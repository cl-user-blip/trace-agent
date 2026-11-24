from pathlib import Path

import pytest

from trace_agent.tools import SecurityError, ToolError, Tools


@pytest.fixture
def tools(tmp_path):
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "cache.md").write_text("# cache\n缓存 cache 根因为 namespace。\n修复方法是回滚配置。\n", encoding="utf-8")
    (tmp_path / "secret.md").write_text("private", encoding="utf-8")
    return Tools(root)


def test_read_preserves_one_based_source_lines(tools):
    result = tools.invoke("read", {"path": "cache.md", "start": 2, "limit": 1})
    assert result["lines"] == [{"line": 2, "text": "缓存 cache 根因为 namespace。", "citation": "[cache.md:L2]"}]


def test_search_zero_matches_returns_no_fake_evidence(tools):
    assert tools.invoke("search", {"query": "quasar neutrino"})["hits"] == []


@pytest.mark.parametrize("path", ["../secret.md", "C:/secret.md", "C:\\secret.md", "/etc/passwd", "cache.md/../cache.md"])
def test_path_escape_is_denied(tools, path):
    with pytest.raises((SecurityError, OSError)):
        tools.invoke("read", {"path": path})


def test_symlink_cannot_escape_root(tools, tmp_path):
    link = tools.root / "linked.md"
    try:
        link.symlink_to(tmp_path / "secret.md")
    except OSError:
        pytest.skip("creating symlinks requires platform privilege")
    with pytest.raises(SecurityError):
        tools.invoke("read", {"path": "linked.md"})
    with pytest.raises(SecurityError):
        tools.invoke("search", {"query": "private"})


@pytest.mark.parametrize("name,args", [
    ("shell", {"command": "pwd"}), ("__getattribute__", {"name": "root"}),
    ("read", {"path": "cache.md", "limit": True}), ("read", {"path": "cache.md", "extra": 1}),
    ("read", {}), ("search", {"query": "cache", "limit": 999}),
])
def test_allowlist_types_and_bounds(tools, name, args):
    with pytest.raises(ToolError):
        tools.invoke(name, args)


@pytest.mark.parametrize("expression", ["__import__('os').system('whoami')", "(1).__class__", "open('x')", "[x for x in range(9)]", "2 ** 999", "1 / 0", "1e309", "1e12 * 2", "True + 1"])
def test_calculator_cannot_execute_code_or_unbounded_math(tools, expression):
    with pytest.raises(ToolError):
        tools.invoke("calculator", {"expression": expression})


def test_calculator_runs_real_arithmetic(tools):
    assert tools.invoke("calculator", {"expression": "(128-96)/128*100"})["value"] == 25
    assert tools.invoke("calculator", {"expression": "-2 ** 3 + 10"})["value"] == 2


def test_large_documents_are_not_read(tools):
    (tools.root / "large.md").write_text("x" * 262145, encoding="utf-8")
    with pytest.raises(ToolError):
        tools.read("large.md")

