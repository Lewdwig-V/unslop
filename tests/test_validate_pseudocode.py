"""Tests for validate_pseudocode.py — pseudocode linting for concrete specs."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'unslop', 'scripts'))
from validate_pseudocode import validate_pseudocode, extract_pseudocode_blocks


class TestExtractBlocks:
    def test_extracts_single_block(self):
        content = "# Title\n```pseudocode\nSET x ← 1\n```\n"
        blocks = extract_pseudocode_blocks(content)
        assert len(blocks) == 1
        assert len(blocks[0]["lines"]) == 1

    def test_extracts_multiple_blocks(self):
        content = "```pseudocode\nSET x ← 1\n```\ntext\n```pseudocode\nSET y ← 2\n```\n"
        blocks = extract_pseudocode_blocks(content)
        assert len(blocks) == 2

    def test_ignores_non_pseudocode_fences(self):
        content = "```python\ndef foo(): pass\n```\n```pseudocode\nSET x ← 1\n```\n"
        blocks = extract_pseudocode_blocks(content)
        assert len(blocks) == 1

    def test_flags_unclosed_block(self):
        content = "```pseudocode\nSET x ← 1\n"
        blocks = extract_pseudocode_blocks(content)
        assert len(blocks) == 1
        assert blocks[0].get("unclosed") is True


class TestBareAssignment:
    def test_catches_bare_equals(self):
        content = "```pseudocode\nx = 1\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "bare_assignment" for v in result["violations"])

    def test_allows_arrow_assignment(self):
        content = "```pseudocode\nSET x ← 1\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_allows_equality_in_if(self):
        """= inside IF is a comparison, not assignment."""
        content = "```pseudocode\nIF x = 1\n    RETURN true\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_allows_equality_in_while(self):
        """= inside WHILE is a comparison."""
        content = "```pseudocode\nWHILE state = OPEN\n    CALL process()\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_allows_equality_in_until(self):
        """= inside UNTIL is a comparison."""
        content = "```pseudocode\nUNTIL status = DONE\n    CALL poll()\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_allows_equality_in_else_if(self):
        """= inside ELSE IF is a comparison."""
        content = "```pseudocode\nIF x = 1\n    RETURN a\nELSE IF x = 2\n    RETURN b\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_allows_equality_in_case(self):
        """= inside CASE/WHEN is a comparison."""
        content = "```pseudocode\nSWITCH mode\n    CASE mode = FAST: RETURN 1\nEND SWITCH\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_catches_bare_assignment_in_case_action(self):
        """= in CASE action after colon is an assignment, not a comparison."""
        content = "```pseudocode\nSWITCH mode\n    CASE mode = FAST: retry_count = 0\nEND SWITCH\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        checks = [v["check"] for v in result["violations"]]
        assert "bare_assignment" in checks

    def test_catches_bare_assignment_in_when_action(self):
        """= in WHEN action after colon is an assignment, not a comparison."""
        content = "```pseudocode\nWHEN status = OK: count = count + 1\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        checks = [v["check"] for v in result["violations"]]
        assert "bare_assignment" in checks

    def test_allows_comparison_in_case_condition(self):
        """= in CASE condition (before colon) is still a valid comparison."""
        content = "```pseudocode\nSWITCH mode\n    CASE mode = FAST: RETURN 1\nEND SWITCH\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_allows_case_without_colon(self):
        """CASE line without colon — = is a pure condition, no action part."""
        content = "```pseudocode\nSWITCH mode\n    CASE mode = FAST\n        RETURN 1\nEND SWITCH\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_catches_bare_equals_without_context(self):
        """= without SET/IF/WHILE context is a bare assignment violation."""
        content = "```pseudocode\nretry_count = 0\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "bare_assignment" for v in result["violations"])

    def test_does_not_flag_comparison_operators(self):
        content = "```pseudocode\nIF x >= 1\n    RETURN true\nIF y <= 0\n    RETURN false\nIF z != null\n    RETURN z\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"


class TestLanguageKeywords:
    def test_catches_def(self):
        content = "```pseudocode\ndef retry(op):\n    pass\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "language_keyword" for v in result["violations"])

    def test_catches_lambda(self):
        content = "```pseudocode\nSET f ← lambda x: x + 1\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "language_keyword" for v in result["violations"])

    def test_catches_async(self):
        content = "```pseudocode\nasync FUNCTION fetch()\n    RETURN data\nEND FUNCTION\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "language_keyword" and "async" in v["message"]
                    for v in result["violations"])

    def test_catches_await(self):
        content = "```pseudocode\nSET result ← await fetch_data()\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "language_keyword" and "await" in v["message"]
                    for v in result["violations"])

    def test_catches_struct(self):
        content = "```pseudocode\nstruct Config\n    max_retries: INTEGER\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "language_keyword" for v in result["violations"])

    def test_catches_class(self):
        content = "```pseudocode\nclass RetryHandler\n    RETURN handler\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "language_keyword" for v in result["violations"])

    def test_catches_arrow_operator(self):
        content = "```pseudocode\nSET f ← (x) => x + 1\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "language_keyword" and "=>" in v["message"]
                    for v in result["violations"])

    def test_catches_thin_arrow_operator(self):
        content = "```pseudocode\nFUNCTION retry(op) -> Result\n    RETURN op()\nEND FUNCTION\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "language_keyword" and "->" in v["message"]
                    for v in result["violations"])

    def test_catches_match(self):
        content = "```pseudocode\nmatch status\n    200: RETURN ok\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "language_keyword" for v in result["violations"])

    def test_catches_case(self):
        content = "```pseudocode\ncase status\n    200: RETURN ok\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "language_keyword" for v in result["violations"])

    def test_catches_public_private(self):
        content = "```pseudocode\npublic FUNCTION handler()\n    RETURN data\nEND FUNCTION\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "language_keyword" for v in result["violations"])

    def test_allows_capitalized_keywords(self):
        content = "```pseudocode\nFUNCTION retry(operation, config)\n    RETURN result\nEND FUNCTION\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_allows_call_async_pattern(self):
        """CALL ASYNC is the pseudocode equivalent of await — must not be flagged."""
        content = "```pseudocode\nSET result ← CALL ASYNC fetch_data()\nWAIT FOR result\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_allows_switch_case_pattern(self):
        """Capitalized SWITCH/CASE is valid pseudocode."""
        content = "```pseudocode\nSWITCH status\n    CASE 200: RETURN ok\n    CASE 404: RETURN not_found\nEND SWITCH\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"


class TestLibraryCalls:
    def test_catches_dot_notation_with_parens(self):
        content = "```pseudocode\ntime.sleep(delay)\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "library_call" for v in result["violations"])

    def test_catches_random_uniform(self):
        content = "```pseudocode\nSET delay ← random.uniform(0, cap)\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "library_call" for v in result["violations"])

    def test_allows_generic_operations(self):
        content = "```pseudocode\nSET delay ← random_uniform(0, cap)\nWAIT delay\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"


class TestMultiStatement:
    def test_catches_semicolons(self):
        content = "```pseudocode\nSET x ← 1; SET y ← 2\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "multi_statement" for v in result["violations"])


class TestFunctionScope:
    def test_catches_unclosed_function(self):
        content = "```pseudocode\nFUNCTION retry(op)\n    RETURN 1\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "unclosed_function" for v in result["violations"])

    def test_allows_matched_function(self):
        content = "```pseudocode\nFUNCTION retry(op)\n    RETURN 1\nEND FUNCTION\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_catches_extra_end_function(self):
        content = "```pseudocode\nEND FUNCTION\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        assert any(v["check"] == "unmatched_end_function" for v in result["violations"])


class TestNoBlocks:
    def test_warns_on_no_pseudocode(self):
        content = "# Just markdown\n\nNo pseudocode here.\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "warn"
        assert any(w["check"] == "no_pseudocode" for w in result["warnings"])


class TestLoopAwareOperators:
    """Loop-aware operator linting: FOR must use ←, UNTIL may use =."""

    def test_for_with_bare_equals_is_violation(self):
        """FOR i = 1 TO 10 must be flagged — FOR initializes an iterator."""
        content = "```pseudocode\nFUNCTION loop()\n    FOR i = 0 TO 9\n        CALL process(i)\nEND FUNCTION\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        violations = [v for v in result["violations"] if v["check"] == "bare_assignment"]
        assert len(violations) == 1
        assert "FOR" in violations[0]["message"] or "Assignment context" in violations[0]["message"]

    def test_for_with_arrow_is_valid(self):
        """FOR i ← 0 TO 9 is correct pseudocode."""
        content = "```pseudocode\nFUNCTION loop()\n    FOR i ← 0 TO 9\n        CALL process(i)\nEND FUNCTION\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_for_with_walrus_is_valid(self):
        """FOR i := 0 TO 9 is also acceptable."""
        content = "```pseudocode\nFUNCTION loop()\n    FOR i := 0 TO 9\n        CALL process(i)\nEND FUNCTION\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_until_with_equals_is_valid(self):
        """UNTIL status = DONE is a comparison, not assignment."""
        content = "```pseudocode\nFUNCTION poll()\n    REPEAT\n        CALL check()\n    UNTIL status = DONE\nEND FUNCTION\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_while_with_equals_is_valid(self):
        """WHILE state = RUNNING is a comparison."""
        content = "```pseudocode\nFUNCTION run()\n    WHILE state = RUNNING\n        CALL tick()\nEND FUNCTION\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass"

    def test_set_with_bare_equals_is_violation(self):
        """SET x = 1 must be flagged — SET mutates state."""
        content = "```pseudocode\nSET x = 1\n```\n"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        violations = [v for v in result["violations"] if v["check"] == "bare_assignment"]
        assert len(violations) >= 1


class TestCompliantPseudocode:
    def test_full_jitter_example_passes(self):
        content = """```pseudocode
FUNCTION retry(operation, config)
    SET last_error ← null

    FOR attempt ← 0 TO config.max_retries - 1
        TRY
            SET result ← CALL operation()
            RETURN result
        CATCH error
            SET last_error ← error

            IF attempt < config.max_retries - 1
                SET upper_bound ← MIN(config.base_delay × 2^attempt, config.max_delay)
                SET delay ← random_uniform(0, upper_bound)    // Full Jitter
                WAIT delay

    RAISE MaxRetriesExceeded(config.max_retries, last_error)
END FUNCTION
```"""
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"


class TestInlineCommentStripping:
    """Inline comments (// ...) should be invisible to all rule checks."""

    def test_banned_keyword_in_comment_ignored(self):
        """async in a comment should not trigger language_keyword."""
        content = '```pseudocode\nSET x ← 1 // must be async\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_banned_operator_in_comment_ignored(self):
        """-> in a comment should not trigger language_keyword."""
        content = '```pseudocode\nSET result ← CALL handler // returns -> error\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_library_call_in_comment_ignored(self):
        """time.sleep() in a comment should not trigger library_call."""
        content = '```pseudocode\nSET timeout ← 30 // time.sleep(30) is the legacy equivalent\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_multi_statement_semicolon_in_comment_ignored(self):
        """Semicolons in comments should not trigger multi_statement."""
        content = '```pseudocode\nSET x ← 1 // note: a; b; c in legacy\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_bare_assignment_in_comment_ignored(self):
        """Bare = in a comment should not trigger bare_assignment."""
        content = '```pseudocode\nSET x ← 1 // where x = initial value\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_code_before_comment_still_checked(self):
        """The code part before // should still be linted."""
        content = '```pseudocode\nasync CALL handler // does the thing\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        checks = {v["check"] for v in result["violations"]}
        assert "language_keyword" in checks

    def test_multiple_inline_comments_in_block(self):
        """Multiple lines with inline comments should all be handled."""
        content = """```pseudocode
FUNCTION retry_with_backoff(operation, config)
    SET attempt ← 0 // start from zero
    SET last_error ← NULL // no error yet
    WHILE attempt < config.max_retries // keep trying
        SET attempt ← attempt + 1
    END WHILE
    RETURN last_error // or NULL if all passed
END FUNCTION
```"""
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_comment_only_after_strip_skipped(self):
        """A line that is all comment after the code part should work."""
        content = '```pseudocode\nSET x ← 1 //\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"


class TestStringLiteralMasking:
    """String literals should be invisible to keyword/library-call scanners."""

    def test_banned_keyword_in_double_quoted_string(self):
        """'async' inside a double-quoted string should not trigger."""
        content = '```pseudocode\nSET msg ← "async error"\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_banned_keyword_in_single_quoted_string(self):
        """'await' inside a single-quoted string should not trigger."""
        content = "```pseudocode\nSET msg ← 'await response'\n```"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_library_call_in_string(self):
        """time.sleep() inside a string should not trigger library_call."""
        content = '```pseudocode\nSET log_note ← "Calling time.sleep() now"\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_operator_in_string(self):
        """-> inside a string should not trigger language_keyword."""
        content = '```pseudocode\nSET arrow ← "returns -> error"\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_semicolon_in_string(self):
        """Semicolons inside a string should not trigger multi_statement."""
        content = '```pseudocode\nSET sql ← "SELECT a; SELECT b"\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_code_outside_string_still_checked(self):
        """Keywords outside strings should still be flagged."""
        content = '```pseudocode\nasync CALL handler("ok")\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "fail"
        checks = {v["check"] for v in result["violations"]}
        assert "language_keyword" in checks

    def test_escaped_quotes_in_string(self):
        r"""Escaped quotes should not break masking: 'it\'s async'."""
        content = "```pseudocode\nSET msg ← 'it\\'s an async op'\n```"
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_multiple_strings_on_one_line(self):
        """Multiple strings with keywords should all be masked."""
        content = '```pseudocode\nCALL log("async", "await")\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_string_plus_comment_both_masked(self):
        """String + comment on same line: both should be invisible."""
        content = '```pseudocode\nSET x ← "async" // await here\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_match_keyword_in_string(self):
        """'match' inside a string should not trigger (SWITCH/CASE rule)."""
        content = '```pseudocode\nSET pattern ← "match found"\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_class_keyword_in_error_message(self):
        """'class' in an error message string should not trigger."""
        content = '```pseudocode\nSET err ← "class not found: Widget"\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_url_in_string_not_truncated(self):
        """A URL like 'https://...' inside a string must not be treated as // comment."""
        content = '```pseudocode\nSET endpoint ← "https://api.example.com/v1"\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_double_slash_in_string_not_comment(self):
        """'//' inside a string must not start a comment."""
        content = '```pseudocode\nSET msg ← "async // not a comment"\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_real_comment_after_string_with_slashes(self):
        """A real // comment after a string containing // should still be stripped."""
        content = '```pseudocode\nSET url ← "https://example.com" // fetch endpoint\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"

    def test_keyword_after_url_string_not_false_positive(self):
        """Keyword scan must not see tokens from inside a truncated URL string."""
        content = '```pseudocode\nSET log ← "async callback at https://svc.io/fn"\n```'
        result = validate_pseudocode(content, "test.impl.md")
        assert result["status"] == "pass", f"Expected pass, got: {result}"
