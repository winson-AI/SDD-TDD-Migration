# Coroutine Lifecycle and Cancellation

Use this reference only when the active work packet names `coroutine-lifecycle`.

## Preserve the contract

Identify the owner, start trigger, completion condition, cancellation trigger and dispatcher
boundary for each asynchronous behavior. Prefer a suspend boundary when the caller owns the
lifetime. Use a named longer-lived owner only when source behavior must outlive its caller.

Do not swallow coroutine cancellation while mapping domain or transport errors. Broad error
wrappers must rethrow cancellation before producing a failure result. Use non-cancellable work
only for bounded cleanup after cancellation, never to detach ordinary work from its owner.

Do not translate Android `viewModelScope`, lifecycle scopes or WorkManager mechanically. Preserve
their lifetime semantics through the target's actual lifecycle or scheduler capability.

## Implementation checks

- No anonymous application-wide or global scope replaces a source-owned lifetime.
- Repository and use-case boundaries do not hide unmanaged launches.
- Platform callbacks cancel their native operation when the coroutine is cancelled when supported.
- Dispatcher choice is injected or otherwise controllable by focused tests.
- Error handling distinguishes cancellation from domain and transport failures.

## Validation

Exercise cancellation before completion, owner destruction, error mapping and cleanup. Verify that
cancelled work produces neither a terminal success effect nor a retried background operation unless
the source contract explicitly requires it.

Source review informed by
[rcosteira79/android-skills kotlin-coroutines](https://github.com/rcosteira79/android-skills/blob/main/plugins/android-skills/skills/kotlin-coroutines/SKILL.md).
The migration contract and platform lifecycle evidence remain authoritative.
