"""Tests for the Mock Budget Linter (validate_mocks.py)."""

import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "unslop", "scripts"))

import pytest

from validate_mocks import (
    MockTargetExtractor,
    load_boundaries,
    validate_test_file,
)


class TestLoadBoundaries:
    def test_returns_empty_when_no_file(self, tmp_path):
        assert load_boundaries(tmp_path) == []

    def test_loads_json_array(self, tmp_path):
        boundaries_dir = tmp_path / ".unslop"
        boundaries_dir.mkdir()
        (boundaries_dir / "boundaries.json").write_text('["requests", "boto3"]')
        assert load_boundaries(tmp_path) == ["requests", "boto3"]

    def test_raises_on_non_array(self, tmp_path):
        boundaries_dir = tmp_path / ".unslop"
        boundaries_dir.mkdir()
        (boundaries_dir / "boundaries.json").write_text('{"bad": "format"}')
        with pytest.raises(ValueError, match="must be a JSON array"):
            load_boundaries(tmp_path)


class TestMockTargetExtractor:
    def _extract(self, source: str) -> list[dict]:
        import ast
        tree = ast.parse(source)
        extractor = MockTargetExtractor()
        extractor.visit(tree)
        return extractor.targets

    def test_decorator_patch(self):
        source = textwrap.dedent('''\
            from unittest.mock import patch

            @patch("src.retry.time.sleep")
            def test_foo(mock_sleep):
                pass
        ''')
        targets = self._extract(source)
        assert len(targets) == 1
        assert targets[0]["target"] == "src.retry.time.sleep"

    def test_context_manager_patch(self):
        source = textwrap.dedent('''\
            from unittest.mock import patch

            def test_bar():
                with patch("os.environ") as mock_env:
                    pass
        ''')
        targets = self._extract(source)
        assert len(targets) == 1
        assert targets[0]["target"] == "os.environ"

    def test_patch_object(self):
        source = textwrap.dedent('''\
            from unittest.mock import patch

            @patch.object(SomeClass, "method")
            def test_baz(mock_method):
                pass
        ''')
        # patch.object first arg is an object, not a string — should not extract
        targets = self._extract(source)
        assert len(targets) == 0

    def test_multiple_patches(self):
        source = textwrap.dedent('''\
            from unittest.mock import patch

            @patch("time.sleep")
            @patch("requests.get")
            def test_multi(mock_get, mock_sleep):
                pass
        ''')
        targets = self._extract(source)
        assert len(targets) == 2
        target_names = {t["target"] for t in targets}
        assert target_names == {"time.sleep", "requests.get"}

    def test_mocker_patch(self):
        source = textwrap.dedent('''\
            def test_with_mocker(mocker):
                mocker.patch("src.internal.helper")
        ''')
        targets = self._extract(source)
        assert len(targets) == 1
        assert targets[0]["target"] == "src.internal.helper"

    def test_no_mocks(self):
        source = textwrap.dedent('''\
            def test_simple():
                assert 1 + 1 == 2
        ''')
        targets = self._extract(source)
        assert len(targets) == 0


class TestValidateTestFile:
    def test_clean_test_passes(self):
        source = textwrap.dedent('''\
            from unittest.mock import patch

            @patch("time.sleep")
            def test_delay(mock_sleep):
                pass
        ''')
        result = validate_test_file(source, "test_foo.py", [])
        assert result["status"] == "pass"
        assert result["boundary_mocks"] == 1
        assert result["internal_mocks"] == 0

    def test_internal_mock_fails(self):
        source = textwrap.dedent('''\
            from unittest.mock import patch

            @patch("src.retry.time.sleep")
            def test_delay(mock_sleep):
                pass
        ''')
        result = validate_test_file(source, "test_foo.py", [])
        assert result["status"] == "fail"
        assert result["internal_mocks"] == 1
        assert len(result["violations"]) == 1
        assert result["violations"][0]["check"] == "internal_mock"

    def test_boundary_mock_passes(self):
        source = textwrap.dedent('''\
            from unittest.mock import patch

            @patch("requests.get")
            def test_api(mock_get):
                pass
        ''')
        result = validate_test_file(source, "test_foo.py", ["requests"])
        assert result["status"] == "pass"
        assert result["boundary_mocks"] == 1

    def test_stdlib_mock_always_allowed(self):
        source = textwrap.dedent('''\
            from unittest.mock import patch

            @patch("os.environ.get")
            @patch("datetime.datetime.now")
            def test_env(mock_now, mock_get):
                pass
        ''')
        result = validate_test_file(source, "test_foo.py", [])
        assert result["status"] == "pass"
        assert result["boundary_mocks"] == 2

    def test_syntax_error(self):
        source = "def test_broken(\n"
        result = validate_test_file(source, "test_bad.py", [])
        assert result["status"] == "fail"
        assert result["violations"][0]["check"] == "syntax_error"

    def test_mixed_mocks(self):
        """One allowed, one internal — should fail."""
        source = textwrap.dedent('''\
            from unittest.mock import patch

            @patch("time.sleep")
            @patch("src.db.connection.get_pool")
            def test_mixed(mock_pool, mock_sleep):
                pass
        ''')
        result = validate_test_file(source, "test_foo.py", [])
        assert result["status"] == "fail"
        assert result["boundary_mocks"] == 1
        assert result["internal_mocks"] == 1


class TestJitterStressTestCompliance:
    """Validate the actual jitter stress test against the mock budget."""

    def test_jitter_test_with_empty_boundaries(self):
        """The jitter test mocks src.retry.time.sleep — this should FAIL
        with empty boundaries because 'src' is an internal module.

        This demonstrates the Mock Budget in action: the existing test
        (written before the adversarial framework) uses an internal mock
        path. A Mason-generated test would mock 'time.sleep' directly.
        """
        test_path = Path("stress-tests/jitter/tests/test_retry.py")
        if not test_path.exists():
            pytest.skip("Stress test not available")

        source = test_path.read_text(encoding="utf-8")
        result = validate_test_file(source, str(test_path), [])

        # The existing test mocks "src.retry.time.sleep" — this is an internal path
        assert result["internal_mocks"] > 0
        assert result["status"] == "fail"

    def test_jitter_test_demonstrates_correct_approach(self):
        """Show what a Mason-compliant test would look like:
        mock 'time.sleep' (stdlib) instead of 'src.retry.time.sleep' (internal)."""
        source = textwrap.dedent('''\
            from unittest.mock import patch

            @patch("time.sleep")
            def test_delay_bounded(mock_sleep):
                from src.retry import retry, RetryConfig, MaxRetriesExceeded
                import pytest

                config = RetryConfig(max_retries=5, base_delay=1.0, max_delay=10.0)
                with pytest.raises(MaxRetriesExceeded):
                    retry(lambda: (_ for _ in ()).throw(RuntimeError("fail")), config)

                for call in mock_sleep.call_args_list:
                    delay = call[0][0]
                    assert 0 <= delay <= config.max_delay
        ''')
        result = validate_test_file(source, "test_compliant.py", [])
        assert result["status"] == "pass"
        assert result["internal_mocks"] == 0
