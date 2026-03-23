"""Tests for the Behaviour DSL validator (validate_behaviour.py)."""

import os
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "unslop", "scripts"))

import pytest

from validate_behaviour import validate_behaviour


class TestValidBehaviourFiles:
    def test_minimal_valid(self):
        content = textwrap.dedent("""\
            behaviour: "transfer_funds"
            interface: "finance.ops:transfer"
            constraints:
              - given: "amount > 0"
        """)
        result = validate_behaviour(content, "transfer.behaviour.yaml")
        assert result["status"] == "pass"

    def test_full_spec(self):
        content = textwrap.dedent("""\
            behaviour: "retry_with_jitter"
            interface: "src.retry:retry"
            constraints:
              - given: "callable succeeds on first attempt"
              - invariant: "delay in [0, max_delay]"
              - error: "MaxRetriesExceeded if exhausted"
              - property: "delays include randomness"
            errors:
              - "MaxRetriesExceeded: raised after max retries"
            invariants:
              - "Total sleep bounded by max_retries * max_delay"
            depends_on:
              - "time.sleep"
        """)
        result = validate_behaviour(content, "retry.behaviour.yaml")
        assert result["status"] == "pass"


class TestInvalidBehaviourFiles:
    def test_empty_file(self):
        result = validate_behaviour("", "empty.yaml")
        assert result["status"] == "fail"
        assert result["issues"][0]["check"] == "empty_file"

    def test_missing_behaviour_field(self):
        content = textwrap.dedent("""\
            interface: "foo.bar:baz"
            constraints:
              - given: "x > 0"
        """)
        result = validate_behaviour(content, "no_behaviour.yaml")
        assert result["status"] == "fail"
        assert any(i["field"] == "behaviour" for i in result["issues"])

    def test_missing_interface_field(self):
        content = textwrap.dedent("""\
            behaviour: "do_thing"
            constraints:
              - given: "x > 0"
        """)
        result = validate_behaviour(content, "no_interface.yaml")
        assert result["status"] == "fail"
        assert any(i["field"] == "interface" for i in result["issues"])

    def test_no_behavioural_content(self):
        content = textwrap.dedent("""\
            behaviour: "do_thing"
            interface: "mod:func"
        """)
        result = validate_behaviour(content, "no_constraints.yaml")
        assert result["status"] == "fail"
        assert any(i["check"] == "no_behavioural_content" for i in result["issues"])

    def test_invalid_interface_format(self):
        content = textwrap.dedent("""\
            behaviour: "do_thing"
            interface: "not a valid interface!!"
            constraints:
              - given: "x > 0"
        """)
        result = validate_behaviour(content, "bad_iface.yaml")
        assert result["status"] == "fail"
        assert any(i["check"] == "invalid_interface" for i in result["issues"])

    def test_empty_constraint_value(self):
        content = textwrap.dedent("""\
            behaviour: "do_thing"
            interface: "mod:func"
            constraints:
              - given: ""
        """)
        result = validate_behaviour(content, "empty_constraint.yaml")
        assert result["status"] == "fail"
        assert any(i["check"] == "empty_constraint" for i in result["issues"])


class TestWarnings:
    def test_unknown_field(self):
        content = textwrap.dedent("""\
            behaviour: "do_thing"
            interface: "mod:func"
            constraints:
              - given: "x > 0"
            extra_field: "ignored"
        """)
        result = validate_behaviour(content, "extra.yaml")
        assert result["status"] == "warn"
        assert any(w["check"] == "unknown_field" for w in result["warnings"])

    def test_unknown_constraint_type(self):
        content = textwrap.dedent("""\
            behaviour: "do_thing"
            interface: "mod:func"
            constraints:
              - prerequisite: "must be logged in"
        """)
        result = validate_behaviour(content, "bad_type.yaml")
        assert result["status"] == "warn"
        assert any(w["check"] == "unknown_constraint_type" for w in result["warnings"])

    def test_untyped_constraint(self):
        content = textwrap.dedent("""\
            behaviour: "do_thing"
            interface: "mod:func"
            constraints:
              - "just a plain string"
        """)
        result = validate_behaviour(content, "untyped.yaml")
        assert result["status"] == "warn"
        assert any(w["check"] == "untyped_constraint" for w in result["warnings"])


class TestMultiBehaviourFormat:
    """Tests for multi-behaviour files (multiple behaviour: blocks)."""

    def test_two_blocks_valid(self):
        content = textwrap.dedent("""\
            behaviour: "fn_a"
            interface: "mod:fn_a"
            constraints:
              - given: "input is positive"
                then: "returns double"

            behaviour: "fn_b"
            interface: "mod:fn_b"
            constraints:
              - given: "input is negative"
                then: "raises ValueError"
        """)
        result = validate_behaviour(content, "test.yaml")
        assert result["status"] == "pass"
        assert result["format"] == "multi"
        assert result["block_count"] == 2

    def test_single_block_stays_single_format(self):
        content = textwrap.dedent("""\
            behaviour: "fn_a"
            interface: "mod:fn_a"
            constraints:
              - given: "always"
                then: "returns 42"
        """)
        result = validate_behaviour(content, "test.yaml")
        assert result["format"] == "single"

    def test_multi_block_missing_interface(self):
        content = textwrap.dedent("""\
            behaviour: "fn_a"
            interface: "mod:fn_a"
            constraints:
              - given: "always"
                then: "returns 1"

            behaviour: "fn_b"
            constraints:
              - given: "always"
                then: "returns 2"
        """)
        result = validate_behaviour(content, "test.yaml")
        assert result["status"] == "fail"
        assert any("interface" in str(i.get("message", "")) for i in result["issues"])

    def test_multi_block_one_empty(self):
        content = textwrap.dedent("""\
            behaviour: "fn_a"
            interface: "mod:fn_a"
            constraints:
              - given: "always"
                then: "returns 1"

            behaviour: "fn_b"
            interface: "mod:fn_b"
        """)
        result = validate_behaviour(content, "test.yaml")
        assert result["status"] == "fail"
        assert any("no_behavioural_content" in str(i.get("check", "")) for i in result["issues"])

    def test_dirty_jitter_multi_behaviour(self):
        from pathlib import Path

        path = Path("stress-tests/dirty-jitter/src/retry_v1.py.behaviour.yaml")
        if not path.exists():
            pytest.skip("Dirty jitter behaviour file not available")
        content = path.read_text(encoding="utf-8")
        result = validate_behaviour(content, str(path))
        assert result["status"] == "pass", f"Dirty jitter behaviour file is invalid: {result}"
        assert result["format"] == "multi"
        assert result["block_count"] == 2


class TestJitterBehaviourExample:
    """Validate the actual jitter behaviour YAML from stress-tests."""

    def test_jitter_behaviour_is_valid(self):
        from pathlib import Path

        behaviour_path = Path("stress-tests/jitter/src/retry.py.behaviour.yaml")
        if not behaviour_path.exists():
            pytest.skip("Jitter behaviour file not available")

        content = behaviour_path.read_text(encoding="utf-8")
        result = validate_behaviour(content, str(behaviour_path))
        assert result["status"] == "pass", f"Jitter behaviour file is invalid: {result}"
