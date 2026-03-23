# retry_v1.py spec

## Purpose

Provides retry-with-backoff for unreliable operations. Exposes `retry()` for basic retries and `retry_with_timeout()` for time-bounded retries.

## Behavior

### retry(fn, max_retries, base_delay, jitter)

1. Calls `fn()` up to `max_retries` times (default 3).
2. If `fn()` succeeds, returns its result immediately.
3. If `fn()` raises an exception and retries remain, waits for a computed delay before the next attempt.
4. If all retries are exhausted, raises `RetryError` wrapping the last exception.

#### Delay computation

Delay follows exponential backoff: `base_delay * 2^attempt`.

- `base_delay` defaults to `1.0` seconds.
- Delay must have a finite upper bound (`max_delay` parameter). [see Legacy Smell LS-2]
- Attempt numbering is zero-indexed (first retry is attempt 0, so initial delay = base_delay).

#### Jitter

When `jitter=True` (default), delay is randomized to prevent thundering herds.

- Jitter range: `[0.5 * computed_delay, computed_delay]` (half-jitter -- preserving original behaviour).
- Both the randomness source and the delay mechanism must be injectable. [see Legacy Smell LS-4]

#### Exception filtering

Only `Exception` subclasses are caught for retry purposes. `BaseException` subclasses (`KeyboardInterrupt`, `SystemExit`, `GeneratorExit`) must propagate immediately. [see Legacy Smell LS-3]

#### HTTP response handling

If `fn()` returns an object with a `status_code` attribute:
- Server errors (5xx) are retryable -- raise an internal error and retry.
- Client errors (4xx) must NOT be retried -- return the response or raise immediately. [see Legacy Smell LS-1]

### retry_with_timeout(fn, timeout, **kwargs)

Wraps `fn` with a timeout guard. If total elapsed time exceeds `timeout` seconds, raises `TimeoutError` instead of calling `fn` again. Delegates to `retry()` for the actual retry logic.

- Time source must be injectable, not wall-clock dependent. [see Legacy Smell LS-5]

## Constraints

- `max_retries` must be at least 1 (a value of 1 means one attempt, no retries).
- Delay is computed only between attempts, never before the first call or after the last failure.
- No global mutable state. Each call to `retry()` is independent.
- `RetryError.last_exception` preserves the original exception. `RetryError.attempts` records the attempt count.

## Dependencies

- `random` (stdlib) -- for default jitter RNG
- `time` (stdlib) -- for default sleep and timeout

## Error Handling

- Retryable exceptions: all `Exception` subclasses from `fn()`.
- Non-retryable: `KeyboardInterrupt`, `SystemExit`, `GeneratorExit` -- must propagate.
- On final failure: raises `RetryError` wrapping the last exception (not re-raising the original).
- HTTP client errors (4xx): not retried, surfaced immediately.

## Legacy Smells (flagged during takeover)

The following behaviours were extracted from the original code but **contradict project principles**. They are excluded from the behaviour.yaml and will NOT be preserved during regeneration:

- **LS-1:** Original retries on ALL HTTP status >= 400 including 4xx client errors. Principle: "Never retry on client errors (HTTP 4xx)."
- **LS-2:** Original has no `max_delay` parameter. Delay grows unbounded. Principle: "All retry delays must have a finite upper bound."
- **LS-3:** Original catches `BaseException`. Principle: "Never catch BaseException -- use Exception."
- **LS-4:** Original calls `time.sleep()` directly with no injectable alternative. Principle: "Delay mechanisms must be injectable."
- **LS-5:** `retry_with_timeout` uses `time.time()` directly. Principle: "No wall-clock time dependencies. Use injectable time sources."
