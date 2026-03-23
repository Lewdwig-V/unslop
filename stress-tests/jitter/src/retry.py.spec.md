# retry.py spec

## Purpose

A retry utility that re-executes a failing operation with exponential backoff delays between attempts. Prevents cascading failures by limiting retry attempts and capping delay duration.

## Behavior

- Accepts a callable operation and an optional retry configuration
- Executes the operation; on success, returns the result immediately
- On failure (any exception), waits with exponential backoff before retrying
- Backoff uses Full Jitter to prevent thundering herd: the delay is randomized within the exponential backoff range
- The upper bound for the delay on each attempt is `min(base_delay * 2^attempt, max_delay)`
- The actual delay is a uniform random value between 0 (inclusive) and the upper bound (exclusive)
- Each retry independently samples a new random delay — delays are not correlated across attempts or across callers
- No sleep after the final failed attempt
- If all attempts are exhausted, raises `MaxRetriesExceeded` with the attempt count and last error

## Constraints

- `max_retries` must be >= 1
- `base_delay` must be > 0
- `max_delay` must be >= `base_delay`
- Delay is always non-negative
- Delay never exceeds `max_delay`
- Configuration is immutable after creation
- Default config: 3 retries, 1.0s base delay, 60.0s max delay

## Error Handling

- `MaxRetriesExceeded` is raised when all retries are exhausted
- The exception carries the total attempt count and the last error encountered
- The error message includes the attempt count

## Open Questions

None — all previously open questions have been resolved.
