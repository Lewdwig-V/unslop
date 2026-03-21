import json
import subprocess
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'unslop', 'scripts'))

from orchestrator import parse_frontmatter, topo_sort, discover_files, build_order_from_dir, resolve_deps

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


def test_discover_py_files(tmp_path):
    (tmp_path / "module").mkdir()
    (tmp_path / "module" / "handler.py").write_text("# handler")
    (tmp_path / "module" / "utils.py").write_text("# utils")
    (tmp_path / "module" / "test_handler.py").write_text("# test")
    (tmp_path / "module" / "__pycache__").mkdir()
    (tmp_path / "module" / "__pycache__" / "handler.cpython-311.pyc").write_text("")

    result = discover_files(str(tmp_path / "module"), extensions=[".py"])
    assert "handler.py" in result
    assert "utils.py" in result
    assert "test_handler.py" not in result
    assert not any("cpython" in f for f in result)

def test_discover_returns_relative_paths(tmp_path):
    (tmp_path / "module" / "sub").mkdir(parents=True)
    (tmp_path / "module" / "sub" / "app.py").write_text("# app")
    result = discover_files(str(tmp_path / "module"), extensions=[".py"])
    assert result == ["sub/app.py"]

def test_discover_excludes_test_dirs(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("# app")
    (tmp_path / "src" / "__tests__").mkdir()
    (tmp_path / "src" / "__tests__" / "app.test.py").write_text("# test")

    result = discover_files(str(tmp_path / "src"), extensions=[".py"])
    assert "app.py" in result
    assert not any("app.test.py" in f for f in result)

def test_discover_excludes_target_dir(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("// lib")
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "debug.rs").write_text("// build artifact")

    result = discover_files(str(tmp_path), extensions=[".rs"])
    filenames = [os.path.basename(f) for f in result]
    assert "lib.rs" in filenames
    assert "debug.rs" not in filenames


def test_build_order_from_specs(tmp_path):
    (tmp_path / "a.py.spec.md").write_text(
        "---\ndepends-on:\n  - b.py.spec.md\n---\n\n# a spec"
    )
    (tmp_path / "b.py.spec.md").write_text("# b spec\n\nNo deps.")
    result = build_order_from_dir(str(tmp_path))
    assert result == ["b.py.spec.md", "a.py.spec.md"]


def test_build_order_cycle_error(tmp_path):
    (tmp_path / "a.py.spec.md").write_text("---\ndepends-on:\n  - b.py.spec.md\n---\n")
    (tmp_path / "b.py.spec.md").write_text("---\ndepends-on:\n  - a.py.spec.md\n---\n")
    try:
        build_order_from_dir(str(tmp_path))
        assert False, "Should have raised"
    except ValueError as e:
        assert "cycle" in str(e).lower()


def test_resolve_deps_transitive(tmp_path):
    (tmp_path / "a.py.spec.md").write_text("---\ndepends-on:\n  - b.py.spec.md\n---\n")
    (tmp_path / "b.py.spec.md").write_text("---\ndepends-on:\n  - c.py.spec.md\n---\n")
    (tmp_path / "c.py.spec.md").write_text("# c spec")
    result = resolve_deps(str(tmp_path / "a.py.spec.md"), str(tmp_path))
    assert result == ["c.py.spec.md", "b.py.spec.md"]


def test_resolve_deps_cycle_error(tmp_path):
    (tmp_path / "a.py.spec.md").write_text("---\ndepends-on:\n  - b.py.spec.md\n---\n")
    (tmp_path / "b.py.spec.md").write_text("---\ndepends-on:\n  - a.py.spec.md\n---\n")
    try:
        resolve_deps(str(tmp_path / "a.py.spec.md"), str(tmp_path))
        assert False, "Should have raised"
    except ValueError as e:
        assert "cycle" in str(e).lower()


def test_build_order_nonexistent_directory():
    try:
        build_order_from_dir("/nonexistent/path/xyz")
        assert False, "Should have raised"
    except ValueError as e:
        assert "does not exist" in str(e).lower()


def test_discover_nonexistent_directory():
    try:
        discover_files("/nonexistent/path/xyz")
        assert False, "Should have raised"
    except ValueError as e:
        assert "does not exist" in str(e).lower()


def test_missing_dependency_warning(tmp_path, capsys):
    (tmp_path / "a.py.spec.md").write_text(
        "---\ndepends-on:\n  - nonexistent.py.spec.md\n---\n\n# a spec"
    )
    result = build_order_from_dir(str(tmp_path))
    assert "nonexistent.py.spec.md" in result
    assert "a.py.spec.md" in result
    captured = capsys.readouterr()
    assert "Missing dependency specs" in captured.err
    assert "nonexistent.py.spec.md" in captured.err


# --- CLI integration tests ---

ORCHESTRATOR_SCRIPT = os.path.join(
    os.path.dirname(__file__), '..', 'unslop', 'scripts', 'orchestrator.py'
)


def _run_cli(*args):
    """Helper to run orchestrator.py as a subprocess."""
    return subprocess.run(
        [sys.executable, ORCHESTRATOR_SCRIPT, *args],
        capture_output=True,
        text=True,
    )


def test_cli_discover_happy_path(tmp_path):
    (tmp_path / "app.py").write_text("# app")
    (tmp_path / "lib.py").write_text("# lib")
    proc = _run_cli("discover", str(tmp_path), "--extensions", ".py")
    assert proc.returncode == 0
    result = json.loads(proc.stdout)
    assert "app.py" in result
    assert "lib.py" in result


def test_cli_build_order_happy_path(tmp_path):
    (tmp_path / "a.py.spec.md").write_text(
        "---\ndepends-on:\n  - b.py.spec.md\n---\n\n# a spec"
    )
    (tmp_path / "b.py.spec.md").write_text("# b spec\n\nNo deps.")
    proc = _run_cli("build-order", str(tmp_path))
    assert proc.returncode == 0
    result = json.loads(proc.stdout)
    assert result == ["b.py.spec.md", "a.py.spec.md"]


def test_cli_deps_happy_path(tmp_path):
    (tmp_path / "a.py.spec.md").write_text(
        "---\ndepends-on:\n  - b.py.spec.md\n---\n\n# a spec"
    )
    (tmp_path / "b.py.spec.md").write_text("# b spec")
    proc = _run_cli("deps", str(tmp_path / "a.py.spec.md"), "--root", str(tmp_path))
    assert proc.returncode == 0
    result = json.loads(proc.stdout)
    assert result == ["b.py.spec.md"]


def test_cli_unknown_command():
    proc = _run_cli("frobnicate")
    assert proc.returncode == 1
    assert "Unknown command" in proc.stderr


def test_cli_missing_args():
    proc = _run_cli("discover")
    assert proc.returncode == 1
    assert "Usage" in proc.stderr


def test_cli_cycle_error_json(tmp_path):
    (tmp_path / "a.py.spec.md").write_text("---\ndepends-on:\n  - b.py.spec.md\n---\n")
    (tmp_path / "b.py.spec.md").write_text("---\ndepends-on:\n  - a.py.spec.md\n---\n")
    proc = _run_cli("build-order", str(tmp_path))
    assert proc.returncode == 1
    # stderr should contain JSON with an error key
    err_lines = [line for line in proc.stderr.strip().split("\n") if line.startswith("{")]
    assert len(err_lines) >= 1
    err_obj = json.loads(err_lines[-1])
    assert "error" in err_obj
    assert "cycle" in err_obj["error"].lower()
