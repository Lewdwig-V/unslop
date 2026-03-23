"""Tests for the Prosecutor (equivalent mutant classifier)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "unslop", "scripts"))

from prosecutor import (
    OffByOneEquivalence,
    RedundantBooleanEquivalence,
    StringLiteralEquivalence,
    DeadCodeEquivalence,
    classify_mutant,
    classify_surviving_mutants,
)


class TestOffByOneEquivalence:
    def test_less_than_to_less_equal(self):
        p = OffByOneEquivalence()
        assert p.matches("x < 10", "x <= 9", {})

    def test_greater_than_to_greater_equal(self):
        p = OffByOneEquivalence()
        assert p.matches("x > 5", "x >= 6", {})

    def test_non_adjacent_values_no_match(self):
        p = OffByOneEquivalence()
        assert not p.matches("x < 10", "x <= 7", {})

    def test_different_variables_no_match(self):
        p = OffByOneEquivalence()
        assert not p.matches("x < 10", "y <= 9", {})


class TestRedundantBooleanEquivalence:
    def test_true_and_x(self):
        p = RedundantBooleanEquivalence()
        assert p.matches("True and x", "x", {})

    def test_x_or_false(self):
        p = RedundantBooleanEquivalence()
        assert p.matches("x or False", "x", {})

    def test_non_trivial_no_match(self):
        p = RedundantBooleanEquivalence()
        assert not p.matches("x and y", "x or y", {})


class TestStringLiteralEquivalence:
    def test_raise_message_change(self):
        p = StringLiteralEquivalence()
        assert p.matches(
            'raise ValueError("must be positive")',
            'raise ValueError("must be non-negative")',
            {},
        )

    def test_raise_type_change_no_match(self):
        p = StringLiteralEquivalence()
        assert not p.matches(
            'raise ValueError("bad")',
            'raise TypeError("bad")',
            {},
        )


class TestDeadCodeEquivalence:
    def test_after_return(self):
        p = DeadCodeEquivalence()
        context = {"preceding_lines": ["    return 42", "    x = 10"]}
        # The preceding line before the mutation is "x = 10", and before that is "return 42"
        # This heuristic checks the last non-blank non-comment line
        assert not p.matches("y = 20", "y = 30", context)

    def test_immediately_after_return(self):
        p = DeadCodeEquivalence()
        context = {"preceding_lines": ["    return 42"]}
        assert p.matches("x = 10", "x = 20", context)


class TestClassifyMutant:
    def test_equivalent_off_by_one(self):
        result = classify_mutant("x < 10", "x <= 9", 5, "test.py")
        assert result["verdict"] == "equivalent"
        assert result["pattern"] == "off_by_one"

    def test_inconclusive_mutation(self):
        result = classify_mutant("total += amount", "total -= amount", 10, "test.py")
        assert result["verdict"] == "inconclusive"
        assert result["confidence"] == "needs_review"
        assert "classification_prompt" in result


class TestBatchClassification:
    def test_mixed_batch(self):
        mutants = [
            {"original": "x < 10", "mutated": "x <= 9", "line": 5},
            {"original": "total += amount", "mutated": "total -= amount", "line": 10},
        ]
        result = classify_surviving_mutants(mutants, "nonexistent.py")
        assert result["total_surviving"] == 2
        assert result["equivalent"] == 1
        assert result["inconclusive"] == 1
        assert result["effective_surviving"] == 1
