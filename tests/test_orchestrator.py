import hashlib
import json
import subprocess
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'unslop', 'scripts'))

from orchestrator import compute_hash, parse_header, parse_frontmatter, topo_sort, discover_files, build_order_from_dir, resolve_deps, classify_file, check_freshness, parse_change_file, file_tree, parse_concrete_frontmatter, compute_concrete_deps_hash, build_concrete_order, resolve_extends_chain, resolve_inherited_sections


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
    result = parse_header("\n".join(lines))
    assert result["spec_path"] == "src/retry.py.spec.md"
    assert result["spec_hash"] == "a3f8c2e9b7d1"
    assert result["output_hash"] == "4e2f1a8c9b03"
    assert result["generated"] == "2026-03-22T14:32:00Z"

def test_parse_header_typescript():
    lines = [
        "// @unslop-managed — do not edit directly. Edit src/api.ts.spec.md instead.",
        "// spec-hash:abc123def456 output-hash:789012345678 generated:2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines))
    assert result["spec_path"] == "src/api.ts.spec.md"
    assert result["spec_hash"] == "abc123def456"

def test_parse_header_html():
    lines = [
        "<!-- @unslop-managed — do not edit directly. Edit src/index.html.spec.md instead. -->",
        "<!-- spec-hash:abc123def456 output-hash:789012345678 generated:2026-03-22T14:32:00Z -->",
    ]
    result = parse_header("\n".join(lines))
    assert result["spec_path"] == "src/index.html.spec.md"
    assert result["spec_hash"] == "abc123def456"

def test_parse_header_with_shebang():
    lines = [
        "#!/usr/bin/env python3",
        "# @unslop-managed — do not edit directly. Edit src/cli.py.spec.md instead.",
        "# spec-hash:abc123def456 output-hash:789012345678 generated:2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines))
    assert result["spec_path"] == "src/cli.py.spec.md"

def test_parse_header_missing():
    result = parse_header("def hello():\n    pass\n")
    assert result is None

def test_parse_header_old_format():
    lines = [
        "# @unslop-managed — do not edit directly. Edit src/retry.py.spec.md instead.",
        "# Generated from spec at 2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines))
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


def test_classify_unreadable_managed_file(tmp_path):
    """Binary/unreadable managed file should return error, not crash."""
    (tmp_path / "thing.py.spec.md").write_text("# spec\n\n## Behavior\nDoes stuff.\nMore.\n")
    (tmp_path / "thing.py").write_bytes(b"\x80\x81\x82\x83\xff\xfe")  # invalid UTF-8
    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"))
    assert result["state"] == "error"

def test_classify_missing_hashes_in_header(tmp_path):
    """Header with @unslop-managed but no hashes should be old_format, not conflict."""
    (tmp_path / "thing.py.spec.md").write_text("# spec\n\n## Behavior\nDoes stuff.\nMore.\n")
    (tmp_path / "thing.py").write_text(
        "# @unslop-managed — do not edit directly. Edit thing.py.spec.md instead.\n"
        "# Some other comment without hashes\n"
        "def thing(): pass\n"
    )
    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"))
    assert result["state"] == "old_format"

def test_check_freshness_empty_unit_spec(tmp_path):
    """Unit spec with no ## Files section should report error."""
    (tmp_path / "module.unit.spec.md").write_text("# module spec\n\n## Behavior\nDoes stuff.\n")
    result = check_freshness(str(tmp_path))
    assert any(f["state"] == "error" for f in result["files"])


# --- parse_change_file tests ---

def test_parse_change_file_single_pending():
    content = """<!-- unslop-changes v1 -->
### [pending] Add jitter to backoff -- 2026-03-22T15:00:00Z

Backoff should include random jitter.

---
"""
    result = parse_change_file(content)
    assert len(result) == 1
    assert result[0]["status"] == "pending"
    assert result[0]["description"] == "Add jitter to backoff"
    assert result[0]["timestamp"] == "2026-03-22T15:00:00Z"
    assert "jitter" in result[0]["body"]

def test_parse_change_file_multiple_entries():
    content = """<!-- unslop-changes v1 -->
### [pending] Add jitter -- 2026-03-22T15:00:00Z

Add jitter to backoff.

---

### [tactical] Fix API endpoint -- 2026-03-22T16:30:00Z

Update base URL.

---
"""
    result = parse_change_file(content)
    assert len(result) == 2
    assert result[0]["status"] == "pending"
    assert result[1]["status"] == "tactical"

def test_parse_change_file_empty():
    content = "<!-- unslop-changes v1 -->\n"
    result = parse_change_file(content)
    assert result == []

def test_parse_change_file_no_marker():
    content = "### [pending] Something -- 2026-03-22T15:00:00Z\n\nBody.\n\n---\n"
    result = parse_change_file(content)
    assert result == []

def test_parse_change_file_malformed_entry(capsys):
    content = """<!-- unslop-changes v1 -->
### Missing status marker -- 2026-03-22T15:00:00Z

Body here.

---

### [pending] Valid entry -- 2026-03-22T16:00:00Z

Valid body.

---
"""
    result = parse_change_file(content)
    assert len(result) == 1
    assert result[0]["status"] == "pending"
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower() or "malformed" in captured.err.lower()

def test_parse_change_file_no_timestamp():
    content = """<!-- unslop-changes v1 -->
### [pending] No timestamp entry

Body without timestamp.

---
"""
    result = parse_change_file(content)
    assert len(result) == 1
    assert result[0]["timestamp"] is None

def test_parse_change_file_unknown_status(capsys):
    content = """<!-- unslop-changes v1 -->
### [shipped] Already deployed -- 2026-03-22T15:00:00Z

This was already deployed.

---
"""
    result = parse_change_file(content)
    assert len(result) == 0
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower()

def test_parse_change_file_trailing_entry_no_separator():
    content = """<!-- unslop-changes v1 -->
### [pending] Last entry -- 2026-03-22T15:00:00Z

No trailing separator here.
"""
    result = parse_change_file(content)
    assert len(result) == 1
    assert result[0]["status"] == "pending"

def test_parse_change_file_multiline_body():
    content = """<!-- unslop-changes v1 -->
### [pending] Complex change -- 2026-03-22T15:00:00Z

First paragraph about the change.

Second paragraph with more detail about
why this matters and what constraints apply.

- Bullet point one
- Bullet point two

---
"""
    result = parse_change_file(content)
    assert len(result) == 1
    assert "First paragraph" in result[0]["body"]
    assert "Bullet point two" in result[0]["body"]


def test_check_freshness_pending_changes(tmp_path):
    from orchestrator import check_freshness, compute_hash
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n" + body
    )
    (tmp_path / "thing.py.change.md").write_text(
        "<!-- unslop-changes v1 -->\n"
        "### [pending] Add feature -- 2026-03-22T15:00:00Z\n\nAdd a feature.\n\n---\n"
    )
    result = check_freshness(str(tmp_path))
    assert result["status"] == "fail"  # pending changes = non-fresh
    file_entry = result["files"][0]
    assert file_entry["state"] == "fresh"  # hash state is fresh
    assert "pending_changes" in file_entry
    assert file_entry["pending_changes"]["count"] == 1
    assert file_entry["pending_changes"]["pending"] == 1

def test_check_freshness_no_changes_still_pass(tmp_path):
    from orchestrator import check_freshness, compute_hash
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
    assert "pending_changes" not in result["files"][0]

def test_check_freshness_mixed_changes(tmp_path):
    from orchestrator import check_freshness, compute_hash
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n" + body
    )
    (tmp_path / "thing.py.change.md").write_text(
        "<!-- unslop-changes v1 -->\n"
        "### [pending] Change 1 -- 2026-03-22T15:00:00Z\n\nBody 1.\n\n---\n\n"
        "### [tactical] Change 2 -- 2026-03-22T16:00:00Z\n\nBody 2.\n\n---\n"
    )
    result = check_freshness(str(tmp_path))
    assert result["status"] == "fail"
    pc = result["files"][0]["pending_changes"]
    assert pc["count"] == 2
    assert pc["pending"] == 1
    assert pc["tactical"] == 1


def test_check_freshness_orphan_change_file(tmp_path, capsys):
    """Change file with no matching managed file should appear as error."""
    (tmp_path / "ghost.py.change.md").write_text(
        "<!-- unslop-changes v1 -->\n"
        "### [pending] Add feature -- 2026-03-22T15:00:00Z\n\nBody.\n\n---\n"
    )
    result = check_freshness(str(tmp_path))
    assert result["status"] == "fail"
    orphan = [f for f in result["files"] if f["managed"] == "ghost.py"]
    assert len(orphan) == 1
    assert orphan[0]["state"] == "error"
    assert orphan[0]["spec"] is None
    assert orphan[0]["pending_changes"]["count"] == 1
    captured = capsys.readouterr()
    assert "Orphan change file" in captured.err


def test_check_freshness_unreadable_change_file(tmp_path, capsys):
    """Unreadable change file should warn on stderr and not crash."""
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n" + body
    )
    (tmp_path / "thing.py.change.md").write_bytes(b"\x80\x81\x82\xff\xfe")
    result = check_freshness(str(tmp_path))
    # Should not crash; the managed file itself is fresh
    assert any(f["state"] == "fresh" for f in result["files"])
    captured = capsys.readouterr()
    assert "Cannot read change file" in captured.err


def test_parse_change_file_double_hyphen_timestamp():
    """Double-hyphen separator (canonical format) should parse correctly."""
    content = "<!-- unslop-changes v1 -->\n### [pending] Fix bug -- 2026-03-22T15:00:00Z\n\nBody.\n\n---\n"
    result = parse_change_file(content)
    assert len(result) == 1
    assert result[0]["timestamp"] == "2026-03-22T15:00:00Z"


def test_check_freshness_hint_combined(tmp_path):
    """Existing hint on a non-fresh file should be combined, not overwritten."""
    old_spec = "# old\n\n## Behavior\nOld.\nMore.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(old_spec)
    oh = compute_hash(body)
    (tmp_path / "thing.py.spec.md").write_text("# new\n\n## Behavior\nNew.\nDifferent.\n")
    (tmp_path / "thing.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-22T14:32:00Z\n" + body
    )
    (tmp_path / "thing.py.change.md").write_text(
        "<!-- unslop-changes v1 -->\n"
        "### [pending] Add feature -- 2026-03-22T15:00:00Z\n\nBody.\n\n---\n"
    )
    result = check_freshness(str(tmp_path))
    file_entry = [f for f in result["files"] if f["managed"] == "thing.py"][0]
    # The stale file has no hint by default, so only change hint should appear
    assert "change request(s) awaiting processing" in file_entry["hint"]


def test_parse_change_file_unparseable_content_warns(capsys):
    """File with marker but no valid entries and non-whitespace content should warn."""
    content = "<!-- unslop-changes v1 -->\nSome random text here.\nMore text.\n"
    result = parse_change_file(content)
    assert result == []
    captured = capsys.readouterr()
    assert "no parseable entries" in captured.err


# --- principles-hash tests ---

def test_parse_header_with_principles_hash():
    lines = [
        "# @unslop-managed -- do not edit directly. Edit src/retry.py.spec.md instead.",
        "# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 principles-hash:7f2e1b8a9c04 generated:2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines))
    assert result["spec_hash"] == "a3f8c2e9b7d1"
    assert result["output_hash"] == "4e2f1a8c9b03"
    assert result["principles_hash"] == "7f2e1b8a9c04"

def test_parse_header_without_principles_hash():
    lines = [
        "# @unslop-managed -- do not edit directly. Edit src/retry.py.spec.md instead.",
        "# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 generated:2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines))
    assert result["principles_hash"] is None

def test_parse_header_with_concrete_deps_hash():
    lines = [
        "# @unslop-managed -- do not edit directly. Edit src/handler.py.spec.md instead.",
        "# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 concrete-deps-hash:9c04b8e7f2a1 generated:2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines))
    assert result["concrete_deps_hash"] == "9c04b8e7f2a1"

def test_parse_header_without_concrete_deps_hash():
    lines = [
        "# @unslop-managed -- do not edit directly. Edit src/handler.py.spec.md instead.",
        "# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 generated:2026-03-22T14:32:00Z",
    ]
    result = parse_header("\n".join(lines))
    assert result["concrete_deps_hash"] is None

def test_classify_principles_stale(tmp_path):
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    principles = "# Principles\n\n## Style\n- Use typed errors\n"
    old_prin_hash = compute_hash("old principles content")
    sh = compute_hash(spec)
    oh = compute_hash(body)
    header = (
        f"# @unslop-managed -- do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} principles-hash:{old_prin_hash} generated:2026-03-22T14:32:00Z\n"
    )
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(header + body)
    (tmp_path / ".unslop").mkdir()
    (tmp_path / ".unslop" / "principles.md").write_text(principles)
    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"),
                           project_root=str(tmp_path))
    assert result["state"] == "stale"
    assert "principles" in result.get("hint", "").lower()

def test_classify_principles_fresh(tmp_path):
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    principles = "# Principles\n\n## Style\n- Use typed errors\n"
    prin_hash = compute_hash(principles)
    sh = compute_hash(spec)
    oh = compute_hash(body)
    header = (
        f"# @unslop-managed -- do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} principles-hash:{prin_hash} generated:2026-03-22T14:32:00Z\n"
    )
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(header + body)
    (tmp_path / ".unslop").mkdir()
    (tmp_path / ".unslop" / "principles.md").write_text(principles)
    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"),
                           project_root=str(tmp_path))
    assert result["state"] == "fresh"

def test_classify_principles_deleted(tmp_path):
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)
    header = (
        f"# @unslop-managed -- do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} principles-hash:abc123def456 generated:2026-03-22T14:32:00Z\n"
    )
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(header + body)
    (tmp_path / ".unslop").mkdir()
    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"),
                           project_root=str(tmp_path))
    assert result["state"] == "stale"
    assert "principles" in result.get("hint", "").lower()

def test_classify_principles_with_conflict(tmp_path):
    """Conflict state should be preserved with principles hint appended."""
    old_spec = "# old\n\n## Behavior\nOld.\nMore.\n"
    original_body = "def thing(): pass\n"
    old_prin_hash = compute_hash("old principles")
    sh = compute_hash(old_spec)
    oh = compute_hash(original_body)
    header = (
        f"# @unslop-managed -- do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} principles-hash:{old_prin_hash} generated:2026-03-22T14:32:00Z\n"
    )
    (tmp_path / "thing.py.spec.md").write_text("# new\n\n## Behavior\nNew.\nDifferent.\n")
    (tmp_path / "thing.py").write_text(header + "def thing(): return True\n")
    (tmp_path / ".unslop").mkdir()
    (tmp_path / ".unslop" / "principles.md").write_text("# New Principles\n\n- New rule\n")
    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"),
                           project_root=str(tmp_path))
    assert result["state"] == "conflict"
    assert "principles" in result.get("hint", "").lower()

def test_classify_principles_unreadable(tmp_path):
    """Unreadable principles.md should not crash, should return stale."""
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)
    header = (
        f"# @unslop-managed -- do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} principles-hash:abc123def456 generated:2026-03-22T14:32:00Z\n"
    )
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(header + body)
    (tmp_path / ".unslop").mkdir()
    (tmp_path / ".unslop" / "principles.md").write_bytes(b"\x80\x81\x82")
    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"),
                           project_root=str(tmp_path))
    assert result["state"] == "stale"
    assert "cannot read" in result.get("hint", "").lower() or "principles" in result.get("hint", "").lower()

def test_classify_no_project_root_skips_principles(tmp_path):
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def thing(): pass\n"
    old_prin_hash = compute_hash("old principles")
    sh = compute_hash(spec)
    oh = compute_hash(body)
    header = (
        f"# @unslop-managed -- do not edit directly. Edit thing.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} principles-hash:{old_prin_hash} generated:2026-03-22T14:32:00Z\n"
    )
    (tmp_path / "thing.py.spec.md").write_text(spec)
    (tmp_path / "thing.py").write_text(header + body)
    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"))
    assert result["state"] == "fresh"


def _git_commit_fixture(tmp_path):
    """Helper: init git repo, add all files, commit. --no-gpg-sign: fixture only, GPG not guaranteed in CI."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init", "--no-gpg-sign"],
        cwd=tmp_path, capture_output=True, check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@test.com",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@test.com"},
    )


def test_file_tree_returns_tracked_files(tmp_path):
    """file_tree should return git-tracked filenames as a sorted JSON-serializable list."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "src" / "util.py").write_text("x = 1")
    (tmp_path / "README.md").write_text("# readme")
    _git_commit_fixture(tmp_path)

    result = file_tree(str(tmp_path))
    assert isinstance(result, list)
    assert "src/main.py" in result
    assert "src/util.py" in result
    assert "README.md" in result
    assert result == sorted(result)


def test_file_tree_excludes_untracked(tmp_path):
    """Untracked files should not appear in file_tree output."""
    (tmp_path / "tracked.py").write_text("x = 1")
    _git_commit_fixture(tmp_path)
    (tmp_path / "untracked.py").write_text("y = 2")

    result = file_tree(str(tmp_path))
    assert "tracked.py" in result
    assert "untracked.py" not in result


def test_file_tree_empty_repo(tmp_path):
    """An initialized repo with no tracked files returns empty list, not ['']."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    result = file_tree(str(tmp_path))
    assert result == []


def test_file_tree_nonexistent_directory():
    """file_tree should raise ValueError for nonexistent directories."""
    import pytest
    with pytest.raises(ValueError, match="Directory does not exist"):
        file_tree("/nonexistent/path")


def test_file_tree_not_a_git_repo(tmp_path):
    """file_tree should raise ValueError for non-git directories."""
    import pytest
    with pytest.raises(ValueError, match="Not a git repository"):
        file_tree(str(tmp_path))


# --- concrete spec frontmatter tests ---

def test_parse_concrete_frontmatter_full():
    content = """---
source-spec: src/retry.py.spec.md
target-language: python
ephemeral: false
complexity: high
concrete-dependencies:
  - src/core/pool.py.impl.md
  - src/core/config.py.impl.md
---

# retry.py — Concrete Spec
"""
    result = parse_concrete_frontmatter(content)
    assert result["source_spec"] == "src/retry.py.spec.md"
    assert result["target_language"] == "python"
    assert result["ephemeral"] is False
    assert result["complexity"] == "high"
    assert result["concrete_dependencies"] == [
        "src/core/pool.py.impl.md",
        "src/core/config.py.impl.md",
    ]


def test_parse_concrete_frontmatter_no_deps():
    content = """---
source-spec: src/retry.py.spec.md
target-language: python
ephemeral: true
---
"""
    result = parse_concrete_frontmatter(content)
    assert result["source_spec"] == "src/retry.py.spec.md"
    assert result["ephemeral"] is True
    assert "concrete_dependencies" not in result


def test_parse_concrete_frontmatter_no_frontmatter():
    content = "# Just markdown\n\nNo frontmatter.\n"
    result = parse_concrete_frontmatter(content)
    assert result == {}


def test_parse_concrete_frontmatter_ephemeral_default():
    content = """---
source-spec: src/retry.py.spec.md
target-language: python
---
"""
    result = parse_concrete_frontmatter(content)
    assert "ephemeral" not in result  # not set = caller uses default


def test_compute_concrete_deps_hash_basic(tmp_path):
    # Create upstream concrete spec
    upstream = tmp_path / "src" / "core"
    upstream.mkdir(parents=True)
    (upstream / "pool.py.impl.md").write_text("---\nsource-spec: pool.py.spec.md\ntarget-language: python\nephemeral: false\n---\n\n## Strategy\nSync pool.\n")

    # Create downstream concrete spec with dependency
    (tmp_path / "src" / "handler.py.impl.md").write_text(
        "---\nsource-spec: src/handler.py.spec.md\ntarget-language: python\nephemeral: false\n"
        "concrete-dependencies:\n  - src/core/pool.py.impl.md\n---\n\n## Strategy\nUses pool.\n"
    )

    h1 = compute_concrete_deps_hash(str(tmp_path / "src" / "handler.py.impl.md"), str(tmp_path))
    assert h1 is not None
    assert len(h1) == 12

    # Change upstream
    (upstream / "pool.py.impl.md").write_text("---\nsource-spec: pool.py.spec.md\ntarget-language: python\nephemeral: false\n---\n\n## Strategy\nAsync pool.\n")

    h2 = compute_concrete_deps_hash(str(tmp_path / "src" / "handler.py.impl.md"), str(tmp_path))
    assert h2 != h1  # Hash should change when upstream changes


def test_compute_concrete_deps_hash_missing_dep(tmp_path):
    (tmp_path / "handler.py.impl.md").write_text(
        "---\nsource-spec: handler.py.spec.md\ntarget-language: python\nephemeral: false\n"
        "concrete-dependencies:\n  - nonexistent.py.impl.md\n---\n"
    )
    h = compute_concrete_deps_hash(str(tmp_path / "handler.py.impl.md"), str(tmp_path))
    assert h is not None  # Should still produce a hash (with "missing" marker)


def test_compute_concrete_deps_hash_no_deps(tmp_path):
    (tmp_path / "simple.py.impl.md").write_text(
        "---\nsource-spec: simple.py.spec.md\ntarget-language: python\n---\n"
    )
    h = compute_concrete_deps_hash(str(tmp_path / "simple.py.impl.md"), str(tmp_path))
    assert h is None  # No deps = no hash


def test_check_freshness_ghost_stale(tmp_path):
    """A fresh file with a changed upstream concrete dep should be ghost-stale."""
    spec = "# handler spec\n\n## Behavior\nHandles requests.\nMore detail.\n"
    body = "def handler(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)

    # Write the permanent concrete spec with a concrete dependency
    (tmp_path / "handler.py.impl.md").write_text(
        "---\nsource-spec: handler.py.spec.md\ntarget-language: python\nephemeral: false\n"
        "concrete-dependencies:\n  - core/pool.py.impl.md\n---\n\n## Strategy\nUses sync pool.\n"
    )

    # Write upstream concrete spec (original version)
    core_dir = tmp_path / "core"
    core_dir.mkdir()
    original_upstream = (
        "---\nsource-spec: core/pool.py.spec.md\ntarget-language: python\n"
        "ephemeral: false\n---\n\n## Strategy\nSync pool.\n"
    )
    (core_dir / "pool.py.impl.md").write_text(original_upstream)

    # Compute the concrete-deps-hash at generation time (before upstream changes)
    cdh = compute_concrete_deps_hash(str(tmp_path / "handler.py.impl.md"), str(tmp_path))

    # Write the managed file with the concrete-deps-hash baked in
    (tmp_path / "handler.py.spec.md").write_text(spec)
    (tmp_path / "handler.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit handler.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} concrete-deps-hash:{cdh}"
        f" generated:2026-03-23T00:00:00Z\n" + body
    )

    # Verify it's fresh before the upstream change
    result = check_freshness(str(tmp_path))
    handler_entry = [f for f in result["files"] if f["managed"] == "handler.py"]
    assert len(handler_entry) == 1
    assert handler_entry[0]["state"] == "fresh"

    # Now change the upstream concrete spec (strategy shift)
    (core_dir / "pool.py.impl.md").write_text(
        "---\nsource-spec: core/pool.py.spec.md\ntarget-language: python\n"
        "ephemeral: false\n---\n\n## Strategy\nAsync connection pool with backpressure.\n"
    )

    # Re-check: handler should now be ghost-stale
    result = check_freshness(str(tmp_path))
    handler_entry = [f for f in result["files"] if f["managed"] == "handler.py"]
    assert len(handler_entry) == 1
    assert handler_entry[0]["state"] == "ghost-stale"
    assert "concrete_staleness" in handler_entry[0]
    assert handler_entry[0]["concrete_staleness"]["impl_path"] == "handler.py.impl.md"


def test_check_freshness_ghost_stale_no_stored_hash(tmp_path):
    """Files without concrete-deps-hash should not be flagged as ghost-stale."""
    spec = "# handler spec\n\n## Behavior\nHandles requests.\nMore detail.\n"
    body = "def handler(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)

    # Managed file WITHOUT concrete-deps-hash (pre-feature backward compat)
    (tmp_path / "handler.py.spec.md").write_text(spec)
    (tmp_path / "handler.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit handler.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-23T00:00:00Z\n" + body
    )

    (tmp_path / "handler.py.impl.md").write_text(
        "---\nsource-spec: handler.py.spec.md\ntarget-language: python\nephemeral: false\n"
        "concrete-dependencies:\n  - core/pool.py.impl.md\n---\n\n## Strategy\nUses sync pool.\n"
    )

    core_dir = tmp_path / "core"
    core_dir.mkdir()
    (core_dir / "pool.py.impl.md").write_text(
        "---\nsource-spec: core/pool.py.spec.md\ntarget-language: python\n"
        "ephemeral: false\n---\n\n## Strategy\nAsync pool.\n"
    )

    result = check_freshness(str(tmp_path))
    handler_entry = [f for f in result["files"] if f["managed"] == "handler.py"]
    assert len(handler_entry) == 1
    assert handler_entry[0]["state"] == "fresh"


# --- concrete dependency cycle detection tests ---

def test_build_concrete_order_no_cycle(tmp_path):
    """Linear concrete dependency chain should produce valid order."""
    (tmp_path / "a.py.impl.md").write_text(
        "---\nsource-spec: a.py.spec.md\ntarget-language: python\nephemeral: false\n---\n"
    )
    (tmp_path / "b.py.impl.md").write_text(
        "---\nsource-spec: b.py.spec.md\ntarget-language: python\nephemeral: false\n"
        "concrete-dependencies:\n  - a.py.impl.md\n---\n"
    )
    result = build_concrete_order(str(tmp_path))
    assert result.index("a.py.impl.md") < result.index("b.py.impl.md")


def test_build_concrete_order_cycle_raises(tmp_path):
    """Circular concrete dependencies should raise ValueError."""
    import pytest
    (tmp_path / "a.py.impl.md").write_text(
        "---\nsource-spec: a.py.spec.md\ntarget-language: python\nephemeral: false\n"
        "concrete-dependencies:\n  - b.py.impl.md\n---\n"
    )
    (tmp_path / "b.py.impl.md").write_text(
        "---\nsource-spec: b.py.spec.md\ntarget-language: python\nephemeral: false\n"
        "concrete-dependencies:\n  - a.py.impl.md\n---\n"
    )
    with pytest.raises(ValueError, match="Cycle detected"):
        build_concrete_order(str(tmp_path))


def test_build_concrete_order_three_way_cycle(tmp_path):
    """Three-way circular dependency should be detected."""
    import pytest
    (tmp_path / "a.py.impl.md").write_text(
        "---\nsource-spec: a.spec.md\ntarget-language: python\nephemeral: false\n"
        "concrete-dependencies:\n  - c.py.impl.md\n---\n"
    )
    (tmp_path / "b.py.impl.md").write_text(
        "---\nsource-spec: b.spec.md\ntarget-language: python\nephemeral: false\n"
        "concrete-dependencies:\n  - a.py.impl.md\n---\n"
    )
    (tmp_path / "c.py.impl.md").write_text(
        "---\nsource-spec: c.spec.md\ntarget-language: python\nephemeral: false\n"
        "concrete-dependencies:\n  - b.py.impl.md\n---\n"
    )
    with pytest.raises(ValueError, match="Cycle detected"):
        build_concrete_order(str(tmp_path))


def test_check_freshness_detects_concrete_cycle(tmp_path):
    """check_freshness should report concrete cycles as errors, not crash."""
    # Create minimal spec + managed file
    spec = "# spec\n\n## Behavior\nDoes stuff.\nMore detail.\n"
    body = "def a(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)

    (tmp_path / "a.py.spec.md").write_text(spec)
    (tmp_path / "a.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit a.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-23T00:00:00Z\n" + body
    )

    # Create circular concrete deps
    (tmp_path / "a.py.impl.md").write_text(
        "---\nsource-spec: a.py.spec.md\ntarget-language: python\nephemeral: false\n"
        "concrete-dependencies:\n  - b.py.impl.md\n---\n"
    )
    (tmp_path / "b.py.impl.md").write_text(
        "---\nsource-spec: b.py.spec.md\ntarget-language: python\nephemeral: false\n"
        "concrete-dependencies:\n  - a.py.impl.md\n---\n"
    )

    result = check_freshness(str(tmp_path))
    # Should not crash — should report the cycle as an error entry
    cycle_entries = [f for f in result["files"] if "cycle" in f.get("hint", "").lower()]
    assert len(cycle_entries) == 1
    assert cycle_entries[0]["state"] == "error"


# --- strategy inheritance tests ---

def test_parse_concrete_frontmatter_extends():
    content = """---
source-spec: src/handler.py.spec.md
target-language: python
extends: shared/fastapi-async.impl.md
ephemeral: false
---
"""
    result = parse_concrete_frontmatter(content)
    assert result["extends"] == "shared/fastapi-async.impl.md"


def test_resolve_extends_chain_single(tmp_path):
    """No extends = chain of 1."""
    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\ntarget-language: python\n---\n"
    )
    chain = resolve_extends_chain("child.impl.md", str(tmp_path))
    assert chain == ["child.impl.md"]


def test_resolve_extends_chain_two_levels(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "base.impl.md").write_text(
        "---\ntarget-language: python\n---\n\n## Pattern\n\n- **Concurrency**: async\n"
    )
    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\ntarget-language: python\n"
        "extends: shared/base.impl.md\n---\n"
    )
    chain = resolve_extends_chain("child.impl.md", str(tmp_path))
    assert chain == ["child.impl.md", "shared/base.impl.md"]


def test_resolve_extends_chain_cycle_raises(tmp_path):
    import pytest
    (tmp_path / "a.impl.md").write_text(
        "---\ntarget-language: python\nextends: b.impl.md\n---\n"
    )
    (tmp_path / "b.impl.md").write_text(
        "---\ntarget-language: python\nextends: a.impl.md\n---\n"
    )
    with pytest.raises(ValueError, match="Cycle detected in extends chain"):
        resolve_extends_chain("a.impl.md", str(tmp_path))


def test_resolve_extends_chain_depth_limit(tmp_path):
    import pytest
    # Create a 4-level chain (exceeds MAX_EXTENDS_DEPTH=3)
    (tmp_path / "d.impl.md").write_text("---\ntarget-language: python\n---\n")
    (tmp_path / "c.impl.md").write_text("---\ntarget-language: python\nextends: d.impl.md\n---\n")
    (tmp_path / "b.impl.md").write_text("---\ntarget-language: python\nextends: c.impl.md\n---\n")
    (tmp_path / "a.impl.md").write_text("---\ntarget-language: python\nextends: b.impl.md\n---\n")
    with pytest.raises(ValueError, match="exceeds maximum depth"):
        resolve_extends_chain("a.impl.md", str(tmp_path))


def test_resolve_inherited_sections_lowering_notes(tmp_path):
    """Child should inherit parent's Lowering Notes and override by language."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "base.impl.md").write_text(
        "---\ntarget-language: python\n---\n\n"
        "## Lowering Notes\n\n### Python\n- Use asyncio\n- Use Annotated DI\n\n"
        "### Go\n- Use goroutines\n"
    )
    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\ntarget-language: python\n"
        "extends: shared/base.impl.md\n---\n\n"
        "## Strategy\n\nSome strategy here.\n\n"
        "## Lowering Notes\n\n### Python\n- Use asyncio\n- Custom override for child\n"
    )
    sections = resolve_inherited_sections("child.impl.md", str(tmp_path))
    assert "Lowering Notes" in sections
    # Python should be overridden by child
    assert "Custom override for child" in sections["Lowering Notes"]
    # Go should be inherited from parent
    assert "goroutines" in sections["Lowering Notes"]


def test_resolve_inherited_sections_pattern_merge(tmp_path):
    """Child pattern keys should override parent, non-conflicting preserved."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "base.impl.md").write_text(
        "---\ntarget-language: python\n---\n\n"
        "## Pattern\n\n"
        "- **Concurrency model**: async cooperative\n"
        "- **DI pattern**: Annotated depends\n"
    )
    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\ntarget-language: python\n"
        "extends: shared/base.impl.md\n---\n\n"
        "## Strategy\n\nChild strategy.\n\n"
        "## Pattern\n\n"
        "- **Concurrency model**: threaded pool\n"
    )
    sections = resolve_inherited_sections("child.impl.md", str(tmp_path))
    assert "Pattern" in sections
    # Child overrides Concurrency model
    assert "threaded pool" in sections["Pattern"]
    # Parent's DI pattern is preserved
    assert "Annotated depends" in sections["Pattern"]


def test_resolve_inherited_sections_strategy_not_inherited(tmp_path):
    """Strategy should always come from child, never inherited."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "base.impl.md").write_text(
        "---\ntarget-language: python\n---\n\n"
        "## Strategy\n\nParent strategy — should NOT appear.\n\n"
        "## Pattern\n\n- **Concurrency**: async\n"
    )
    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\ntarget-language: python\n"
        "extends: shared/base.impl.md\n---\n\n"
        "## Strategy\n\nChild strategy — should WIN.\n"
    )
    sections = resolve_inherited_sections("child.impl.md", str(tmp_path))
    assert "Child strategy" in sections["Strategy"]
    assert "Parent strategy" not in sections["Strategy"]


def test_build_concrete_order_includes_extends(tmp_path):
    """extends should be treated as an implicit dependency in build order."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "base.impl.md").write_text(
        "---\ntarget-language: python\n---\n"
    )
    (tmp_path / "child.impl.md").write_text(
        "---\ntarget-language: python\nextends: shared/base.impl.md\n---\n"
    )
    result = build_concrete_order(str(tmp_path))
    base_idx = result.index("shared/base.impl.md")
    child_idx = result.index("child.impl.md")
    assert base_idx < child_idx  # Parent must come before child


# --- multi-target lowering tests ---

def test_parse_concrete_frontmatter_targets():
    content = """---
source-spec: src/auth/auth_logic.spec.md
ephemeral: false
complexity: high
targets:
  - path: src/api/auth.py
    language: python
    notes: "Use FastAPI HTTPException"
  - path: frontend/src/api/auth.ts
    language: typescript
    notes: "Use Axios interceptors"
---
"""
    result = parse_concrete_frontmatter(content)
    assert "targets" in result
    assert len(result["targets"]) == 2
    assert result["targets"][0]["path"] == "src/api/auth.py"
    assert result["targets"][0]["language"] == "python"
    assert result["targets"][0]["notes"] == "Use FastAPI HTTPException"
    assert result["targets"][1]["path"] == "frontend/src/api/auth.ts"
    assert result["targets"][1]["language"] == "typescript"
    # target-language should NOT be set when targets is used
    assert "target_language" not in result


def test_parse_concrete_frontmatter_targets_minimal():
    content = """---
source-spec: src/shared.spec.md
targets:
  - path: backend/shared.py
    language: python
  - path: frontend/shared.ts
    language: typescript
---
"""
    result = parse_concrete_frontmatter(content)
    assert len(result["targets"]) == 2
    assert result["targets"][0]["path"] == "backend/shared.py"
    assert "notes" not in result["targets"][0]


def test_parse_concrete_frontmatter_single_target_language():
    """target-language (single) should still work for backwards compat."""
    content = """---
source-spec: src/retry.py.spec.md
target-language: python
---
"""
    result = parse_concrete_frontmatter(content)
    assert result["target_language"] == "python"
    assert "targets" not in result


def test_parse_concrete_frontmatter_targets_with_deps():
    """targets and concrete-dependencies can coexist."""
    content = """---
source-spec: src/auth.spec.md
targets:
  - path: src/api/auth.py
    language: python
  - path: frontend/src/auth.ts
    language: typescript
concrete-dependencies:
  - src/core/tokens.impl.md
---
"""
    result = parse_concrete_frontmatter(content)
    assert len(result["targets"]) == 2
    assert result["concrete_dependencies"] == ["src/core/tokens.impl.md"]
