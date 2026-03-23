import hashlib
import json
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "unslop", "scripts"))

from orchestrator import (
    compute_hash,
    parse_header,
    parse_frontmatter,
    topo_sort,
    discover_files,
    build_order_from_dir,
    resolve_deps,
    classify_file,
    check_freshness,
    parse_change_file,
    file_tree,
    parse_concrete_frontmatter,
    compute_concrete_deps_hash,
    compute_concrete_manifest,
    format_manifest_header,
    diagnose_ghost_staleness,
    format_ghost_diagnostic,
    build_concrete_order,
    resolve_extends_chain,
    resolve_inherited_sections,
    get_all_strategy_providers,
    get_registry_key_for_spec,
    flatten_inheritance_chain,
    ripple_check,
    render_dependency_graph,
    STRICT_CHILD_ONLY,
)


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
    (tmp_path / "a.py.spec.md").write_text("---\ndepends-on:\n  - b.py.spec.md\n---\n\n# a spec")
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
    (tmp_path / "a.py.spec.md").write_text("---\ndepends-on:\n  - nonexistent.py.spec.md\n---\n\n# a spec")
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
        [sys.executable, "unslop/scripts/orchestrator.py", "check-freshness", str(tmp_path)], capture_output=True, text=True
    )
    assert r.returncode == 0
    output = json.loads(r.stdout)
    assert output["status"] == "pass"


# --- CLI integration tests ---

ORCHESTRATOR_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "unslop", "scripts", "orchestrator.py")


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
    (tmp_path / "a.py.spec.md").write_text("---\ndepends-on:\n  - b.py.spec.md\n---\n\n# a spec")
    (tmp_path / "b.py.spec.md").write_text("# b spec\n\nNo deps.")
    proc = _run_cli("build-order", str(tmp_path))
    assert proc.returncode == 0
    result = json.loads(proc.stdout)
    assert result == ["b.py.spec.md", "a.py.spec.md"]


def test_cli_deps_happy_path(tmp_path):
    (tmp_path / "a.py.spec.md").write_text("---\ndepends-on:\n  - b.py.spec.md\n---\n\n# a spec")
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
        "<!-- unslop-changes v1 -->\n### [pending] Add feature -- 2026-03-22T15:00:00Z\n\nAdd a feature.\n\n---\n"
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
        "<!-- unslop-changes v1 -->\n### [pending] Add feature -- 2026-03-22T15:00:00Z\n\nBody.\n\n---\n"
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
        "<!-- unslop-changes v1 -->\n### [pending] Add feature -- 2026-03-22T15:00:00Z\n\nBody.\n\n---\n"
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
    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"), project_root=str(tmp_path))
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
    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"), project_root=str(tmp_path))
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
    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"), project_root=str(tmp_path))
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
    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"), project_root=str(tmp_path))
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
    result = classify_file(str(tmp_path / "thing.py"), str(tmp_path / "thing.py.spec.md"), project_root=str(tmp_path))
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
        cwd=tmp_path,
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        },
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
    (upstream / "pool.py.impl.md").write_text(
        "---\nsource-spec: pool.py.spec.md\ntarget-language: python\nephemeral: false\n---\n\n## Strategy\nSync pool.\n"
    )

    # Create downstream concrete spec with dependency
    (tmp_path / "src" / "handler.py.impl.md").write_text(
        "---\nsource-spec: src/handler.py.spec.md\ntarget-language: python\nephemeral: false\n"
        "concrete-dependencies:\n  - src/core/pool.py.impl.md\n---\n\n## Strategy\nUses pool.\n"
    )

    h1 = compute_concrete_deps_hash(str(tmp_path / "src" / "handler.py.impl.md"), str(tmp_path))
    assert h1 is not None
    assert len(h1) == 12

    # Change upstream
    (upstream / "pool.py.impl.md").write_text(
        "---\nsource-spec: pool.py.spec.md\ntarget-language: python\nephemeral: false\n---\n\n## Strategy\nAsync pool.\n"
    )

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
    (tmp_path / "simple.py.impl.md").write_text("---\nsource-spec: simple.py.spec.md\ntarget-language: python\n---\n")
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
        "---\nsource-spec: core/pool.py.spec.md\ntarget-language: python\nephemeral: false\n---\n\n## Strategy\nSync pool.\n"
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
        "---\nsource-spec: core/pool.py.spec.md\ntarget-language: python\nephemeral: false\n---\n\n## Strategy\nAsync pool.\n"
    )

    result = check_freshness(str(tmp_path))
    handler_entry = [f for f in result["files"] if f["managed"] == "handler.py"]
    assert len(handler_entry) == 1
    assert handler_entry[0]["state"] == "fresh"


# --- multi-target discovery tests ---


def test_check_freshness_multi_target_discovery(tmp_path):
    """Multi-target impl spec should seed all target files into freshness check."""
    spec = "# auth spec\n\n## Behavior\nAuth logic.\nMore detail.\n"
    body_py = "def auth(): pass\n"
    body_ts = "export function auth() {}\n"
    sh = compute_hash(spec)
    oh_py = compute_hash(body_py)
    oh_ts = compute_hash(body_ts)

    # Abstract spec lives at src/auth_logic.spec.md
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "auth_logic.spec.md").write_text(spec)

    # Multi-target impl spec
    (src_dir / "auth_logic.impl.md").write_text(
        "---\nsource-spec: src/auth_logic.spec.md\nephemeral: false\n"
        "targets:\n"
        "  - path: src/api/auth.py\n"
        "    language: python\n"
        "  - path: frontend/src/api/auth.ts\n"
        "    language: typescript\n"
        "---\n\n## Strategy\nShared auth.\n"
    )

    # Write managed files at their target paths
    api_dir = src_dir / "api"
    api_dir.mkdir()
    (api_dir / "auth.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit src/auth_logic.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh_py} generated:2026-03-23T00:00:00Z\n" + body_py
    )

    fe_dir = tmp_path / "frontend" / "src" / "api"
    fe_dir.mkdir(parents=True)
    (fe_dir / "auth.ts").write_text(
        f"// @unslop-managed — do not edit directly. Edit src/auth_logic.spec.md instead.\n"
        f"// spec-hash:{sh} output-hash:{oh_ts} generated:2026-03-23T00:00:00Z\n" + body_ts
    )

    result = check_freshness(str(tmp_path))
    managed_paths = {f["managed"] for f in result["files"]}

    # Both target paths should appear in the freshness report
    assert "src/api/auth.py" in managed_paths
    assert "frontend/src/api/auth.ts" in managed_paths

    # Both should be fresh
    py_entry = [f for f in result["files"] if f["managed"] == "src/api/auth.py"]
    ts_entry = [f for f in result["files"] if f["managed"] == "frontend/src/api/auth.ts"]
    assert len(py_entry) == 1
    assert py_entry[0]["state"] == "fresh"
    assert len(ts_entry) == 1
    assert ts_entry[0]["state"] == "fresh"

    # No ghost entry for the deduced basename
    assert "src/auth_logic" not in managed_paths, (
        f"Ghost 'src/auth_logic' should be suppressed when targets[] exists, got: {managed_paths}"
    )


def test_check_freshness_multi_target_stale(tmp_path):
    """A missing target file should appear as stale."""
    spec = "# auth spec\n\n## Behavior\nAuth logic.\nMore detail.\n"

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "auth_logic.spec.md").write_text(spec)

    (src_dir / "auth_logic.impl.md").write_text(
        "---\nsource-spec: src/auth_logic.spec.md\nephemeral: false\n"
        "targets:\n"
        "  - path: src/api/auth.py\n"
        "    language: python\n"
        "  - path: frontend/src/api/auth.ts\n"
        "    language: typescript\n"
        "---\n\n## Strategy\nShared auth.\n"
    )

    # Neither target file exists
    result = check_freshness(str(tmp_path))
    target_entries = [f for f in result["files"] if f["managed"] in ("src/api/auth.py", "frontend/src/api/auth.ts")]
    assert len(target_entries) == 2
    for entry in target_entries:
        assert entry["state"] == "stale"


def test_check_freshness_target_collision(tmp_path):
    """Two impl specs claiming the same target should produce an error."""
    spec = "# shared spec\n\n## Behavior\nShared logic.\nMore detail.\n"

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "shared.spec.md").write_text(spec)

    # First impl claims src/api/handler.py
    (src_dir / "first.impl.md").write_text(
        "---\nsource-spec: src/shared.spec.md\nephemeral: false\n"
        "targets:\n"
        "  - path: src/api/handler.py\n"
        "    language: python\n"
        "---\n"
    )

    # Second impl also claims src/api/handler.py
    (src_dir / "second.impl.md").write_text(
        "---\nsource-spec: src/shared.spec.md\nephemeral: false\n"
        "targets:\n"
        "  - path: src/api/handler.py\n"
        "    language: python\n"
        "---\n"
    )

    result = check_freshness(str(tmp_path))
    collision_entries = [
        f
        for f in result["files"]
        if f["managed"] == "src/api/handler.py" and f["state"] == "error" and "collision" in f.get("hint", "").lower()
    ]
    assert len(collision_entries) >= 1
    assert "collision" in collision_entries[0]["hint"].lower()


# --- concrete dependency cycle detection tests ---


def test_build_concrete_order_no_cycle(tmp_path):
    """Linear concrete dependency chain should produce valid order."""
    (tmp_path / "a.py.impl.md").write_text("---\nsource-spec: a.py.spec.md\ntarget-language: python\nephemeral: false\n---\n")
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
    (tmp_path / "child.impl.md").write_text("---\nsource-spec: child.spec.md\ntarget-language: python\n---\n")
    chain = resolve_extends_chain("child.impl.md", str(tmp_path))
    assert chain == ["child.impl.md"]


def test_resolve_extends_chain_two_levels(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "base.impl.md").write_text("---\ntarget-language: python\n---\n\n## Pattern\n\n- **Concurrency**: async\n")
    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\ntarget-language: python\nextends: shared/base.impl.md\n---\n"
    )
    chain = resolve_extends_chain("child.impl.md", str(tmp_path))
    assert chain == ["child.impl.md", "shared/base.impl.md"]


def test_resolve_extends_chain_cycle_raises(tmp_path):
    import pytest

    (tmp_path / "a.impl.md").write_text("---\ntarget-language: python\nextends: b.impl.md\n---\n")
    (tmp_path / "b.impl.md").write_text("---\ntarget-language: python\nextends: a.impl.md\n---\n")
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
    (shared / "base.impl.md").write_text("---\ntarget-language: python\n---\n")
    (tmp_path / "child.impl.md").write_text("---\ntarget-language: python\nextends: shared/base.impl.md\n---\n")
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


# --- Inheritance-Aware Staleness Tests ---


def test_get_all_strategy_providers_deps_only():
    meta = {"concrete_dependencies": ["a.impl.md", "b.impl.md"]}
    assert get_all_strategy_providers(meta) == ["a.impl.md", "b.impl.md"]


def test_get_all_strategy_providers_extends_only():
    meta = {"extends": "base.impl.md"}
    assert get_all_strategy_providers(meta) == ["base.impl.md"]


def test_get_all_strategy_providers_both():
    meta = {
        "concrete_dependencies": ["dep.impl.md"],
        "extends": "base.impl.md",
    }
    result = get_all_strategy_providers(meta)
    assert "base.impl.md" in result
    assert "dep.impl.md" in result
    assert len(result) == 2


def test_get_all_strategy_providers_deduplicates():
    """If extends is also listed in concrete_dependencies, no duplicate."""
    meta = {
        "concrete_dependencies": ["base.impl.md"],
        "extends": "base.impl.md",
    }
    assert get_all_strategy_providers(meta) == ["base.impl.md"]


def test_get_all_strategy_providers_empty():
    assert get_all_strategy_providers({}) == []


def test_compute_concrete_deps_hash_includes_extends(tmp_path):
    """Hash should include the parent spec from extends."""
    # Create parent
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "base.impl.md").write_text(
        "---\nsource-spec: base.spec.md\ntarget-language: python\nephemeral: false\n---\n\n## Strategy\nBase v1.\n"
    )

    # Create child that extends parent (no concrete-dependencies)
    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\ntarget-language: python\nephemeral: false\n"
        "extends: shared/base.impl.md\n---\n\n## Strategy\nChild.\n"
    )

    h1 = compute_concrete_deps_hash(str(tmp_path / "child.impl.md"), str(tmp_path))
    assert h1 is not None, "extends-only spec should produce a hash"

    # Change parent
    (shared / "base.impl.md").write_text(
        "---\nsource-spec: base.spec.md\ntarget-language: python\nephemeral: false\n---\n\n## Strategy\nBase v2 with security headers.\n"
    )

    h2 = compute_concrete_deps_hash(str(tmp_path / "child.impl.md"), str(tmp_path))
    assert h2 != h1, "Hash should change when parent spec changes"


def test_compute_concrete_deps_hash_extends_and_deps(tmp_path):
    """Hash should incorporate both extends parent and concrete deps."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "base.impl.md").write_text(
        "---\nsource-spec: base.spec.md\ntarget-language: python\n---\n\n## Strategy\nBase.\n"
    )
    (tmp_path / "pool.impl.md").write_text(
        "---\nsource-spec: pool.spec.md\ntarget-language: python\n---\n\n## Strategy\nPool.\n"
    )

    # Child extends base and depends on pool
    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\ntarget-language: python\nephemeral: false\n"
        "extends: shared/base.impl.md\n"
        "concrete-dependencies:\n  - pool.impl.md\n---\n\n## Strategy\nChild.\n"
    )

    h1 = compute_concrete_deps_hash(str(tmp_path / "child.impl.md"), str(tmp_path))
    assert h1 is not None

    # Change the parent (not the dep) — hash should still change
    (shared / "base.impl.md").write_text(
        "---\nsource-spec: base.spec.md\ntarget-language: python\n---\n\n## Strategy\nBase v2.\n"
    )

    h2 = compute_concrete_deps_hash(str(tmp_path / "child.impl.md"), str(tmp_path))
    assert h2 != h1, "Changing parent should change the hash even when deps are untouched"


def test_check_freshness_ghost_stale_via_extends(tmp_path):
    """Changing a parent spec should make child ghost-stale via extends."""
    # Create parent concrete spec
    shared = tmp_path / "shared"
    shared.mkdir()
    parent_v1 = (
        "---\nsource-spec: shared/base.spec.md\ntarget-language: python\nephemeral: false\n---\n\n"
        "## Strategy\nBase strategy v1.\n"
    )
    (shared / "base.impl.md").write_text(parent_v1)

    # Create child spec.md and impl.md
    child_spec = "# Child\n\n## Behavior\nChild behavior.\nDetails here.\n"
    (tmp_path / "child.py.spec.md").write_text(child_spec)

    child_impl = (
        "---\nsource-spec: child.py.spec.md\ntarget-language: python\nephemeral: false\n"
        "extends: shared/base.impl.md\n---\n\n## Strategy\nChild strategy.\n"
    )
    (tmp_path / "child.py.impl.md").write_text(child_impl)

    # Compute hashes at "generation time"
    child_body = "def child(): pass\n"
    sh = compute_hash(child_spec)
    oh = compute_hash(child_body)
    cdh = compute_concrete_deps_hash(str(tmp_path / "child.py.impl.md"), str(tmp_path))

    # Write managed file with correct header format
    (tmp_path / "child.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit child.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} concrete-deps-hash:{cdh}"
        f" generated:2026-03-23T00:00:00Z\n" + child_body
    )

    # Verify it's fresh before parent changes
    result = check_freshness(str(tmp_path))
    child_entry = [f for f in result["files"] if f["managed"] == "child.py"]
    assert len(child_entry) == 1
    assert child_entry[0]["state"] == "fresh", f"Expected fresh, got: {child_entry[0]}"

    # Now change the parent spec (strategy shift)
    (shared / "base.impl.md").write_text(
        "---\nsource-spec: shared/base.spec.md\ntarget-language: python\nephemeral: false\n---\n\n"
        "## Strategy\nBase strategy v2 with security headers.\n"
    )

    # Child should now be ghost-stale because parent changed
    result = check_freshness(str(tmp_path))
    child_entry = [f for f in result["files"] if f["managed"] == "child.py"]
    assert len(child_entry) == 1
    assert child_entry[0]["state"] == "ghost-stale", f"Expected ghost-stale after parent change, got: {child_entry[0]}"


# --- Unit Spec Registry Key Tests ---


def test_get_registry_key_per_file_spec():
    assert get_registry_key_for_spec("handler.py.spec.md") == "handler.py"


def test_get_registry_key_per_file_spec_nested():
    assert get_registry_key_for_spec("src/api/handler.py.spec.md") == "src/api/handler.py"


def test_get_registry_key_unit_spec():
    """Unit spec registry key is the parent directory."""
    assert get_registry_key_for_spec("pkg/mod.unit.spec.md") == "pkg"


def test_get_registry_key_unit_spec_nested():
    assert get_registry_key_for_spec("src/utils/helpers.unit.spec.md") == "src/utils"


def test_get_registry_key_plain_string():
    """Non-spec path is returned unchanged."""
    assert get_registry_key_for_spec("handler.py") == "handler.py"


def test_check_freshness_ghost_stale_unit_spec(tmp_path):
    """Ghost-staleness should fire for unit specs via correct registry key."""
    # Create upstream concrete spec that will change
    (tmp_path / "base_math.impl.md").write_text(
        "---\nsource-spec: base_math.spec.md\ntarget-language: python\nephemeral: false\n---\n\n## Strategy\nMath utils v1.\n"
    )

    # Create the unit spec
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    unit_spec_content = "# Pkg Module\n\n## Behavior\nPackage utilities.\nDetails.\n\n## Files\n- `calc.py`\n- `utils.py`\n"
    (pkg / "mod.unit.spec.md").write_text(unit_spec_content)

    # Create unit impl that depends on base_math
    (pkg / "mod.unit.impl.md").write_text(
        "---\nsource-spec: pkg/mod.unit.spec.md\ntarget-language: python\nephemeral: false\n"
        "concrete-dependencies:\n  - base_math.impl.md\n---\n\n## Strategy\nUses base math.\n"
    )

    # Compute hashes at "generation time"
    calc_body = "def calc(): pass\n"
    utils_body = "def utils(): pass\n"
    sh = compute_hash(unit_spec_content)
    calc_oh = compute_hash(calc_body)
    utils_oh = compute_hash(utils_body)
    cdh = compute_concrete_deps_hash(str(pkg / "mod.unit.impl.md"), str(tmp_path))

    # Write managed files with headers
    (pkg / "calc.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit pkg/mod.unit.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{calc_oh} concrete-deps-hash:{cdh}"
        f" generated:2026-03-23T00:00:00Z\n" + calc_body
    )
    (pkg / "utils.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit pkg/mod.unit.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{utils_oh} concrete-deps-hash:{cdh}"
        f" generated:2026-03-23T00:00:00Z\n" + utils_body
    )

    # Verify fresh before upstream change
    result = check_freshness(str(tmp_path))
    pkg_entry = [f for f in result["files"] if f["managed"] == "pkg"]
    assert len(pkg_entry) == 1, f"Expected pkg entry, got: {[f['managed'] for f in result['files']]}"
    assert pkg_entry[0]["state"] == "fresh", f"Expected fresh, got: {pkg_entry[0]}"

    # Change upstream concrete spec
    (tmp_path / "base_math.impl.md").write_text(
        "---\nsource-spec: base_math.spec.md\ntarget-language: python\nephemeral: false\n---\n\n"
        "## Strategy\nMath utils v2 with overflow protection.\n"
    )

    # Unit spec should now be ghost-stale
    result = check_freshness(str(tmp_path))
    pkg_entry = [f for f in result["files"] if f["managed"] == "pkg"]
    assert len(pkg_entry) == 1
    assert pkg_entry[0]["state"] == "ghost-stale", f"Expected ghost-stale after upstream change, got: {pkg_entry[0]}"


# --- Target-Driven Suppression Tests ---


def test_target_suppresses_default_deduction(tmp_path):
    """When impl.md defines targets[], no ghost entry for the deduced basename."""
    spec = "# auth spec\n\n## Behavior\nAuth logic.\nMore detail.\n"
    body = "def auth(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)

    src = tmp_path / "src"
    src.mkdir()
    (src / "auth_logic.spec.md").write_text(spec)

    # impl explicitly targets src/api/auth.py
    (src / "auth_logic.impl.md").write_text(
        "---\nsource-spec: src/auth_logic.spec.md\nephemeral: false\n"
        "targets:\n  - path: src/api/auth.py\n    language: python\n"
        "---\n\n## Strategy\nShared auth.\n"
    )

    api = src / "api"
    api.mkdir()
    (api / "auth.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit src/auth_logic.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-23T00:00:00Z\n" + body
    )

    result = check_freshness(str(tmp_path))
    managed_set = {f["managed"] for f in result["files"]}

    # Target should appear
    assert "src/api/auth.py" in managed_set
    # Ghost "src/auth_logic" must NOT appear
    assert "src/auth_logic" not in managed_set, f"Ghost entry for deduced basename should be suppressed, got: {managed_set}"


def test_no_suppression_without_targets(tmp_path):
    """Without targets[] in impl.md, the default basename deduction still works."""
    spec = "# handler spec\n\n## Behavior\nHandle requests.\nMore detail.\n"
    body = "def handle(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)

    (tmp_path / "handler.py.spec.md").write_text(spec)
    (tmp_path / "handler.py.impl.md").write_text(
        "---\nsource-spec: handler.py.spec.md\nephemeral: false\n---\n\n## Strategy\nBasic handler.\n"
    )
    (tmp_path / "handler.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit handler.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-23T00:00:00Z\n" + body
    )

    result = check_freshness(str(tmp_path))
    managed_set = {f["managed"] for f in result["files"]}
    assert "handler.py" in managed_set

    handler = [f for f in result["files"] if f["managed"] == "handler.py"]
    assert handler[0]["state"] == "fresh"


def test_no_suppression_without_impl(tmp_path):
    """Without any impl.md companion, the default basename deduction still works."""
    spec = "# utils spec\n\n## Behavior\nUtility functions.\nMore detail.\n"
    body = "def util(): pass\n"
    sh = compute_hash(spec)
    oh = compute_hash(body)

    (tmp_path / "utils.py.spec.md").write_text(spec)
    (tmp_path / "utils.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit utils.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-23T00:00:00Z\n" + body
    )

    result = check_freshness(str(tmp_path))
    managed_set = {f["managed"] for f in result["files"]}
    assert "utils.py" in managed_set

    utils = [f for f in result["files"] if f["managed"] == "utils.py"]
    assert utils[0]["state"] == "fresh"


# --- Flatten Inheritance Chain Tests ---


def test_flatten_single_level(tmp_path):
    """Single impl with no extends produces a chain of 1."""
    (tmp_path / "handler.py.impl.md").write_text(
        "---\nsource-spec: handler.py.spec.md\nephemeral: false\n---\n\n"
        "## Strategy\nDirect handler.\n\n"
        "## Lowering Notes\n\n### Python\n- Use dataclass.\n"
    )

    result = flatten_inheritance_chain(
        str(tmp_path / "handler.py.impl.md"),
        str(tmp_path),
    )
    assert result["chain"] == ["handler.py.impl.md"]
    assert len(result["levels"]) == 1
    assert result["levels"][0]["impl"] == "handler.py.impl.md"
    assert "Strategy" in result["resolved"]
    assert "Lowering Notes" in result["resolved"]
    assert result["attribution"]["Strategy"] == "handler.py.impl.md"
    assert result["attribution"]["Lowering Notes"] == {"Python": "handler.py.impl.md"}


def test_flatten_two_level_inheritance(tmp_path):
    """Two-level chain shows which sections come from which level."""
    # Parent: base pattern with Python + Go lowering notes
    (tmp_path / "base.impl.md").write_text(
        "---\nsource-spec: base.spec.md\nephemeral: false\n---\n\n"
        "## Strategy\nBase strategy.\n\n"
        "## Lowering Notes\n\n"
        "### Python\n- Use threading.\n\n"
        "### Go\n- Use goroutines.\n"
    )

    # Child: extends base, overrides Python lowering notes
    (tmp_path / "child.py.impl.md").write_text(
        "---\nsource-spec: child.py.spec.md\nephemeral: false\n"
        "extends: base.impl.md\n---\n\n"
        "## Strategy\nChild strategy.\n\n"
        "## Lowering Notes\n\n"
        "### Python\n- Use asyncio instead of threading.\n"
    )

    result = flatten_inheritance_chain(
        str(tmp_path / "child.py.impl.md"),
        str(tmp_path),
    )

    # Chain: most general first
    assert result["chain"] == ["base.impl.md", "child.py.impl.md"]
    assert len(result["levels"]) == 2

    # Strategy: child wins (never inherited)
    assert "Child strategy." in result["resolved"]["Strategy"]
    assert result["attribution"]["Strategy"] == "child.py.impl.md"

    # Lowering Notes: Python from child, Go inherited from parent
    ln = result["attribution"]["Lowering Notes"]
    assert ln["Python"] == "child.py.impl.md"
    assert ln["Go"] == "base.impl.md"

    # Resolved content has both languages
    assert "asyncio" in result["resolved"]["Lowering Notes"]
    assert "goroutines" in result["resolved"]["Lowering Notes"]


def test_flatten_pattern_attribution(tmp_path):
    """Pattern section merging shows per-key attribution."""
    (tmp_path / "base.impl.md").write_text(
        "---\nsource-spec: base.spec.md\nephemeral: false\n---\n\n"
        "## Pattern\n- **Concurrency**: async cooperative\n"
        "- **DI pattern**: Annotated depends\n"
    )

    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\nephemeral: false\n"
        "extends: base.impl.md\n---\n\n"
        "## Pattern\n- **Concurrency**: threaded pool\n"
    )

    result = flatten_inheritance_chain(
        str(tmp_path / "child.impl.md"),
        str(tmp_path),
    )

    pat_attr = result["attribution"]["Pattern"]
    assert pat_attr["Concurrency"] == "child.impl.md"
    assert pat_attr["DI pattern"] == "base.impl.md"


def test_flatten_cli_output(tmp_path):
    """The --flatten flag in CLI output includes the flattened key."""
    (tmp_path / "simple.py.impl.md").write_text(
        "---\nsource-spec: simple.py.spec.md\nephemeral: false\n---\n\n## Strategy\nSimple.\n"
    )

    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "orchestrator",
            "concrete-deps",
            str(tmp_path / "simple.py.impl.md"),
            "--root",
            str(tmp_path),
            "--flatten",
        ],
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "unslop", "scripts"),
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "flattened" in data
    assert data["flattened"]["chain"] == ["simple.py.impl.md"]
    assert "Strategy" in data["flattened"]["resolved"]


def test_flatten_cli_without_flag(tmp_path):
    """Without --flatten, no flattened key in output."""
    (tmp_path / "simple.py.impl.md").write_text(
        "---\nsource-spec: simple.py.spec.md\nephemeral: false\n---\n\n## Strategy\nSimple.\n"
    )

    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "orchestrator", "concrete-deps", str(tmp_path / "simple.py.impl.md"), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "unslop", "scripts"),
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "flattened" not in data


# --- Deep Inheritance Staleness Tests ---


def test_deep_hash_changes_on_grandparent_edit(tmp_path):
    """Hash should change when a grandparent spec is modified."""
    # grand -> parent -> child
    (tmp_path / "grand.impl.md").write_text(
        "---\nsource-spec: grand.spec.md\nephemeral: false\n---\n\n## Strategy\nGlobal RETRY_PRECISION = 1ms.\n"
    )
    (tmp_path / "parent.impl.md").write_text(
        "---\nsource-spec: parent.spec.md\nephemeral: false\nextends: grand.impl.md\n---\n\n## Strategy\nParent retry logic.\n"
    )
    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\nephemeral: false\nextends: parent.impl.md\n---\n\n## Strategy\nChild handler.\n"
    )

    h1 = compute_concrete_deps_hash(str(tmp_path / "child.impl.md"), str(tmp_path))
    assert h1 is not None

    # Change grandparent
    (tmp_path / "grand.impl.md").write_text(
        "---\nsource-spec: grand.spec.md\nephemeral: false\n---\n\n## Strategy\nGlobal RETRY_PRECISION = 5ms.\n"
    )

    h2 = compute_concrete_deps_hash(str(tmp_path / "child.impl.md"), str(tmp_path))
    assert h2 is not None
    assert h1 != h2, "Hash should change when grandparent strategy changes"


def test_deep_hash_changes_on_transitive_dep(tmp_path):
    """Hash should change when a dependency's dependency changes."""
    # base_math -> pool (dep) -> handler (dep)
    (tmp_path / "base_math.impl.md").write_text(
        "---\nsource-spec: base_math.spec.md\nephemeral: false\n---\n\n## Strategy\nMath utils v1.\n"
    )
    (tmp_path / "pool.impl.md").write_text(
        "---\nsource-spec: pool.spec.md\nephemeral: false\n"
        "concrete-dependencies:\n  - base_math.impl.md\n---\n\n"
        "## Strategy\nPool using math.\n"
    )
    (tmp_path / "handler.impl.md").write_text(
        "---\nsource-spec: handler.spec.md\nephemeral: false\n"
        "concrete-dependencies:\n  - pool.impl.md\n---\n\n"
        "## Strategy\nHandler using pool.\n"
    )

    h1 = compute_concrete_deps_hash(str(tmp_path / "handler.impl.md"), str(tmp_path))

    # Change the transitive dependency
    (tmp_path / "base_math.impl.md").write_text(
        "---\nsource-spec: base_math.spec.md\nephemeral: false\n---\n\n## Strategy\nMath utils v2 with overflow protection.\n"
    )

    h2 = compute_concrete_deps_hash(str(tmp_path / "handler.impl.md"), str(tmp_path))
    assert h1 != h2, "Hash should change when transitive dep changes"


def test_deep_hash_stable_without_changes(tmp_path):
    """Hash should be stable when nothing changes."""
    (tmp_path / "grand.impl.md").write_text("---\nsource-spec: grand.spec.md\nephemeral: false\n---\n\n## Strategy\nGrand.\n")
    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\nephemeral: false\nextends: grand.impl.md\n---\n\n## Strategy\nChild.\n"
    )

    h1 = compute_concrete_deps_hash(str(tmp_path / "child.impl.md"), str(tmp_path))
    h2 = compute_concrete_deps_hash(str(tmp_path / "child.impl.md"), str(tmp_path))
    assert h1 == h2


def test_deep_hash_handles_cycle(tmp_path):
    """Recursive hashing should not infinite-loop on cycles."""
    (tmp_path / "a.impl.md").write_text(
        "---\nsource-spec: a.spec.md\nephemeral: false\nconcrete-dependencies:\n  - b.impl.md\n---\n\n## Strategy\nA.\n"
    )
    (tmp_path / "b.impl.md").write_text(
        "---\nsource-spec: b.spec.md\nephemeral: false\nconcrete-dependencies:\n  - a.impl.md\n---\n\n## Strategy\nB.\n"
    )

    # Should not hang — seen set prevents re-visiting
    h = compute_concrete_deps_hash(str(tmp_path / "a.impl.md"), str(tmp_path))
    assert h is not None


def test_check_freshness_deep_ghost_stale(tmp_path):
    """Integration: grandparent change should ghost-stale the child managed file."""
    # grand -> parent (extends) -> child (extends)
    (tmp_path / "grand.impl.md").write_text(
        "---\nsource-spec: grand.spec.md\nephemeral: false\n---\n\n## Strategy\nGrand strategy v1.\n"
    )
    (tmp_path / "parent.py.impl.md").write_text(
        "---\nsource-spec: parent.py.spec.md\nephemeral: false\nextends: grand.impl.md\n---\n\n## Strategy\nParent strategy.\n"
    )
    (tmp_path / "child.py.impl.md").write_text(
        "---\nsource-spec: child.py.spec.md\nephemeral: false\n"
        "extends: parent.py.impl.md\n---\n\n"
        "## Strategy\nChild strategy.\n"
    )

    # Spec files
    spec = "# Spec\n\n## Behavior\nDo things.\nMore detail.\n"
    (tmp_path / "parent.py.spec.md").write_text(spec)
    (tmp_path / "child.py.spec.md").write_text(spec)

    sh = compute_hash(spec)
    parent_body = "def parent(): pass\n"
    child_body = "def child(): pass\n"
    parent_oh = compute_hash(parent_body)
    child_oh = compute_hash(child_body)

    parent_cdh = compute_concrete_deps_hash(str(tmp_path / "parent.py.impl.md"), str(tmp_path))
    child_cdh = compute_concrete_deps_hash(str(tmp_path / "child.py.impl.md"), str(tmp_path))

    (tmp_path / "parent.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit parent.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{parent_oh} concrete-deps-hash:{parent_cdh}"
        f" generated:2026-03-23T00:00:00Z\n" + parent_body
    )
    (tmp_path / "child.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit child.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{child_oh} concrete-deps-hash:{child_cdh}"
        f" generated:2026-03-23T00:00:00Z\n" + child_body
    )

    # Verify fresh
    result = check_freshness(str(tmp_path))
    child_entry = [f for f in result["files"] if f["managed"] == "child.py"]
    assert len(child_entry) == 1
    assert child_entry[0]["state"] == "fresh"

    # Change grandparent
    (tmp_path / "grand.impl.md").write_text(
        "---\nsource-spec: grand.spec.md\nephemeral: false\n---\n\n## Strategy\nGrand strategy v2 — changed precision.\n"
    )

    # Both parent and child should be ghost-stale
    result = check_freshness(str(tmp_path))
    child_entry = [f for f in result["files"] if f["managed"] == "child.py"]
    parent_entry = [f for f in result["files"] if f["managed"] == "parent.py"]
    assert len(child_entry) == 1
    assert child_entry[0]["state"] == "ghost-stale", (
        f"Expected ghost-stale for child after grandparent change, got: {child_entry[0]}"
    )
    assert len(parent_entry) == 1
    assert parent_entry[0]["state"] == "ghost-stale", (
        f"Expected ghost-stale for parent after grandparent change, got: {parent_entry[0]}"
    )


# --- strict child-only inheritance tests ---


def test_strict_child_only_strategy_purged_when_child_omits(tmp_path):
    """A child that omits ## Strategy should NOT inherit parent's strategy."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "base.impl.md").write_text(
        "---\ntarget-language: python\n---\n\n"
        "## Strategy\n\nParent generic fetch strategy.\n\n"
        "## Pattern\n\n- **Concurrency**: async\n\n"
        "## Lowering Notes\n\n### Python\n- Use asyncio\n"
    )
    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\ntarget-language: python\n"
        "extends: shared/base.impl.md\n---\n\n"
        "## Pattern\n\n- **Error handling**: typed errors\n"
    )
    sections = resolve_inherited_sections("child.impl.md", str(tmp_path))
    # Strategy must NOT be present — it was purged from parent and child didn't define one
    assert "Strategy" not in sections
    # Pattern should be merged
    assert "Pattern" in sections
    assert "Concurrency" in sections["Pattern"]
    assert "Error handling" in sections["Pattern"]
    # Lowering Notes should be inherited
    assert "Lowering Notes" in sections
    assert "asyncio" in sections["Lowering Notes"]


def test_strict_child_only_type_sketch_purged_when_child_omits(tmp_path):
    """A child that omits ## Type Sketch should NOT inherit parent's type sketch."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "base.impl.md").write_text(
        "---\ntarget-language: python\n---\n\n"
        "## Type Sketch\n\nBaseConfig { timeout: int }\n\n"
        "## Pattern\n\n- **DI pattern**: Depends()\n"
    )
    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\ntarget-language: python\n"
        "extends: shared/base.impl.md\n---\n\n"
        "## Strategy\n\nChild algorithm here.\n"
    )
    sections = resolve_inherited_sections("child.impl.md", str(tmp_path))
    assert "Type Sketch" not in sections
    assert "Strategy" in sections
    assert "Child algorithm" in sections["Strategy"]
    assert "Pattern" in sections


def test_strict_child_only_constant_has_expected_sections():
    """Verify the STRICT_CHILD_ONLY set contains the right sections."""
    assert "Strategy" in STRICT_CHILD_ONLY
    assert "Type Sketch" in STRICT_CHILD_ONLY
    assert "Pattern" not in STRICT_CHILD_ONLY
    assert "Lowering Notes" not in STRICT_CHILD_ONLY


def test_strict_child_only_three_level_chain_purges_grandparent(tmp_path):
    """In a 3-level chain, grandparent Strategy must not leak to grandchild."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "grandparent.impl.md").write_text(
        "---\ntarget-language: python\n---\n\n"
        "## Strategy\n\nGrandparent strategy — must NOT leak.\n\n"
        "## Pattern\n\n- **Base**: grandparent pattern\n\n"
        "## Lowering Notes\n\n### Python\n- grandparent note\n"
    )
    (shared / "parent.impl.md").write_text(
        "---\ntarget-language: python\nextends: shared/grandparent.impl.md\n---\n\n"
        "## Strategy\n\nParent strategy — also must NOT leak to child.\n\n"
        "## Pattern\n\n- **Middle**: parent pattern\n"
    )
    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\ntarget-language: python\n"
        "extends: shared/parent.impl.md\n---\n\n"
        "## Strategy\n\nChild's own unique strategy.\n"
    )
    sections = resolve_inherited_sections("child.impl.md", str(tmp_path))
    assert "Child's own unique strategy" in sections["Strategy"]
    assert "Grandparent strategy" not in sections.get("Strategy", "")
    assert "Parent strategy" not in sections.get("Strategy", "")
    # Pattern should merge from grandparent + parent
    assert "Base" in sections["Pattern"]
    assert "Middle" in sections["Pattern"]
    # Lowering Notes inherited from grandparent
    assert "grandparent note" in sections["Lowering Notes"]


def test_strict_child_only_no_inheritance_returns_own_sections(tmp_path):
    """A spec with no extends should return its own sections unchanged."""
    (tmp_path / "standalone.impl.md").write_text(
        "---\nsource-spec: standalone.spec.md\ntarget-language: python\n---\n\n"
        "## Strategy\n\nStandalone algorithm.\n\n"
        "## Type Sketch\n\nFoo { x: int }\n"
    )
    sections = resolve_inherited_sections("standalone.impl.md", str(tmp_path))
    assert "Strategy" in sections
    assert "Standalone algorithm" in sections["Strategy"]
    assert "Type Sketch" in sections
    assert "Foo" in sections["Type Sketch"]


def test_strict_child_only_child_defines_both_strict_sections(tmp_path):
    """If child defines Strategy and Type Sketch, those should appear (not parent's)."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "base.impl.md").write_text(
        "---\ntarget-language: python\n---\n\n"
        "## Strategy\n\nParent strategy.\n\n"
        "## Type Sketch\n\nParentType { a: int }\n"
    )
    (tmp_path / "child.impl.md").write_text(
        "---\nsource-spec: child.spec.md\ntarget-language: python\n"
        "extends: shared/base.impl.md\n---\n\n"
        "## Strategy\n\nChild strategy.\n\n"
        "## Type Sketch\n\nChildType { b: string }\n"
    )
    sections = resolve_inherited_sections("child.impl.md", str(tmp_path))
    assert "Child strategy" in sections["Strategy"]
    assert "Parent strategy" not in sections["Strategy"]
    assert "ChildType" in sections["Type Sketch"]
    assert "ParentType" not in sections["Type Sketch"]


# --- ripple-check tests ---


def _make_managed_file(path, spec_path, body="pass"):
    """Helper to create a managed file with proper header."""
    from orchestrator import compute_hash

    spec_content = path.parent.parent / spec_path if not isinstance(spec_path, str) else spec_path
    # Read the actual spec to compute hash
    spec_file = path.parent / spec_path if "/" not in str(spec_path) else path.parent.parent / spec_path
    # We'll compute hashes from content
    spec_hash = compute_hash(spec_file.read_text() if spec_file.exists() else "")
    output_hash = compute_hash(body)
    header = (
        f"# @unslop-managed — do not edit directly. Edit {spec_path} instead.\n"
        f"# spec-hash:{spec_hash} output-hash:{output_hash} generated:2026-03-23T00:00:00Z\n\n"
    )
    path.write_text(header + body)


def test_ripple_check_single_spec_no_deps(tmp_path):
    """Ripple check on a spec with no dependents should show only itself."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "retry.py.spec.md").write_text("# Retry Spec\n\nRetry with backoff.\n")
    (tmp_path / "src" / "retry.py").write_text("# no header\ndef retry(): pass\n")

    result = ripple_check(["src/retry.py.spec.md"], str(tmp_path))
    assert result["layers"]["abstract"]["total"] == 1
    assert "src/retry.py.spec.md" in result["layers"]["abstract"]["directly_changed"]
    assert len(result["layers"]["abstract"]["transitively_affected"]) == 0
    assert result["layers"]["code"]["total_files"] == 1
    assert result["layers"]["code"]["regenerate"][0]["managed"] == "src/retry.py"


def test_ripple_check_transitive_deps(tmp_path):
    """Changing a spec should show transitively affected dependents."""
    (tmp_path / "src").mkdir()
    # A -> B -> C (C depends on B, B depends on A)
    (tmp_path / "src" / "a.py.spec.md").write_text("# A Spec\n")
    (tmp_path / "src" / "b.py.spec.md").write_text(
        "---\ndepends-on:\n  - src/a.py.spec.md\n---\n# B Spec\n"
    )
    (tmp_path / "src" / "c.py.spec.md").write_text(
        "---\ndepends-on:\n  - src/b.py.spec.md\n---\n# C Spec\n"
    )

    result = ripple_check(["src/a.py.spec.md"], str(tmp_path))
    assert result["layers"]["abstract"]["total"] == 3
    assert "src/a.py.spec.md" in result["layers"]["abstract"]["directly_changed"]
    transitives = result["layers"]["abstract"]["transitively_affected"]
    assert "src/b.py.spec.md" in transitives
    assert "src/c.py.spec.md" in transitives
    assert result["layers"]["code"]["total_files"] == 3


def test_ripple_check_concrete_deps_ghost_stale(tmp_path):
    """Concrete dependency changes should show ghost-stale files."""
    (tmp_path / "src").mkdir()
    # Two specs, each with its own impl.md
    (tmp_path / "src" / "pool.py.spec.md").write_text("# Pool Spec\n")
    (tmp_path / "src" / "pool.py.impl.md").write_text(
        "---\nsource-spec: src/pool.py.spec.md\ntarget-language: python\nephemeral: false\n---\n\n"
        "## Strategy\n\nPool strategy.\n"
    )
    (tmp_path / "src" / "handler.py.spec.md").write_text("# Handler Spec\n")
    (tmp_path / "src" / "handler.py.impl.md").write_text(
        "---\nsource-spec: src/handler.py.spec.md\ntarget-language: python\n"
        "ephemeral: false\nconcrete-dependencies:\n  - src/pool.py.impl.md\n---\n\n"
        "## Strategy\n\nHandler strategy.\n"
    )

    # Change pool spec — handler's concrete spec depends on pool's concrete spec
    result = ripple_check(["src/pool.py.spec.md"], str(tmp_path))

    # pool is directly changed, handler is ghost-stale via concrete deps
    assert "src/pool.py.spec.md" in result["layers"]["abstract"]["directly_changed"]
    assert result["layers"]["concrete"]["total"] >= 1
    assert "src/pool.py.impl.md" in result["layers"]["concrete"]["affected_impls"]


def test_ripple_check_build_order(tmp_path):
    """Build order should respect dependency ordering."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "base.py.spec.md").write_text("# Base\n")
    (tmp_path / "src" / "mid.py.spec.md").write_text(
        "---\ndepends-on:\n  - src/base.py.spec.md\n---\n# Mid\n"
    )
    (tmp_path / "src" / "top.py.spec.md").write_text(
        "---\ndepends-on:\n  - src/mid.py.spec.md\n---\n# Top\n"
    )

    result = ripple_check(["src/base.py.spec.md"], str(tmp_path))
    order = result["build_order"]
    base_idx = order.index("src/base.py.spec.md")
    mid_idx = order.index("src/mid.py.spec.md")
    top_idx = order.index("src/top.py.spec.md")
    assert base_idx < mid_idx < top_idx


def test_ripple_check_multiple_input_specs(tmp_path):
    """Multiple input specs should union their ripple effects."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py.spec.md").write_text("# A\n")
    (tmp_path / "src" / "b.py.spec.md").write_text("# B\n")
    (tmp_path / "src" / "c.py.spec.md").write_text(
        "---\ndepends-on:\n  - src/a.py.spec.md\n---\n# C\n"
    )

    result = ripple_check(["src/a.py.spec.md", "src/b.py.spec.md"], str(tmp_path))
    assert result["layers"]["abstract"]["total"] == 3  # a, b, c
    assert len(result["layers"]["abstract"]["directly_changed"]) == 2
    assert "src/c.py.spec.md" in result["layers"]["abstract"]["transitively_affected"]


# --- concrete-manifest tests ---


def test_parse_header_with_concrete_manifest():
    lines = [
        "# @unslop-managed — do not edit directly. Edit src/handler.py.spec.md instead.",
        "# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 generated:2026-03-23T00:00:00Z",
        "# concrete-manifest:src/core/pool.py.impl.md:7f2e1b8a9c04,shared/base.impl.md:b3d5a1f8e290",
    ]
    result = parse_header("\n".join(lines))
    assert result is not None
    assert result["concrete_manifest"] == {
        "src/core/pool.py.impl.md": "7f2e1b8a9c04",
        "shared/base.impl.md": "b3d5a1f8e290",
    }
    # Legacy field should be None since we used manifest
    assert result["concrete_deps_hash"] is None


def test_parse_header_with_both_manifest_and_legacy():
    """If both manifest and legacy hash are present, both should be parsed."""
    lines = [
        "# @unslop-managed — do not edit directly. Edit src/handler.py.spec.md instead.",
        "# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 concrete-deps-hash:9c04b8e7f2a1 generated:2026-03-23T00:00:00Z",
        "# concrete-manifest:pool.impl.md:7f2e1b8a9c04",
    ]
    result = parse_header("\n".join(lines))
    assert result["concrete_manifest"] == {"pool.impl.md": "7f2e1b8a9c04"}
    assert result["concrete_deps_hash"] == "9c04b8e7f2a1"


def test_parse_header_without_manifest():
    """Files without manifest should have concrete_manifest=None."""
    lines = [
        "# @unslop-managed — do not edit directly. Edit src/retry.py.spec.md instead.",
        "# spec-hash:a3f8c2e9b7d1 output-hash:4e2f1a8c9b03 generated:2026-03-23T00:00:00Z",
    ]
    result = parse_header("\n".join(lines))
    assert result["concrete_manifest"] is None


def test_compute_concrete_manifest_basic(tmp_path):
    """Manifest should contain direct deps with their hashes."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "pool.py.impl.md").write_text(
        "---\nsource-spec: src/pool.py.spec.md\ntarget-language: python\nephemeral: false\n---\n\n"
        "## Strategy\n\nPool strategy.\n"
    )
    (tmp_path / "src" / "handler.py.impl.md").write_text(
        "---\nsource-spec: src/handler.py.spec.md\ntarget-language: python\n"
        "ephemeral: false\nconcrete-dependencies:\n  - src/pool.py.impl.md\n---\n\n"
        "## Strategy\n\nHandler strategy.\n"
    )

    manifest = compute_concrete_manifest(str(tmp_path / "src" / "handler.py.impl.md"), str(tmp_path))
    assert manifest is not None
    assert "src/pool.py.impl.md" in manifest
    # Hash should be the hash of pool.impl.md content
    pool_content = (tmp_path / "src" / "pool.py.impl.md").read_text()
    assert manifest["src/pool.py.impl.md"] == compute_hash(pool_content)


def test_compute_concrete_manifest_no_deps(tmp_path):
    """Impl with no deps should return None."""
    (tmp_path / "simple.impl.md").write_text(
        "---\nsource-spec: simple.spec.md\ntarget-language: python\n---\n"
    )
    manifest = compute_concrete_manifest(str(tmp_path / "simple.impl.md"), str(tmp_path))
    assert manifest is None


def test_format_manifest_header():
    """Manifest should format as comma-separated path:hash pairs."""
    manifest = {
        "src/pool.impl.md": "a3f8c2e9b7d1",
        "shared/base.impl.md": "7f2e1b8a9c04",
    }
    result = format_manifest_header(manifest)
    assert "shared/base.impl.md:7f2e1b8a9c04" in result
    assert "src/pool.impl.md:a3f8c2e9b7d1" in result
    assert "," in result


def test_format_manifest_roundtrip():
    """format → parse → should yield the same manifest."""
    manifest = {
        "src/pool.impl.md": "a3f8c2e9b7d1",
        "shared/base.impl.md": "7f2e1b8a9c04",
    }
    header_str = format_manifest_header(manifest)
    # Simulate writing to header
    full_header = (
        "# @unslop-managed — do not edit directly. Edit src/handler.py.spec.md instead.\n"
        "# spec-hash:000000000000 output-hash:111111111111 generated:2026-03-23T00:00:00Z\n"
        f"# concrete-manifest:{header_str}\n"
    )
    parsed = parse_header(full_header)
    assert parsed["concrete_manifest"] == manifest


def test_diagnose_ghost_staleness_detects_change(tmp_path):
    """Changed dep should be detected by comparing manifest hash vs current."""
    (tmp_path / "pool.impl.md").write_text("## Strategy\n\nPool v2 — changed.\n")
    manifest = {"pool.impl.md": "000000000000"}  # Stale hash (doesn't match v2)
    diagnostics = diagnose_ghost_staleness(manifest, str(tmp_path))
    assert len(diagnostics) == 1
    assert diagnostics[0]["dep"] == "pool.impl.md"
    assert diagnostics[0]["reason"] == "changed"


def test_diagnose_ghost_staleness_fresh(tmp_path):
    """Fresh dep should produce no diagnostics."""
    content = "## Strategy\n\nPool strategy.\n"
    (tmp_path / "pool.impl.md").write_text(content)
    manifest = {"pool.impl.md": compute_hash(content)}
    diagnostics = diagnose_ghost_staleness(manifest, str(tmp_path))
    assert len(diagnostics) == 0


def test_diagnose_ghost_staleness_missing_dep(tmp_path):
    """Missing dep should be reported."""
    manifest = {"nonexistent.impl.md": "a3f8c2e9b7d1"}
    diagnostics = diagnose_ghost_staleness(manifest, str(tmp_path))
    assert len(diagnostics) == 1
    assert diagnostics[0]["reason"] == "not found"


def test_format_ghost_diagnostic_deep_chain(tmp_path):
    """Deep chain should be reported as 'upstream X changed (via Y)'."""
    # Build: handler -> service -> utils
    (tmp_path / "utils.impl.md").write_text(
        "---\nsource-spec: utils.spec.md\ntarget-language: python\nephemeral: false\n---\n\n"
        "## Strategy\n\nUtils strategy v2 — CHANGED.\n"
    )
    (tmp_path / "service.impl.md").write_text(
        "---\nsource-spec: service.spec.md\ntarget-language: python\n"
        "ephemeral: false\nconcrete-dependencies:\n  - utils.impl.md\n---\n\n"
        "## Strategy\n\nService strategy.\n"
    )
    # handler's manifest stored old hash for service.impl.md
    manifest = {"service.impl.md": "000000000000"}
    diagnostics = diagnose_ghost_staleness(manifest, str(tmp_path))
    assert len(diagnostics) == 1
    reasons = format_ghost_diagnostic(diagnostics)
    assert len(reasons) == 1
    # Should report the chain: service changed, with upstream utils
    assert "service.impl.md" in reasons[0]
    assert "via" in reasons[0]
    assert "utils.impl.md" in reasons[0]


def test_check_freshness_with_manifest_surgical(tmp_path):
    """check_freshness should use manifest for surgical ghost detection."""
    # Setup: handler depends on pool (concrete dep)
    spec_content = "# Handler Spec\n"
    pool_content_v1 = (
        "---\nsource-spec: pool.py.spec.md\ntarget-language: python\nephemeral: false\n---\n\n"
        "## Strategy\n\nPool strategy v1.\n"
    )
    handler_impl_content = (
        "---\nsource-spec: handler.py.spec.md\ntarget-language: python\n"
        "ephemeral: false\nconcrete-dependencies:\n  - pool.py.impl.md\n---\n\n"
        "## Strategy\n\nHandler strategy.\n"
    )

    (tmp_path / "handler.py.spec.md").write_text(spec_content)
    (tmp_path / "pool.py.spec.md").write_text("# Pool Spec\n")
    (tmp_path / "pool.py.impl.md").write_text(pool_content_v1)
    (tmp_path / "handler.py.impl.md").write_text(handler_impl_content)

    # Compute hashes at "generation time"
    sh = compute_hash(spec_content)
    body = "def handler(): pass"
    oh = compute_hash(body)
    pool_hash = compute_hash(pool_content_v1)
    manifest_str = f"pool.py.impl.md:{pool_hash}"

    # Write managed file with concrete-manifest
    (tmp_path / "handler.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit handler.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-23T00:00:00Z\n"
        f"# concrete-manifest:{manifest_str}\n\n"
        f"{body}"
    )
    # Write pool managed file (not ghost-checked, just needs to exist for freshness)
    pool_sh = compute_hash("# Pool Spec\n")
    pool_body = "def pool(): pass"
    pool_oh = compute_hash(pool_body)
    (tmp_path / "pool.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit pool.py.spec.md instead.\n"
        f"# spec-hash:{pool_sh} output-hash:{pool_oh} generated:2026-03-23T00:00:00Z\n\n"
        f"{pool_body}"
    )

    # Before change: should be fresh
    result = check_freshness(str(tmp_path))
    handler_entry = [f for f in result["files"] if f["managed"] == "handler.py"]
    assert len(handler_entry) == 1
    assert handler_entry[0]["state"] == "fresh"

    # Change pool.py.impl.md
    (tmp_path / "pool.py.impl.md").write_text(
        "---\nsource-spec: pool.py.spec.md\ntarget-language: python\nephemeral: false\n---\n\n"
        "## Strategy\n\nPool strategy v2 — CHANGED to async.\n"
    )

    # After change: handler should be ghost-stale with surgical diagnostic
    result = check_freshness(str(tmp_path))
    handler_entry = [f for f in result["files"] if f["managed"] == "handler.py"]
    assert len(handler_entry) == 1
    assert handler_entry[0]["state"] == "ghost-stale"
    hint = handler_entry[0].get("hint", "")
    assert "pool.py.impl.md" in hint
    # Should NOT mention any other deps (surgical, not blanket)


def test_check_freshness_legacy_concrete_deps_hash_still_works(tmp_path):
    """Files with old concrete-deps-hash should still detect ghost staleness."""
    spec_content = "# Handler Spec\n"
    pool_content_v1 = (
        "---\nsource-spec: pool.py.spec.md\ntarget-language: python\nephemeral: false\n---\n\n"
        "## Strategy\n\nPool strategy v1.\n"
    )
    handler_impl_content = (
        "---\nsource-spec: handler.py.spec.md\ntarget-language: python\n"
        "ephemeral: false\nconcrete-dependencies:\n  - pool.py.impl.md\n---\n\n"
        "## Strategy\n\nHandler strategy.\n"
    )

    (tmp_path / "handler.py.spec.md").write_text(spec_content)
    (tmp_path / "pool.py.spec.md").write_text("# Pool Spec\n")
    (tmp_path / "pool.py.impl.md").write_text(pool_content_v1)
    (tmp_path / "handler.py.impl.md").write_text(handler_impl_content)

    sh = compute_hash(spec_content)
    body = "def handler(): pass"
    oh = compute_hash(body)
    cdh = compute_concrete_deps_hash(str(tmp_path / "handler.py.impl.md"), str(tmp_path))

    # Write managed file with LEGACY concrete-deps-hash (no manifest)
    (tmp_path / "handler.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit handler.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} concrete-deps-hash:{cdh} generated:2026-03-23T00:00:00Z\n\n"
        f"{body}"
    )
    pool_sh = compute_hash("# Pool Spec\n")
    pool_body = "def pool(): pass"
    pool_oh = compute_hash(pool_body)
    (tmp_path / "pool.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit pool.py.spec.md instead.\n"
        f"# spec-hash:{pool_sh} output-hash:{pool_oh} generated:2026-03-23T00:00:00Z\n\n"
        f"{pool_body}"
    )

    # Change pool
    (tmp_path / "pool.py.impl.md").write_text(
        "---\nsource-spec: pool.py.spec.md\ntarget-language: python\nephemeral: false\n---\n\n"
        "## Strategy\n\nPool strategy v2.\n"
    )

    result = check_freshness(str(tmp_path))
    handler_entry = [f for f in result["files"] if f["managed"] == "handler.py"]
    assert len(handler_entry) == 1
    assert handler_entry[0]["state"] == "ghost-stale"


# --- render_dependency_graph tests ---


def test_graph_basic_structure(tmp_path):
    """Graph should contain Mermaid header and spec nodes."""
    (tmp_path / ".unslop").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "retry.py.spec.md").write_text("# Retry Spec\n")

    result = render_dependency_graph(str(tmp_path))
    assert "graph TD" in result["mermaid"]
    assert result["stats"]["abstract_specs"] == 1
    assert "retry" in result["mermaid"].lower()


def test_graph_includes_deps_edges(tmp_path):
    """Abstract depends-on should produce edges."""
    (tmp_path / ".unslop").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py.spec.md").write_text("# A\n")
    (tmp_path / "src" / "b.py.spec.md").write_text(
        "---\ndepends-on:\n  - src/a.py.spec.md\n---\n# B\n"
    )

    result = render_dependency_graph(str(tmp_path))
    mermaid = result["mermaid"]
    # Should have an edge from a to b
    assert "-->" in mermaid
    assert result["stats"]["abstract_specs"] == 2


def test_graph_includes_concrete_specs(tmp_path):
    """Concrete specs should appear as nodes with extends edges."""
    (tmp_path / ".unslop").mkdir()
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "base.impl.md").write_text(
        "---\ntarget-language: python\nephemeral: false\n---\n\n## Pattern\n\n- **DI**: Depends()\n"
    )
    (tmp_path / "handler.py.spec.md").write_text("# Handler\n")
    (tmp_path / "handler.py.impl.md").write_text(
        "---\nsource-spec: handler.py.spec.md\ntarget-language: python\n"
        "ephemeral: false\nextends: shared/base.impl.md\n---\n\n"
        "## Strategy\n\nHandler strategy.\n"
    )

    result = render_dependency_graph(str(tmp_path))
    mermaid = result["mermaid"]
    assert "extends" in mermaid
    assert result["stats"]["concrete_specs"] == 2


def test_graph_no_code_flag(tmp_path):
    """--no-code should omit managed code file nodes."""
    (tmp_path / ".unslop").mkdir()
    (tmp_path / "retry.py.spec.md").write_text("# Retry\n")

    with_code = render_dependency_graph(str(tmp_path), include_code=True)
    without_code = render_dependency_graph(str(tmp_path), include_code=False)

    assert with_code["stats"]["managed_files"] >= 1
    assert without_code["stats"]["managed_files"] == 0
    assert "generates" not in without_code["mermaid"]


def test_graph_scope_filter(tmp_path):
    """Scoped graph should only include related specs."""
    (tmp_path / ".unslop").mkdir()
    (tmp_path / "a.py.spec.md").write_text("# A\n")
    (tmp_path / "b.py.spec.md").write_text(
        "---\ndepends-on:\n  - a.py.spec.md\n---\n# B\n"
    )
    (tmp_path / "c.py.spec.md").write_text("# C — unrelated\n")

    result = render_dependency_graph(str(tmp_path), scope=["a.py.spec.md"])
    # Should include a and b (b depends on a), but not c
    assert result["stats"]["abstract_specs"] == 2
    node_paths = [n["path"] for n in result["nodes"] if n["layer"] == "abstract"]
    assert "a.py.spec.md" in node_paths
    assert "b.py.spec.md" in node_paths
    assert "c.py.spec.md" not in node_paths


def test_graph_staleness_coloring(tmp_path):
    """Managed files should get CSS classes based on staleness state."""
    (tmp_path / ".unslop").mkdir()
    spec_content = "# Retry\n"
    (tmp_path / "retry.py.spec.md").write_text(spec_content)
    sh = compute_hash(spec_content)
    body = "def retry(): pass"
    oh = compute_hash(body)
    (tmp_path / "retry.py").write_text(
        f"# @unslop-managed — do not edit directly. Edit retry.py.spec.md instead.\n"
        f"# spec-hash:{sh} output-hash:{oh} generated:2026-03-23T00:00:00Z\n\n"
        f"{body}"
    )

    result = render_dependency_graph(str(tmp_path))
    # Should have a code node with fresh state
    code_nodes = [n for n in result["nodes"] if n["layer"] == "code"]
    assert len(code_nodes) == 1
    assert code_nodes[0]["state"] == "fresh"
    assert "class" in result["mermaid"]
    assert "fresh" in result["mermaid"]
