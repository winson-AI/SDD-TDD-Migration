# Retry and Backpressure Semantics

Use this reference only when the active work packet names `retry-backpressure`.

## Preserve the contract

Trace retry eligibility, maximum attempts, delay/backoff, cancellation, exhaustion behavior and
which errors are retryable. An unbounded retry is valid only when source evidence proves it.

For streams, determine whether the source buffers, conflates, drops oldest/latest, blocks the
producer, switches to the latest request, or applies another backpressure strategy. Preserve the
observable result rather than translating operator names mechanically.

Latest-only cancellation is normally appropriate for replaceable reads such as search. It can be
destructive for writes because a new input may cancel an in-flight mutation.

## Implementation checks

- Bound retries exactly when the source is bounded.
- Keep retry delay on a cancellable path.
- Do not retry authentication refresh recursively or retry permanent failures as transient ones.
- Preserve the source behavior after exhaustion.
- Make buffer/drop/conflate decisions explicit at the boundary.

## Validation

Exercise the first attempt, final permitted retry, exhaustion, cancellation during backoff, burst
input and slow-consumer behavior. A happy-path test cannot close this knowledge requirement.

Source review informed by
[rcosteira79/android-skills kotlin-flows](https://github.com/rcosteira79/android-skills/blob/main/plugins/android-skills/skills/kotlin-flows/SKILL.md)
and its RxJava migration guidance. Source behavior remains authoritative.
