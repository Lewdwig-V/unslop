"""Mason-generated black-box tests for retry_v1.

Generated from: src/retry_v1.py.behaviour.yaml
Source code access: NONE (Chinese Wall enforced)
Mock budget: stdlib + boundaries.json only
"""

from unittest.mock import patch

from src.retry_v1 import retry, retry_with_timeout, RetryError


# ---------------------------------------------------------------------------
# Helpers (Mason can infer these from interface + constraint descriptions)
# ---------------------------------------------------------------------------


class _Failer:
    """Callable that fails n times then succeeds."""

    def __init__(self, fail_count, result="ok"):
        self.fail_count = fail_count
        self.calls = 0
        self.result = result

    def __call__(self):
        self.calls += 1
        if self.calls <= self.fail_count:
            raise ConnectionError(f"fail #{self.calls}")
        return self.result


class _FakeResponse:
    """Duck-typed response with status_code attribute."""

    def __init__(self, status_code):
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Constraint: fn succeeds on first call -> returns result immediately
# ---------------------------------------------------------------------------


def test_succeeds_on_first_call():
    assert retry(lambda: "ok") == "ok"


def test_no_sleep_on_first_success():
    sleeps = []
    with patch("src.retry_v1.time.sleep", side_effect=lambda d: sleeps.append(d)):
        retry(lambda: "ok")
    assert sleeps == [], "Should not sleep when fn succeeds on first call"


# ---------------------------------------------------------------------------
# Constraint: fn raises Exception, succeeds on second -> returns after retry
# ---------------------------------------------------------------------------


def test_succeeds_after_one_failure():
    failer = _Failer(fail_count=1)
    result = retry(failer, base_delay=0.001, jitter=False)
    assert result == "ok"
    assert failer.calls == 2


# ---------------------------------------------------------------------------
# Constraint: fn raises Exception on all attempts -> RetryError
# ---------------------------------------------------------------------------


def test_raises_retry_error_after_exhaustion():
    failer = _Failer(fail_count=100)
    try:
        retry(failer, max_retries=3, base_delay=0.001, jitter=False)
        assert False, "should have raised RetryError"
    except RetryError as e:
        assert e.attempts == 3
        assert isinstance(e.last_exception, ConnectionError)


# ---------------------------------------------------------------------------
# Constraint: max_retries = 1 -> one attempt, no retries, no sleep
# ---------------------------------------------------------------------------


def test_max_retries_one_no_retry():
    failer = _Failer(fail_count=100)
    sleeps = []
    with patch("src.retry_v1.time.sleep", side_effect=lambda d: sleeps.append(d)):
        try:
            retry(failer, max_retries=1, base_delay=1.0)
            assert False, "should have raised"
        except RetryError:
            pass
    assert failer.calls == 1
    assert sleeps == [], "Should not sleep with max_retries=1"


# ---------------------------------------------------------------------------
# Constraint: max_retries = 0 -> RetryError immediately
# ---------------------------------------------------------------------------


def test_max_retries_zero():
    call_count = 0

    def fn():
        nonlocal call_count
        call_count += 1
        return "ok"

    try:
        retry(fn, max_retries=0, base_delay=1.0)
        assert False, "should have raised RetryError"
    except RetryError as e:
        assert e.last_exception is None
        assert e.attempts == 0
    assert call_count == 0, "Should not call fn when max_retries=0"


# ---------------------------------------------------------------------------
# Constraint: status_code >= 500 -> retryable
# ---------------------------------------------------------------------------


def test_server_error_is_retried():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            return _FakeResponse(503)
        return _FakeResponse(200)

    with patch("src.retry_v1.time.sleep"):
        result = retry(fn, max_retries=5, base_delay=0.001)
    assert result.status_code == 200
    assert len(calls) == 3


# ---------------------------------------------------------------------------
# Constraint: status_code in 400..499 -> does NOT retry
# ---------------------------------------------------------------------------


def test_client_error_not_retried():
    """THE 404 BUG TEST: behaviour.yaml says 4xx must not be retried."""
    calls = []

    def fn():
        calls.append(1)
        return _FakeResponse(404)

    with patch("src.retry_v1.time.sleep"):
        result = retry(fn, max_retries=3, base_delay=0.001)

    # Must return on first call -- no retries for client errors
    assert len(calls) == 1, f"Called {len(calls)} times -- 404 should not trigger retry"
    assert result.status_code == 404


def test_400_not_retried():
    calls = []

    def fn():
        calls.append(1)
        return _FakeResponse(400)

    with patch("src.retry_v1.time.sleep"):
        retry(fn, max_retries=3, base_delay=0.001)

    assert len(calls) == 1, "400 should not trigger retry"


def test_499_not_retried():
    calls = []

    def fn():
        calls.append(1)
        return _FakeResponse(499)

    with patch("src.retry_v1.time.sleep"):
        retry(fn, max_retries=3, base_delay=0.001)

    assert len(calls) == 1, "499 should not trigger retry"


# ---------------------------------------------------------------------------
# Constraint: KeyboardInterrupt propagates immediately
# ---------------------------------------------------------------------------


def test_keyboard_interrupt_propagates():
    def fn():
        raise KeyboardInterrupt()

    try:
        retry(fn, max_retries=3, base_delay=0.001)
        assert False, "should have propagated KeyboardInterrupt"
    except KeyboardInterrupt:
        pass  # correct
    except RetryError:
        assert False, "KeyboardInterrupt should not be caught as RetryError"


# ---------------------------------------------------------------------------
# Constraint: SystemExit propagates immediately
# ---------------------------------------------------------------------------


def test_system_exit_propagates():
    def fn():
        raise SystemExit(1)

    try:
        retry(fn, max_retries=3, base_delay=0.001)
        assert False, "should have propagated SystemExit"
    except SystemExit:
        pass  # correct
    except RetryError:
        assert False, "SystemExit should not be caught as RetryError"


# ---------------------------------------------------------------------------
# Invariant: delay never exceeds max_delay
# ---------------------------------------------------------------------------


def test_delay_capped_by_max_delay():
    delays = []
    with patch("src.retry_v1.time.sleep", side_effect=lambda d: delays.append(d)):
        failer = _Failer(fail_count=9)
        try:
            retry(failer, max_retries=10, base_delay=1.0, jitter=False)
        except RetryError:
            pass

    for delay in delays:
        # Behaviour says max_delay exists and caps delay.
        # Mason doesn't know the default max_delay value, but can assert
        # delay doesn't grow unbounded. With base_delay=1.0 and 10 retries,
        # uncapped delay would be 512s on attempt 9. Any reasonable max_delay
        # should keep it well below that.
        assert delay <= 120.0, f"delay {delay}s suggests no max_delay cap"


# ---------------------------------------------------------------------------
# Invariant: delay = base_delay * 2^attempt (before jitter)
# ---------------------------------------------------------------------------


def test_exponential_backoff_without_jitter():
    delays = []
    with patch("src.retry_v1.time.sleep", side_effect=lambda d: delays.append(d)):
        failer = _Failer(fail_count=3)
        try:
            retry(failer, max_retries=4, base_delay=1.0, jitter=False)
        except RetryError:
            pass

    # Without jitter, delays should be exactly base_delay * 2^attempt
    expected = [1.0, 2.0, 4.0]
    for i, (actual, exp) in enumerate(zip(delays, expected)):
        assert abs(actual - exp) < 0.01, f"attempt {i}: expected {exp}, got {actual}"


# ---------------------------------------------------------------------------
# Invariant: half-jitter range [0.5 * delay, delay]
# ---------------------------------------------------------------------------


def test_half_jitter_range():
    all_delays = []
    for seed in range(100):
        delays = []
        with patch("src.retry_v1.time.sleep", side_effect=lambda d: delays.append(d)):
            failer = _Failer(fail_count=1)
            try:
                retry(failer, max_retries=2, base_delay=1.0, jitter=True)
            except RetryError:
                pass
        all_delays.extend(delays)

    # Half-jitter: delay in [0.5 * cap, cap] where cap = base_delay * 2^0 = 1.0
    # So delay should be in [0.5, 1.0]
    for d in all_delays:
        assert 0.49 <= d <= 1.01, f"delay {d} outside half-jitter range [0.5, 1.0]"


# ---------------------------------------------------------------------------
# Property: each call is independent
# ---------------------------------------------------------------------------


def test_independent_calls():
    failer1 = _Failer(fail_count=2)
    failer2 = _Failer(fail_count=0)

    with patch("src.retry_v1.time.sleep"):
        result1 = retry(failer1, max_retries=3, base_delay=0.001)
        result2 = retry(failer2, max_retries=3)

    assert result1 == "ok"
    assert result2 == "ok"
    assert failer1.calls == 3
    assert failer2.calls == 1


# ---------------------------------------------------------------------------
# RetryError invariants
# ---------------------------------------------------------------------------


def test_retry_error_preserves_exception():
    original_exc = ValueError("test error")

    def fn():
        raise original_exc

    try:
        retry(fn, max_retries=2, base_delay=0.001, jitter=False)
    except RetryError as e:
        assert e.last_exception is original_exc
        assert e.attempts == 2


# ---------------------------------------------------------------------------
# retry_with_timeout constraints
# ---------------------------------------------------------------------------


def test_timeout_returns_on_success():
    result = retry_with_timeout(lambda: "ok", timeout=10.0)
    assert result == "ok"


def test_timeout_raises_on_expiry():
    call_count = 0

    def slow_fn():
        nonlocal call_count
        call_count += 1
        raise ConnectionError("fail")

    # Mock time.time to simulate elapsed time exceeding timeout
    time_values = [0.0, 0.0, 5.0, 5.0, 35.0]  # starts at 0, exceeds 30s timeout
    with patch("src.retry_v1.time.time", side_effect=time_values):
        with patch("src.retry_v1.time.sleep"):
            try:
                retry_with_timeout(slow_fn, timeout=30.0, max_retries=10, base_delay=0.001, jitter=False)
                assert False, "should have raised"
            except TimeoutError:
                pass  # correct
            except RetryError:
                pass  # also acceptable if timeout wraps as RetryError
