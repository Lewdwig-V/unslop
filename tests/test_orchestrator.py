import hashlib
import json
import subprocess
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'unslop', 'scripts'))

from orchestrator import compute_hash, parse_header, parse_frontmatter, topo_sort, discover_files, build_order_from_dir, resolve_deps, classify_file, check_freshness


def test_compute_hash_deterministic():
    result = compute_hash("hello world")
    assert len(result) == 12
    assert result == hashlib.sha256("hello world".encode()).hexdigest()[:12]

def test_compute_hash_strips_whitespace():
    result1 = compute_hash("hello world")
    result2 = compute_hash("  hello world  \n\n")
    assert result1 == result2

def test_compute_hash_empty_string():
    result = compute_hash("")
    assert len(result) == 12

def test_parse_header_python():
    lines = [
        "# @unslop-managed — do not edit directly. Edit src/retry.py.spec.md instead.",
        "# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 generated:2026-03-22T14:32:00Z",
        "",
        "def retry():",
    ]
    result = parse_header("\n".join(lines), ".py")
    assert result["spec_path"] == "src/retry.py.spec.md"
    assert result["spec_hash"] == "a3f8c2e9b7d1"
    assert result["output_hash"] == "4e2f1a8c9b03"
    assert result["generated"] == "2026-03-22T14:32:00Z"

def test_parse_header_typescript():
    lines = [
        "// @unslop-managed — do not edit directly. Edit src/api.ts.spec.md instead.",
        "// spec-hash:abc123def456 output-hash:789012345678 generated:2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines), ".ts")
    assert result["spec_path"] == "src/api.ts.spec.md"
    assert result["spec_hash"] == "abc123def456"

def test_parse_header_html():
    lines = [
        "<!-- @unslop-managed — do not edit directly. Edit src/index.html.spec.md instead. -->",
        "<!-- spec-hash:abc123def456 output-hash:789012345678 generated:2026-03-22T14:32:00Z -->",
    ]
    result = parse_header("\n".join(lines), ".html")
    assert result["spec_path"] == "src/index.html.spec.md"
    assert result["spec_hash"] == "abc123def456"

def test_parse_header_with_shebang():
    lines = [
        "#!/usr/bin/env python3",
        "# @unslop-managed — do not edit directly. Edit src/cli.py.spec.md instead.",
        "# spec-hash:abc123def456 output-hash:789012345678 generated:2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines), ".py")
    assert result["spec_path"] == "src/cli.py.spec.md"

def test_parse_header_missing():
    result = parse_header("def hello():\n    pass\n", ".py")
    assert result is None

def test_parse_header_old_format():
    lines = [
        "# @unslop-managed — do not edit directly. Edit src/retry.py.spec.md instead.",
        "# Generated from spec at 2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines), ".py")
    assert result["spec_path"] == "src/retry.py.spec.md"
    assert result["spec_hash"] is None
    assert result["output_hash"] is None
    assert result["old_format"] is True

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


def test_discover_extra_excludes(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("# app")
    (tmp_path / "src" / "custom_cache").mkdir()
    (tmp_path / "src" / "custom_cache" / "cached.py").write_text("# cached")

    result = discover_files(str(tmp_path / "src"), extensions=[".py"], extra_excludes=["custom_cache"])
    assert result == ["app.py"]
    assert not any("cached" in f for f in result)


def test_frontmatter_wrong_indentation_warning(tmp_path, capsys):
    content = "---\ndepends-on:\n\t- tabbed.spec.md\n---\n"
    result = parse_frontmatter(content)
    assert result == []
    captured = capsys.readouterr()
    assert "malformed" in captured.err.lower() or "indentation" in captured.err.lower()


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


# --- classify_file tests ---

def test_classify_fresh(tmp_path):
    spec_content = "# retry spec\n\n## Behavior\nRetries stuff.\nWith backoff.\n"
    body = "def retry(): pass\n"
    sh = compute_hash(spec_content)
    oh = compute_hash(body)
    header = f"# @unslop-managed — do not edit directly. Edit retry.py.spec.md instead.\n# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n"
    (tmp_path / "retry.py.spec.md").write_text(spec_content)
    (tmp_path / "retry.py").write_text(header + body)
    result = classify_file(str(tmp_path / "retry.py"), str(tmp_path / "retry.py.spec.md"))
    assert result["state"] == "fresh"

def test_classify_stale(tmp_path):
    old_spec = "# old spec\n\n## Behavior\nOld behavior.\nMore detail.\n"
    body = "def retry(): pass\n"
    sh = compute_hash(old_spec)
    oh = compute_hash(body)
    header = f"# @unslop-managed — do not edit directly. Edit retry.py.spec.md instead.\n# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n"
    (tmp_path / "retry.py.spec.md").write_text("# new spec\n\n## Behavior\nNew behavior.\nDifferent.\n")
    (tmp_path / "retry.py").write_text(header + body)
    result = classify_file(str(tmp_path / "retry.py"), str(tmp_path / "retry.py.spec.md"))
    assert result["state"] == "stale"

def test_classify_modified(tmp_path):
    spec = "# spec\n\n## Behavior\nRetries stuff.\nWith backoff.\n"
    original_body = "def retry(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(original_body)
    header = f"# @unslop-managed — do not edit directly. Edit retry.py.spec.md instead.\n# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n"
    (tmp_path / "retry.py.spec.md").write_text(spec)
    (tmp_path / "retry.py").write_text(header + "def retry(): return True  # hotfix\n")
    result = classify_file(str(tmp_path / "retry.py"), str(tmp_path / "retry.py.spec.md"))
    assert result["state"] == "modified"

def test_classify_conflict(tmp_path):
    old_spec = "# old\n\n## Behavior\nOld.\nMore.\n"
    original_body = "def retry(): pass\n"
    sh = compute_hash(old_spec)
    oh = compute_hash(original_body)
    header = f"# @unslop-managed — do not edit directly. Edit retry.py.spec.md instead.\n# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n"
    (tmp_path / "retry.py.spec.md").write_text("# new\n\n## Behavior\nNew.\nDifferent.\n")
    (tmp_path / "retry.py").write_text(header + "def retry(): return True\n")
    result = classify_file(str(tmp_path / "retry.py"), str(tmp_path / "retry.py.spec.md"))
    assert result["state"] == "conflict"

def test_classify_no_header(tmp_path):
    (tmp_path / "retry.py.spec.md").write_text("# spec\n\n## Behavior\nStuff.\nMore.\n")
    (tmp_path / "retry.py").write_text("def retry(): pass\n")
    result = classify_file(str(tmp_path / "retry.py"), str(tmp_path / "retry.py.spec.md"))
    assert result["state"] == "unmanaged"

def test_classify_old_header(tmp_path):
    (tmp_path / "retry.py.spec.md").write_text("# spec\n\n## Behavior\nStuff.\nMore.\n")
    (tmp_path / "retry.py").write_text(
        "# @unslop-managed — do not edit directly. Edit retry.py.spec.md instead.\n"
        "# Generated from spec at 2026-03-22T14:32:00Z\n"
        "def retry(): pass\n"
    )
    result = classify_file(str(tmp_path / "retry.py"), str(tmp_path / "retry.py.spec.md"))
    assert result["state"] == "old_format"

def test_classify_spec_missing(tmp_path):
    (tmp_path / "retry.py").write_text(
        "# @unslop-managed — do not edit directly. Edit retry.py.spec.md instead.\n"
        "# spec-hash:abc123def456 output-hash:789012345678 generated:2026-03-22T14:32:00Z\n"
        "def retry(): pass\n"
    )
    result = classify_file(str(tmp_path / "retry.py"), str(tmp_path / "retry.py.spec.md"))
    assert result["state"] == "error"


# --- check_freshness tests ---

def test_check_freshness_all_fresh(tmp_path):
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n" + body
    )
    result = check_freshness(str(tmp_path))
    assert result["status"] == "pass"

def test_check_freshness_has_stale(tmp_path):
    old_spec = "# old\n\n## Behavior\nOld.\nMore.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(old_spec)
    oh = compute_hash(body)
    (tmp_path / "thing.py.spec.md").write_text("# new\n\n## Behavior\nNew.\nDifferent.\n")
    (tmp_path / "thing.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n" + body
    )
    result = check_freshness(str(tmp_path))
    assert result["status"] == "fail"

def test_cli_check_freshness(tmp_path):
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n" + body
    )
    r = subprocess.run(
        [sys.executable, "unslop/scripts/orchestrator.py", "check-freshness", str(tmp_path)],
        capture_output=True, text=True
    )
    assert r.returncode == 0
    output = json.loads(r.stdout)
    assert output["status"] == "pass"


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
