---
source-spec: src/retry_v1.py.spec.md
target-language: python
ephemeral: true
---

# retry_v1 Concrete Spec (Raised from Legacy Code)

> Faithful extraction of the current implementation. Bugs included. Do not idealize.

## Strategy

### retry()

Exponential backoff with optional jitter. Loop-based, synchronous.

```pseudocode
FUNCTION retry(fn, max_retries, base_delay, jitter)
    SET last_exc <- None

    FOR attempt <- 0 TO max_retries - 1
        TRY
            SET result <- CALL fn()

            // HTTP response inspection: if result has status_code attribute
            // and status_code >= 400, raise internal _HttpError
            IF result HAS "status_code" AND result.status_code >= 400
                RAISE _HttpError(result.status_code, "HTTP error")
            END IF

            RETURN result

        CATCH BaseException AS exc   // NOTE: catches ALL exceptions including KeyboardInterrupt
            SET last_exc <- exc

            IF attempt < max_retries - 1
                SET delay <- base_delay * (2 ^ attempt)   // NOTE: no upper bound on delay
                IF jitter
                    SET delay <- delay * (0.5 + RANDOM(0, 0.5))
                END IF
                CALL time.sleep(delay)                    // NOTE: not injectable
            END IF
        END TRY
    END FOR

    RAISE RetryError(last_exc, max_retries)
END FUNCTION
```

### retry_with_timeout()

Wraps fn with a wall-clock timeout check before each invocation. Delegates to retry().

```pseudocode
FUNCTION retry_with_timeout(fn, timeout, **kwargs)
    SET start <- time.time()       // NOTE: wall-clock, not injectable

    FUNCTION _wrapped()
        IF time.time() - start > timeout
            RAISE TimeoutError
        END IF
        RETURN CALL fn()
    END FUNCTION

    RETURN CALL retry(_wrapped, **kwargs)
END FUNCTION
```

## Type Sketch

- `RetryError(Exception)` -- raised on exhaustion. Stores `.last_exception` and `.attempts`.
- `_HttpError(Exception)` -- internal. Stores `.status_code` and `.message`. Raised when response has status_code >= 400.

## Patterns

- **Retry loop**: simple for-loop with try/except, no state machine
- **HTTP inspection**: duck-typed via `hasattr(result, "status_code")` -- no explicit type check
- **Jitter**: multiplicative, range [0.5*delay, 1.0*delay] (half-jitter, not full jitter)
- **Timeout**: closure-based wrapper, wall-clock dependent

## Edge Cases (as implemented)

1. `max_retries=0` causes the for-loop to never execute. `last_exc` remains None. `raise RetryError(None, 0)` is raised.
2. `max_retries=1` means one attempt, no retries, no sleep.
3. If `fn()` raises `KeyboardInterrupt`, it is caught and retried (BaseException catch).
4. If `fn()` returns a response with `status_code=404`, it is treated as retryable.
5. Delay on attempt 10 with base_delay=1.0: 1024 seconds (~17 minutes). No cap.
6. `retry_with_timeout` checks timeout before each call but not during sleep -- a long sleep can exceed the timeout.

## Lowering Notes

### python
- `_HttpError` is private (underscore prefix) but structurally exposed via the retry loop
- `retry_with_timeout` uses `**kwargs` pass-through to `retry()`
- No type annotations in the original
- `random.random()` is not seeded and not injectable
