"""Tests for retry module.

These tests validate the ABSTRACT spec constraints, not implementation
details. They are designed to survive the jitter upgrade — adding
randomness should not break any of these assertions.
"""

import pytest
from unittest.mock import patch
from src.retry import retry, RetryConfig, MaxRetriesExceeded


class TestRetryConfig:
    def test_default_config(self):
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0

    def test_max_retries_must_be_positive(self):
        with pytest.raises(ValueError, match="max_retries must be >= 1"):
            RetryConfig(max_retries=0)

    def test_base_delay_must_be_positive(self):
        with pytest.raises(ValueError, match="base_delay must be > 0"):
            RetryConfig(base_delay=0)

    def test_max_delay_must_be_gte_base(self):
        with pytest.raises(ValueError, match="max_delay must be >= base_delay"):
            RetryConfig(base_delay=5.0, max_delay=1.0)

    def test_config_is_immutable(self):
        config = RetryConfig()
        with pytest.raises(AttributeError):
            config.max_retries = 10


class TestRetrySuccess:
    def test_returns_on_first_success(self):
        result = retry(lambda: 42)
        assert result == 42

    def test_returns_after_transient_failure(self):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "ok"

        result = retry(flaky)
        assert result == "ok"
        assert call_count == 3


class TestRetryExhaustion:
    def test_raises_after_max_retries(self):
        config = RetryConfig(max_retries=2)

        with pytest.raises(MaxRetriesExceeded) as exc_info:
            retry(lambda: (_ for _ in ()).throw(ValueError("fail")), config)

        assert exc_info.value.attempts == 2
        assert isinstance(exc_info.value.last_error, ValueError)

    def test_error_message_includes_attempts(self):
        config = RetryConfig(max_retries=1)

        with pytest.raises(MaxRetriesExceeded, match="1 attempts"):
            retry(lambda: (_ for _ in ()).throw(RuntimeError("boom")), config)


class TestBackoffBehavior:
    """Tests that validate backoff WITHOUT assuming deterministic delays.

    These tests are designed to pass both with and without jitter.
    They check the BOUNDS of the delay, not the exact value.
    """

    @patch("src.retry.time.sleep")
    def test_delay_is_bounded_by_max(self, mock_sleep):
        config = RetryConfig(max_retries=5, base_delay=1.0, max_delay=10.0)

        with pytest.raises(MaxRetriesExceeded):
            retry(
                lambda: (_ for _ in ()).throw(RuntimeError("fail")),
                config,
            )

        for call in mock_sleep.call_args_list:
            delay = call[0][0]
            assert 0 <= delay <= config.max_delay, f"Delay {delay} exceeds max_delay {config.max_delay}"

    @patch("src.retry.time.sleep")
    def test_delay_is_non_negative(self, mock_sleep):
        config = RetryConfig(max_retries=3, base_delay=0.5)

        with pytest.raises(MaxRetriesExceeded):
            retry(
                lambda: (_ for _ in ()).throw(RuntimeError("fail")),
                config,
            )

        for call in mock_sleep.call_args_list:
            delay = call[0][0]
            assert delay >= 0, f"Delay must be non-negative, got {delay}"

    @patch("src.retry.time.sleep")
    def test_no_sleep_on_last_attempt(self, mock_sleep):
        config = RetryConfig(max_retries=3)

        with pytest.raises(MaxRetriesExceeded):
            retry(
                lambda: (_ for _ in ()).throw(RuntimeError("fail")),
                config,
            )

        # Should sleep max_retries - 1 times (not after the final attempt)
        assert mock_sleep.call_count == config.max_retries - 1


class TestJitterBehavior:
    """Tests that will ONLY pass after jitter is added.

    These tests validate the jitter-specific constraint: delays must
    include randomness to prevent thundering herd.
    """

    @patch("src.retry.time.sleep")
    def test_delays_are_not_all_identical(self, mock_sleep):
        """Run multiple retry sequences and verify delays vary.

        Without jitter, identical configs produce identical delay
        sequences. With jitter, they should differ.
        """
        config = RetryConfig(max_retries=5, base_delay=1.0, max_delay=60.0)
        delay_sequences = []

        for _ in range(10):
            mock_sleep.reset_mock()
            with pytest.raises(MaxRetriesExceeded):
                retry(
                    lambda: (_ for _ in ()).throw(RuntimeError("fail")),
                    config,
                )
            delays = [call[0][0] for call in mock_sleep.call_args_list]
            delay_sequences.append(tuple(delays))

        unique_sequences = set(delay_sequences)
        assert len(unique_sequences) > 1, (
            "All 10 retry sequences produced identical delays — jitter is not working. Delays should vary between runs."
        )

    @patch("src.retry.time.sleep")
    def test_delay_has_lower_bound_of_zero(self, mock_sleep):
        """With full jitter, delay can be as low as 0."""
        config = RetryConfig(max_retries=20, base_delay=1.0, max_delay=60.0)

        with pytest.raises(MaxRetriesExceeded):
            retry(
                lambda: (_ for _ in ()).throw(RuntimeError("fail")),
                config,
            )

        delays = [call[0][0] for call in mock_sleep.call_args_list]
        # At least some delays should be less than the base_delay
        # (with full jitter: sleep = random(0, min(cap, base * 2^attempt)))
        has_sub_base = any(d < config.base_delay for d in delays)
        assert has_sub_base, (
            f"No delays were less than base_delay ({config.base_delay}). "
            f"Full jitter should produce delays in [0, cap). "
            f"Actual delays: {delays}"
        )
