# UI and Screenshot Determinism

Use this reference only when the active work packet names `ui-screenshot-determinism`.

## Deterministic evidence

- Fix clock, locale, timezone, random seeds and generated identifiers.
- Freeze or explicitly advance animation progress.
- Use deterministic test providers for an explicitly declared capture fixture. Keep fixture provenance and production behavior checks separate; fixture screenshots do not prove online services/provider fidelity.
- Plan screenshots for meaningful stable states such as content, empty and error. Loading, skeletons, brief progress and transition animations remain implemented behavior and require state-transition/semantic assertions; they become screenshot targets only when the frozen SPEC explicitly requires a reproducible visual state with source-backed trigger and capture condition. Do not add fake delay or change production timing to make a transient state capturable.
- Use UI semantics and callback assertions for behavior; reserve screenshots for visual properties
  that semantics cannot prove.
- Keep test-clock waits separate from real wall-clock or external-device waits.

Spec-Designer classifies stable versus transient targets before freeze and records the corresponding behavior/visual PATHs. Test-Runner performs the frozen checks and read-only comparison through the existing SDD flow. A missing transient screenshot is not itself a visual failure when no such screenshot was required; required behavior checks must still execute or be recorded Yellow/unexecuted. Use the [SDD knowledge mapping](../sdd-adaptation.md).

## Validation

Reject screenshot evidence that depends on current time, live services, uncontrolled animation or
remote assets. Record fixture provenance so deterministic traffic cannot appear as production
network evidence.

Source review informed by
[rcosteira79/android-skills android-testing](https://github.com/rcosteira79/android-skills/blob/main/plugins/android-skills/skills/android-testing/SKILL.md).
