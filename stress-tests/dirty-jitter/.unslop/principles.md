# Project Principles

## Error Handling
- Never catch BaseException -- use Exception for retry logic. BaseException includes KeyboardInterrupt and SystemExit which must propagate.
- Never retry on client errors (HTTP 4xx status codes). Only server errors (5xx) and transient network failures are retryable.

## Resilience
- All retry delays must have a finite upper bound (max_delay). Unbounded exponential growth can cause minutes-long waits.
- Delay mechanisms must be injectable for testing. No direct calls to time.sleep without an injectable alternative.

## Architecture
- No wall-clock time dependencies in retry logic. Use injectable time sources for timeout calculations.
