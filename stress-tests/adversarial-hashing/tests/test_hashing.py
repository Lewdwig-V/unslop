# @unslop-managed -- Edit hashing.py.spec.md instead
"""Black-box tests for the hashing module, derived solely from behaviour.yaml."""

import re


from src.hashing import (
    MISSING_SENTINEL,
    UNREADABLE_SENTINEL,
    compute_hash,
    get_body_below_header,
    parse_header,
)


# ---------------------------------------------------------------------------
# Invariant tests: sentinels
# ---------------------------------------------------------------------------


def test_missing_sentinel_is_12_chars():
    assert len(MISSING_SENTINEL) == 12


def test_unreadable_sentinel_is_12_chars():
    assert len(UNREADABLE_SENTINEL) == 12


def test_missing_sentinel_is_not_valid_hex():
    assert not re.match(r"^[0-9a-f]{12}$", MISSING_SENTINEL)


def test_unreadable_sentinel_is_not_valid_hex():
    assert not re.match(r"^[0-9a-f]{12}$", UNREADABLE_SENTINEL)


def test_missing_sentinel_value():
    assert MISSING_SENTINEL == "missing00000"


def test_unreadable_sentinel_value():
    assert UNREADABLE_SENTINEL == "unreadabl000"


# ---------------------------------------------------------------------------
# compute_hash tests
# ---------------------------------------------------------------------------


def test_compute_hash_returns_12_hex_chars():
    result = compute_hash("hello world")
    assert re.match(r"^[0-9a-f]{12}$", result)


def test_compute_hash_output_length_always_12():
    for s in ["", "a", "abc" * 1000, "\n\n\n", "   "]:
        assert len(compute_hash(s)) == 12


def test_compute_hash_output_format_invariant():
    for s in ["test", "another test", "123", "\t\ttabs\t\t"]:
        assert re.match(r"^[0-9a-f]{12}$", compute_hash(s))


def test_compute_hash_deterministic():
    content = "determinism check"
    assert compute_hash(content) == compute_hash(content)


def test_compute_hash_deterministic_multiple_calls():
    content = "some content here"
    results = {compute_hash(content) for _ in range(100)}
    assert len(results) == 1


def test_compute_hash_whitespace_normalization_leading():
    assert compute_hash("  hello") == compute_hash("hello")


def test_compute_hash_whitespace_normalization_trailing():
    assert compute_hash("hello   ") == compute_hash("hello")


def test_compute_hash_whitespace_normalization_both():
    assert compute_hash("  hello  ") == compute_hash("hello")


def test_compute_hash_whitespace_normalization_newlines():
    assert compute_hash("\nhello\n") == compute_hash("hello")


def test_compute_hash_whitespace_normalization_tabs():
    assert compute_hash("\thello\t") == compute_hash("hello")


def test_compute_hash_whitespace_normalization_mixed():
    assert compute_hash("  \t\n hello \n\t  ") == compute_hash("hello")


def test_compute_hash_a_equals_padded_a():
    """Spec: content 'a' vs '  a  ' produce identical hashes."""
    assert compute_hash("a") == compute_hash("  a  ")


def test_compute_hash_different_content_different_hashes():
    assert compute_hash("foo") != compute_hash("bar")


def test_compute_hash_different_content_collision_resistance():
    hashes = {compute_hash(f"content_{i}") for i in range(200)}
    assert len(hashes) == 200


def test_compute_hash_empty_string():
    result = compute_hash("")
    assert re.match(r"^[0-9a-f]{12}$", result)


def test_compute_hash_whitespace_only_equals_empty():
    """All-whitespace content should hash the same as empty after stripping."""
    assert compute_hash("   ") == compute_hash("")
    assert compute_hash("\n\n") == compute_hash("")
    assert compute_hash("\t\t") == compute_hash("")


def test_compute_hash_internal_whitespace_preserved():
    """Only leading/trailing whitespace is stripped, not internal."""
    assert compute_hash("a b") != compute_hash("ab")


# ---------------------------------------------------------------------------
# parse_header tests
# ---------------------------------------------------------------------------


def test_parse_header_no_marker_returns_none():
    content = "some random content\nno header here"
    assert parse_header(content) is None


def test_parse_header_empty_string_returns_none():
    assert parse_header("") is None


def test_parse_header_extracts_spec_path():
    content = "# @unslop-managed -- Edit foo.spec.md instead"
    result = parse_header(content)
    assert result is not None
    assert result["spec_path"] == "foo.spec.md"


def test_parse_header_extracts_spec_path_with_directory():
    content = "# @unslop-managed -- Edit path/to/my.spec.md instead"
    result = parse_header(content)
    assert result["spec_path"] == "path/to/my.spec.md"


def test_parse_header_extracts_spec_hash():
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:a1b2c3d4e5f6 output-hash:f6e5d4c3b2a1"
    result = parse_header(content)
    assert result["spec_hash"] == "a1b2c3d4e5f6"


def test_parse_header_extracts_output_hash():
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:a1b2c3d4e5f6 output-hash:f6e5d4c3b2a1"
    result = parse_header(content)
    assert result["output_hash"] == "f6e5d4c3b2a1"


def test_parse_header_extracts_principles_hash():
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:a1b2c3d4e5f6 principles-hash:112233445566"
    result = parse_header(content)
    assert result["principles_hash"] == "112233445566"


def test_parse_header_extracts_concrete_deps_hash():
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:a1b2c3d4e5f6 concrete-deps-hash:aabbccddeeff"
    result = parse_header(content)
    assert result["concrete_deps_hash"] == "aabbccddeeff"


def test_parse_header_extracts_generated_timestamp():
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:a1b2c3d4e5f6 generated:2024-01-15T10:30:00Z"
    result = parse_header(content)
    assert result["generated"] == "2024-01-15T10:30:00Z"


def test_parse_header_extracts_managed_end_line():
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:a1b2c3d4e5f6 managed-end-line:42"
    result = parse_header(content)
    assert result["managed_end_line"] == 42
    assert isinstance(result["managed_end_line"], int)


def test_parse_header_extracts_concrete_manifest():
    content = (
        "# @unslop-managed -- Edit foo.spec.md instead\n"
        "# spec-hash:a1b2c3d4e5f6\n"
        "# concrete-manifest:dep1.impl.md:a3f8c2e9b7d1,dep2.impl.md:7f2e1b8a9c04"
    )
    result = parse_header(content)
    assert result["concrete_manifest"] is not None
    assert result["concrete_manifest"]["dep1.impl.md"] == "a3f8c2e9b7d1"
    assert result["concrete_manifest"]["dep2.impl.md"] == "7f2e1b8a9c04"


def test_parse_header_manifest_with_missing_sentinel():
    content = (
        "# @unslop-managed -- Edit foo.spec.md instead\n"
        "# spec-hash:a1b2c3d4e5f6\n"
        f"# concrete-manifest:dep1.impl.md:{MISSING_SENTINEL}"
    )
    result = parse_header(content)
    assert result["concrete_manifest"] is not None
    assert result["concrete_manifest"]["dep1.impl.md"] == MISSING_SENTINEL


def test_parse_header_manifest_with_unreadable_sentinel():
    content = (
        "# @unslop-managed -- Edit foo.spec.md instead\n"
        "# spec-hash:a1b2c3d4e5f6\n"
        f"# concrete-manifest:dep1.impl.md:{UNREADABLE_SENTINEL}"
    )
    result = parse_header(content)
    assert result["concrete_manifest"] is not None
    assert result["concrete_manifest"]["dep1.impl.md"] == UNREADABLE_SENTINEL


def test_parse_header_python_comment_prefix():
    content = "# @unslop-managed -- Edit foo.spec.md instead"
    result = parse_header(content)
    assert result is not None
    assert result["spec_path"] == "foo.spec.md"


def test_parse_header_c_style_comment_prefix():
    content = "// @unslop-managed -- Edit foo.spec.md instead"
    result = parse_header(content)
    assert result is not None
    assert result["spec_path"] == "foo.spec.md"


def test_parse_header_sql_comment_prefix():
    content = "-- @unslop-managed -- Edit foo.spec.md instead"
    result = parse_header(content)
    assert result is not None
    assert result["spec_path"] == "foo.spec.md"


def test_parse_header_block_comment_prefix():
    content = "/* @unslop-managed -- Edit foo.spec.md instead */"
    result = parse_header(content)
    assert result is not None
    assert result["spec_path"] == "foo.spec.md"


def test_parse_header_html_comment_prefix():
    content = "<!-- @unslop-managed -- Edit foo.spec.md instead -->"
    result = parse_header(content)
    assert result is not None
    assert result["spec_path"] == "foo.spec.md"


def test_parse_header_old_format():
    content = "# Generated from spec at 2024-01-15T10:30:00Z"
    # Old format without @unslop-managed marker => no spec_path => None
    assert parse_header(content) is None


def test_parse_header_old_format_with_managed_marker():
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# Generated from spec at 2024-01-15T10:30:00Z"
    result = parse_header(content)
    assert result is not None
    # If spec_hash is None and old format marker is present, old_format should be True
    # But spec_hash might not be set, so old_format depends on spec_hash being None
    assert result["generated"] == "2024-01-15T10:30:00Z"


def test_parse_header_marker_on_line_6_returns_none():
    """@unslop-managed on line 6+ should not be found (only first 5 lines scanned)."""
    lines = ["line1", "line2", "line3", "line4", "line5"]
    lines.append("# @unslop-managed -- Edit foo.spec.md instead")
    content = "\n".join(lines)
    assert parse_header(content) is None


def test_parse_header_marker_on_line_5_is_found():
    """@unslop-managed on line 5 should be found."""
    lines = ["", "", "", ""]  # lines 1-4 are empty
    lines.append("# @unslop-managed -- Edit foo.spec.md instead")
    content = "\n".join(lines)
    result = parse_header(content)
    assert result is not None
    assert result["spec_path"] == "foo.spec.md"


def test_parse_header_returned_dict_has_all_keys():
    """Invariant: returned dict always contains all expected keys."""
    content = "# @unslop-managed -- Edit foo.spec.md instead"
    result = parse_header(content)
    expected_keys = {
        "spec_path",
        "spec_hash",
        "output_hash",
        "principles_hash",
        "concrete_deps_hash",
        "concrete_manifest",
        "managed_end_line",
        "generated",
        "old_format",
    }
    assert set(result.keys()) == expected_keys


def test_parse_header_missing_fields_are_none():
    """Fields not present in header should be None (except old_format which is bool)."""
    content = "# @unslop-managed -- Edit foo.spec.md instead"
    result = parse_header(content)
    assert result["spec_hash"] is None
    assert result["output_hash"] is None
    assert result["principles_hash"] is None
    assert result["concrete_deps_hash"] is None
    assert result["concrete_manifest"] is None
    assert result["managed_end_line"] is None
    assert result["generated"] is None
    assert result["old_format"] is False


def test_parse_header_manifest_multiple_entries():
    """Concrete manifest with multiple comma-separated entries parsed correctly."""
    content = (
        "# @unslop-managed -- Edit foo.spec.md instead\n"
        "# spec-hash:aabbccddeeff\n"
        "# concrete-manifest:a/b.impl.md:111111111111,c/d.impl.md:222222222222,e/f.impl.md:333333333333"
    )
    result = parse_header(content)
    manifest = result["concrete_manifest"]
    assert manifest is not None
    assert len(manifest) == 3
    assert manifest["a/b.impl.md"] == "111111111111"
    assert manifest["c/d.impl.md"] == "222222222222"
    assert manifest["e/f.impl.md"] == "333333333333"


def test_parse_header_manifest_uses_last_colon_separator():
    """Dep path containing colons should use last colon as separator."""
    content = (
        "# @unslop-managed -- Edit foo.spec.md instead\n"
        "# spec-hash:aabbccddeeff\n"
        "# concrete-manifest:path/with:colon.impl.md:111111111111"
    )
    result = parse_header(content)
    manifest = result["concrete_manifest"]
    assert manifest is not None
    assert manifest["path/with:colon.impl.md"] == "111111111111"


def test_parse_header_all_fields_populated():
    content = (
        "# @unslop-managed -- Edit foo.spec.md instead\n"
        "# spec-hash:aabbccddeeff output-hash:112233445566 "
        "principles-hash:aabb11223344 concrete-deps-hash:ffeeddccbbaa "
        "generated:2024-06-01T00:00:00Z managed-end-line:50\n"
        "# concrete-manifest:dep.impl.md:abcdef012345"
    )
    result = parse_header(content)
    assert result["spec_path"] == "foo.spec.md"
    assert result["spec_hash"] == "aabbccddeeff"
    assert result["output_hash"] == "112233445566"
    assert result["principles_hash"] == "aabb11223344"
    assert result["concrete_deps_hash"] == "ffeeddccbbaa"
    assert result["generated"] == "2024-06-01T00:00:00Z"
    assert result["managed_end_line"] == 50
    assert result["concrete_manifest"]["dep.impl.md"] == "abcdef012345"


def test_parse_header_c_style_with_hashes():
    content = "// @unslop-managed -- Edit foo.spec.md instead\n// spec-hash:aabbccddeeff output-hash:112233445566"
    result = parse_header(content)
    assert result["spec_path"] == "foo.spec.md"
    assert result["spec_hash"] == "aabbccddeeff"
    assert result["output_hash"] == "112233445566"


def test_parse_header_html_comment_with_hashes():
    content = "<!-- @unslop-managed -- Edit foo.spec.md instead -->\n<!-- spec-hash:aabbccddeeff output-hash:112233445566 -->"
    result = parse_header(content)
    assert result["spec_path"] == "foo.spec.md"
    assert result["spec_hash"] == "aabbccddeeff"
    assert result["output_hash"] == "112233445566"


def test_parse_header_block_comment_with_hashes():
    content = "/* @unslop-managed -- Edit foo.spec.md instead */\n/* spec-hash:aabbccddeeff output-hash:112233445566 */"
    result = parse_header(content)
    assert result["spec_path"] == "foo.spec.md"
    assert result["spec_hash"] == "aabbccddeeff"
    assert result["output_hash"] == "112233445566"


# ---------------------------------------------------------------------------
# get_body_below_header tests
# ---------------------------------------------------------------------------


def test_get_body_below_header_returns_content_after_header():
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:aabbccddeeff\ndef hello():\n    pass"
    body = get_body_below_header(content)
    assert "def hello():" in body
    assert "@unslop-managed" not in body
    assert "spec-hash" not in body


def test_get_body_below_header_blank_lines_in_header_skipped():
    content = "# @unslop-managed -- Edit foo.spec.md instead\n\n# spec-hash:aabbccddeeff\ndef hello():\n    pass"
    body = get_body_below_header(content)
    assert "def hello():" in body
    assert "@unslop-managed" not in body


def test_get_body_below_header_end_line_none_returns_full_body():
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:aabbccddeeff\nline1\nline2\nline3"
    body = get_body_below_header(content, end_line=None)
    assert "line1" in body
    assert "line2" in body
    assert "line3" in body


def test_get_body_below_header_end_line_truncates():
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:aabbccddeeff\nline3\nline4\nline5\nline6"
    # Header is 2 lines. Body starts at line 3. end_line=5 means include lines 3-4.
    body = get_body_below_header(content, end_line=5)
    assert "line3" in body
    assert "line4" in body
    assert "line5" not in body
    assert "line6" not in body


def test_get_body_below_header_end_line_too_small_emits_warning(capsys):
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:aabbccddeeff\nbody content here"
    # end_line=1 is before/at header, should emit warning and return full body
    body = get_body_below_header(content, end_line=1)
    captured = capsys.readouterr()
    assert "Warning" in captured.err or "warning" in captured.err.lower()
    assert "body content here" in body


def test_get_body_below_header_end_line_zero_emits_warning(capsys):
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:aabbccddeeff\nbody content"
    body = get_body_below_header(content, end_line=0)
    captured = capsys.readouterr()
    assert "Warning" in captured.err or "warning" in captured.err.lower()
    assert "body content" in body


def test_get_body_below_header_end_line_at_body_start_emits_warning(capsys):
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:aabbccddeeff\nbody line 1\nbody line 2"
    # Body starts at line 3 (0-indexed: 2). end_line <= body_start+1 => warning.
    # body_start=2, so end_line <= 3 triggers warning.
    body = get_body_below_header(content, end_line=3)
    captured = capsys.readouterr()
    assert "Warning" in captured.err or "warning" in captured.err.lower()
    assert "body line 1" in body


def test_get_body_below_header_non_header_line_stops_scan():
    """Non-header line in first 5 lines stops header scanning."""
    content = "# @unslop-managed -- Edit foo.spec.md instead\ndef foo():\n# spec-hash:aabbccddeeff\n    pass"
    body = get_body_below_header(content)
    # "def foo():" is not a header marker, so scanning stops.
    # Body starts at line 2 (0-indexed: 1).
    assert "def foo():" in body


def test_get_body_below_header_recognizes_all_header_markers():
    """All header markers should be recognized and skipped."""
    content = (
        "# @unslop-managed -- Edit foo.spec.md instead\n"
        "# spec-hash:aabbccddeeff output-hash:112233445566\n"
        "# Generated from spec at 2024-01-01\n"
        "# concrete-manifest:dep.impl.md:aabbccddeeff\n"
        "actual body content"
    )
    body = get_body_below_header(content)
    assert body.strip() == "actual body content"


def test_get_body_below_header_no_header_returns_all():
    content = "no header here\njust regular content"
    body = get_body_below_header(content)
    assert "no header here" in body
    assert "just regular content" in body


def test_get_body_below_header_empty_content():
    body = get_body_below_header("")
    assert body == ""


def test_get_body_below_header_only_header():
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:aabbccddeeff"
    body = get_body_below_header(content)
    assert body == ""


def test_get_body_below_header_end_line_beyond_file():
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:aabbccddeeff\nline1\nline2"
    # end_line=100 is way beyond the file, should just return all body lines
    body = get_body_below_header(content, end_line=100)
    assert "line1" in body
    assert "line2" in body


# ---------------------------------------------------------------------------
# Cross-function integration tests
# ---------------------------------------------------------------------------


def test_compute_hash_of_body_is_deterministic_with_header():
    """Extracting body and hashing it should be deterministic."""
    content = "# @unslop-managed -- Edit foo.spec.md instead\n# spec-hash:aabbccddeeff\ndef hello():\n    return 42"
    body = get_body_below_header(content)
    h1 = compute_hash(body)
    h2 = compute_hash(body)
    assert h1 == h2
    assert re.match(r"^[0-9a-f]{12}$", h1)


def test_parse_header_and_get_body_complementary():
    """parse_header and get_body_below_header should handle the same content."""
    content = (
        "# @unslop-managed -- Edit foo.spec.md instead\n"
        "# spec-hash:aabbccddeeff output-hash:112233445566\n"
        "def code():\n"
        "    pass"
    )
    header = parse_header(content)
    body = get_body_below_header(content)
    assert header is not None
    assert header["spec_path"] == "foo.spec.md"
    assert "def code():" in body
    assert "@unslop-managed" not in body


def test_parse_header_managed_marker_without_edit_pattern_returns_none():
    """@unslop-managed present but no 'Edit ... instead' pattern returns None."""
    content = "# @unslop-managed -- Do not touch"
    assert parse_header(content) is None


def test_parse_header_manifest_all_entries_malformed_returns_none_manifest():
    """When all manifest entries have invalid hashes, concrete_manifest is None."""
    content = (
        "# @unslop-managed -- Edit foo.spec.md instead\n"
        "# spec-hash:aabbccddeeff\n"
        "# concrete-manifest:bad.impl.md:ZZZZZZ,short.impl.md:abc"
    )
    result = parse_header(content)
    assert result is not None
    assert result["concrete_manifest"] is None
