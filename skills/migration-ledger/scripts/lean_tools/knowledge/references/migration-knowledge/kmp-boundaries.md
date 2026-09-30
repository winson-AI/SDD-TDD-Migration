# KMP Platform Boundaries

Use this reference only when the active work packet names `kmp-boundaries`.

## Boundary rules

- Keep `commonMain` semantic: name the product capability, not Android, iOS or Harmony mechanics.
- Split independent capabilities instead of creating one platform god object.
- Keep platform implementations thin; business decisions remain in shared code and are testable
  with a fake boundary.
- Prefer a common interface plus platform binding when fakes, DI, lifecycle ownership or runtime
  selection are required.
- Add an intermediate source set only when multiple targets share a real implementation.

These rules select the shape of a boundary, not its production route. An interface or
`expect/actual` declaration never proves the selected Harmony KMP-library, CAPI, ArkTS or hybrid
implementation.

## Implementation checks

- No Android framework type leaks into shared APIs.
- Platform resources, lifecycle owners and native handles stay within their owning source set.
- The production graph binds every common capability to a real target implementation.
- Error, cancellation and completion semantics cross the boundary explicitly.
- Platform code contains translation and lifecycle integration, not hidden domain policy.

## Validation

Trace the common call through DI/factory registration into the exact target implementation and its
runtime probe. Reject unused actuals, declaration-only adapters and platform stubs.

Source review informed by
[rcosteira79/android-skills kmp-boundaries](https://github.com/rcosteira79/android-skills/blob/main/plugins/android-skills/skills/kmp-boundaries/SKILL.md).
Harmony capability routing in this migration suite overrides Android/iOS examples.
