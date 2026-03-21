import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'unslop', 'scripts'))

from orchestrator import parse_frontmatter, topo_sort

def test_parse_depends_on():
    content = """---
depends-on:
  - src/auth/tokens.py.spec.md
  - src/auth/errors.py.spec.md
---

# handler.py spec
"""
    result = parse_frontmatter(content)
    assert result == ["src/auth/tokens.py.spec.md", "src/auth/errors.py.spec.md"]

def test_parse_no_frontmatter():
    content = "# Just a spec\n\n## Purpose\nDoes stuff"
    result = parse_frontmatter(content)
    assert result == []

def test_parse_empty_depends_on():
    content = "---\ndepends-on:\n---\n\n# spec"
    result = parse_frontmatter(content)
    assert result == []

def test_parse_no_depends_on_key():
    content = "---\nversion: 1.0\n---\n\n# spec"
    result = parse_frontmatter(content)
    assert result == []

def test_parse_frontmatter_only_between_delimiters():
    content = "---\ndepends-on:\n  - a.spec.md\n---\n\n  - not/a/dep.spec.md"
    result = parse_frontmatter(content)
    assert result == ["a.spec.md"]


def test_topo_sort_linear():
    graph = {
        "a.spec.md": ["b.spec.md"],
        "b.spec.md": ["c.spec.md"],
        "c.spec.md": [],
    }
    result = topo_sort(graph)
    assert result.index("c.spec.md") < result.index("b.spec.md")
    assert result.index("b.spec.md") < result.index("a.spec.md")

def test_topo_sort_diamond():
    graph = {
        "a.spec.md": ["b.spec.md", "c.spec.md"],
        "b.spec.md": ["d.spec.md"],
        "c.spec.md": ["d.spec.md"],
        "d.spec.md": [],
    }
    result = topo_sort(graph)
    assert result.index("d.spec.md") < result.index("b.spec.md")
    assert result.index("d.spec.md") < result.index("c.spec.md")
    assert result.index("b.spec.md") < result.index("a.spec.md")
    assert result.index("c.spec.md") < result.index("a.spec.md")

def test_topo_sort_no_deps():
    graph = {"a.spec.md": [], "b.spec.md": [], "c.spec.md": []}
    result = topo_sort(graph)
    assert set(result) == {"a.spec.md", "b.spec.md", "c.spec.md"}

def test_topo_sort_cycle():
    graph = {
        "a.spec.md": ["b.spec.md"],
        "b.spec.md": ["a.spec.md"],
    }
    try:
        topo_sort(graph)
        assert False, "Should have raised"
    except ValueError as e:
        assert "cycle" in str(e).lower()
