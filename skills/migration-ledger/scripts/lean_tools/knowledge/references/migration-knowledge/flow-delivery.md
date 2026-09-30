# Flow Delivery Semantics

Use this reference only when the active work packet names `flow-delivery`.

## Preserve the contract

Determine from source evidence whether each stream is:

- state with a current value;
- broadcast to every active collector;
- a single-consumer event;
- a producer-consumer queue.

Record and preserve what happens when no collector is active: drop, buffer, replay, persist, or
unknown. Preserve ordering, replay count, duplicate-consumption behavior and lifecycle ownership.
Do not select `Channel`, `SharedFlow` or `StateFlow` from a project-wide default.

`receiveAsFlow()` distributes elements across collectors; it does not broadcast each element to
all collectors. A replay-zero shared flow can lose an emission when no collector is ready. A
critical result that must survive lifecycle loss belongs in durable state with acknowledgement,
not only in an ephemeral event stream.

For callback-backed streams, unregister or stop the producer when collection ends. If the source
SDK cannot unregister, preserve that limitation in the contract and require a runtime check.

## Implementation checks

- Expose immutable stream types and keep mutable producers private.
- Keep state and one-shot effects distinct.
- Preserve source start/stop and subscription semantics.
- Keep transform operators free of effects that would repeat on resubscription.
- Ensure multi-input streams can produce their first value under the contracted initial state.

## Validation

Exercise inactive-subscriber behavior, collector count, ordering, replay, cancellation and
resubscription. Compilation or the presence of a familiar Flow type is not delivery evidence.

Source review informed by
[rcosteira79/android-skills kotlin-flows](https://github.com/rcosteira79/android-skills/blob/main/plugins/android-skills/skills/kotlin-flows/SKILL.md).
The migration contract and target runtime evidence remain authoritative.
