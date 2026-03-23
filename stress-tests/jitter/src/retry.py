# Legacy retry module — exponential backoff WITHOUT jitter.
# This is the "before" state for the Jitter Stress Test.
# The takeover pipeline will lift this into specs, then lower it
# back with jitter added.

import time
from dataclasses import dataclass
from typing import Callable, TypeVar, Optional

T = TypeVar("T")


class MaxRetriesExceeded(Exception):
    """Raised when the retry loop exhausts all attempts."""

    def __init__(self, attempts: int, last_error: Exception):
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Operation failed after {attempts} attempts: {last_error}"
        )


@dataclass(frozen=True)
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0

    def __post_init__(self):
        if self.max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        if self.base_delay <= 0:
            raise ValueError("base_delay must be > 0")
        if self.max_delay < self.base_delay:
            raise ValueError("max_delay must be >= base_delay")


def retry(
    operation: Callable[[], T],
    config: Optional[RetryConfig] = None,
) -> T:
    """Execute an operation with exponential backoff retry.

    WARNING: No jitter — susceptible to thundering herd.
    All failed clients retry at the exact same intervals,
    creating synchronized retry storms.
    """
    if config is None:
        config = RetryConfig()

    last_error: Optional[Exception] = None

    for attempt in range(config.max_retries):
        try:
            return operation()
        except Exception as e:
            last_error = e
            if attempt < config.max_retries - 1:
                # Pure exponential — no randomness
                delay = min(
                    config.base_delay * (2 ** attempt),
                    config.max_delay,
                )
                time.sleep(delay)

    raise MaxRetriesExceeded(config.max_retries, last_error)
