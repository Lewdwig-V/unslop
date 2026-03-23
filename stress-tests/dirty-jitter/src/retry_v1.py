"""Legacy retry module -- intentionally buggy for testless takeover stress test.

Bug 1: Retries on HTTP 404 (client error -- should not retry)
Bug 2: No max_delay cap (delay grows unbounded on high attempt counts)
Bug 3: Catches BaseException instead of Exception (swallows KeyboardInterrupt)
"""

import random
import time


class RetryError(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, last_exception, attempts):
        self.last_exception = last_exception
        self.attempts = attempts
        super().__init__(f"Failed after {attempts} attempts: {last_exception}")


def retry(
    fn,
    max_retries=3,
    base_delay=1.0,
    jitter=True,
):
    """Retry fn with exponential backoff.

    Note: this function has several known issues (see module docstring).
    It exists as a stress-test target for testless takeover validation.
    """
    last_exc = None

    for attempt in range(max_retries):
        try:
            result = fn()

            # Bug 1: Checks for HTTP-like response objects and retries on 404.
            # This is wrong -- 404 is a client error and should not be retried.
            if hasattr(result, "status_code"):
                if result.status_code >= 400:
                    raise _HttpError(result.status_code, "HTTP error")

            return result

        # Bug 3: Catches BaseException instead of Exception.
        # This swallows KeyboardInterrupt, SystemExit, and GeneratorExit.
        except BaseException as exc:
            last_exc = exc

            if attempt < max_retries - 1:
                # Bug 2: No max_delay cap. On attempt 10 with base_delay=1.0,
                # delay = 1024 seconds (~17 minutes). Unbounded growth.
                delay = base_delay * (2**attempt)

                if jitter:
                    delay = delay * (0.5 + random.random() * 0.5)

                time.sleep(delay)

    raise RetryError(last_exc, max_retries)


class _HttpError(Exception):
    """Internal HTTP error for retry logic."""

    def __init__(self, status_code, message):
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


def retry_with_timeout(fn, timeout=30.0, **kwargs):
    """Retry fn but abort if total elapsed time exceeds timeout.

    Uses wall-clock time -- not injectable. Another design smell.
    """
    start = time.time()

    def _wrapped():
        if time.time() - start > timeout:
            raise TimeoutError(f"Retry timed out after {timeout}s")
        return fn()

    return retry(_wrapped, **kwargs)
