"""Retry module with exponential backoff and optional jitter.

NOTE: This file is a DELIBERATE stress-test fixture containing intentional bugs.
Do not fix them -- they exist to validate the testless takeover pipeline.
See docs/superpowers/specs/2026-03-23-testless-takeover-design.md for context.
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
    """Retry fn with exponential backoff."""
    last_exc = None

    for attempt in range(max_retries):
        try:
            result = fn()

            if hasattr(result, "status_code"):
                if result.status_code >= 400:
                    raise _HttpError(result.status_code, "HTTP error")

            return result

        except BaseException as exc:
            last_exc = exc

            if attempt < max_retries - 1:
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
    """Retry fn but abort if total elapsed time exceeds timeout."""
    start = time.time()

    def _wrapped():
        if time.time() - start > timeout:
            raise TimeoutError(f"Retry timed out after {timeout}s")
        return fn()

    return retry(_wrapped, **kwargs)
