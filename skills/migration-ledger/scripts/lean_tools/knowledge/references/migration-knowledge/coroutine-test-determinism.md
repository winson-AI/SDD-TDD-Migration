# Coroutine Test Determinism

Use this reference only when the active work packet names `coroutine-test-determinism`.

## Test rules

- Drive suspend work with a test scheduler; do not use sleeps as synchronization.
- Ensure the code under test and the test body advance the same scheduler.
- Inject or bind dispatchers so the test controls queued work.
- Collect hot streams in a scope that is cancelled at test completion.
- Advance queued work deliberately before asserting terminal state.
- Test cancellation, retry exhaustion and inactive-collector behavior when contracted.

The exact test library is target- and project-specific. Do not introduce an Android-only runner
into common or Harmony tests merely because an example uses one.

## Validation

Record the scheduler/dispatcher arrangement and the behavior transitions exercised. A zero-exit
test that never collects the stream or advances the owning scheduler is not evidence for the
asynchronous contract.

Source review informed by
[rcosteira79/android-skills android-testing](https://github.com/rcosteira79/android-skills/blob/main/plugins/android-skills/skills/android-testing/SKILL.md).
This is determinism guidance, not an absolute test-first policy.
