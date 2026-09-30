# RxJava to Coroutines and Flow

Use this reference only when Android source evidence names RxJava types or operators and the active
work packet names `rxjava-to-flow`.

## Analyze before translating

Classify the source chain by:

- cardinality: no value, optional one, exactly one, many;
- hot/cold and replay behavior;
- scheduler changes;
- cancellation/disposal;
- retry/error recovery;
- backpressure;
- shared Subject ownership;
- latest-only versus merge/concat ordering.

Do not map operator names one for one without preserving these dimensions. In particular,
latest-only operators can cancel writes, a behavior subject may represent either state or replayed
events, and a backpressured flowable needs an explicit overflow strategy.

## Implementation checks

- Keep an incremental Rx/Flow boundary when a full conversion would obscure behavior.
- Preserve source subscription timing and disposal ownership.
- Map scheduler boundaries to explicit coroutine dispatchers only when the source behavior depends
  on them.
- Preserve retry count, delay, error selection and exhaustion.
- Re-throw coroutine cancellation during fallback/error conversion.

## Validation

Run characterization tests for source ordering, disposal, burst input, error recovery and terminal
events, then run equivalent target tests. Unclear complex chains remain an analysis unknown; do not
guess a lossy conversion.

Source review informed by
[rcosteira79/android-skills rxjava-migration](https://github.com/rcosteira79/android-skills/blob/main/plugins/android-skills/skills/rxjava-migration/SKILL.md).
