# MPCore Harmony Back Navigation

Use this capability only when Harmony/OHOS is required, the target exposes MPCore Compose host
surfaces, and at least one of these behavior triggers is present:

- the selected Android scope has observable back behavior;
- the migration preserves or introduces a user-visible route stack whose inner destinations need
  platform back dispatch;
- the approved Spec explicitly requires platform back or an edge-back gesture.

Do not enable it for every migration. Inspect the installed target dependency and declarations because MPCore APIs may differ by version.

## Capability contract

Use capability id `system.navigation.back`. Inspect the target before generating anything and make
one decision:

| Decision | Select when | Allowed change |
| --- | --- | --- |
| `reuse_existing` | A single acyclic ArkTS-to-KMP route already has correct ownership and consumption | Wire the migrated navigation state to it; do not add another route |
| `repair_existing` | Relevant handlers already exist but dispatch cycles, duplicates, fixed consumption or misses the active stack owner | Repair the existing route in place |
| `generate_boundary` | The installed target API is proven available but no reusable route exists | Add only the smallest missing source-set/host boundary |
| `blocked` | The installed API cannot support the approved behavior and no supported route is proven | Report the exact unavailable surface |

When the installed MPCore host already provides `ArkUIViewController.onBackPress()` and a Compose
`BackHandler`, prefer `reuse_existing` or `repair_existing`; do not create a parallel ArkTS, NAPI/C,
or Compose dispatch path.

Analysis must record:

- Android sources such as `OnBackPressedDispatcher`, Activity/Fragment `onBackPressed`, Compose `BackHandler`, navigation `popBackStack`, drawer/dialog/player dismissal, and root exit behavior;
- consumption priority and the condition under which each owner is enabled;
- the installed MPCore coordinate/version or target files that prove the API exists;
- the ArkTS page entry, KMP handler, common navigation owner, host fallback owner, lifecycle calls, generated surfaces, and runtime checks.

If the installed MPCore surface does not provide these APIs, return to normal Harmony capability routing. Do not invent compatible signatures or label a custom bridge `reuse_existing`.

## Ownership model

One physical/system back event flows in one direction:

```text
ArkTS page onBackPress
  -> ArkUIViewController.onBackPress exactly once
  -> enabled KMP BackHandler, if any
  -> Compose host onBackPressed fallback, if configured
  -> ArkTS navigation/system default
```

Use explicit priority: transient overlay/dialog/player mode, then the innermost KMP screen, then the KMP root stack, then the ArkTS shell, then the system. Only the active highest-priority owner is enabled. Return or report consumed only when that owner actually handled the event.

The `Compose.onBackPressed` callback is a fallback from Compose to the host. It must not call `ArkUIViewController.onBackPress()` or any helper that redispatches to that controller. A re-entry flag hides a cycle; it does not make the cycle correct.

## Generation pattern

Reuse an existing target back abstraction when present. Otherwise generate the smallest boundary required by the target source sets.

Common declaration:

```kotlin
@Composable
expect fun PlatformBackHandler(
    enabled: Boolean,
    onBack: () -> Unit,
)
```

Harmony actual, after confirming the installed import and signature:

```kotlin
import androidx.compose.ui.backhandler.BackHandler

@Composable
actual fun PlatformBackHandler(enabled: Boolean, onBack: () -> Unit) {
    BackHandler(enabled = enabled, onBack = onBack)
}
```

Use the Android target's supported handler for its actual. Register handlers next to the state they consume, for example only while an overlay is visible or `backStack.size > 1`; do not register one unconditional root pop.

ArkTS page entry:

```typescript
onBackPress(): boolean {
  const controller = this.controller
  return controller ? controller.onBackPress() : false
}
```

Configure `Compose({ controller, ... })` with either no host callback at the root or a host-only fallback that pops an ArkTS-owned route. Match the installed declaration's return type. The fallback may return `false`/leave the event unconsumed so the system closes the root page; it must never redispatch to `controller.onBackPress()`.

Keep one stable controller for the page lifetime. Forward the target template's required page/surface lifecycle calls, including `onPageShow` and `onPageHide` when exposed, and release/finalize through the existing host lifecycle rather than creating a controller per recomposition.

## Forbidden generated shapes

- `onBackPress -> controller.onBackPress -> onBackPressed -> controller.onBackPress`;
- re-entry guards added only to tolerate that callback cycle;
- polling KMP state to decide whether ArkTS should dispatch back;
- a custom NAPI/C callback for back when the installed MPCore route already supports it;
- unconditional `true`, unconditional stack pop, duplicate dispatch, or two active owners for one event;
- treating a compiled `expect/actual` pair as runtime proof.

## Gates

Static inspection must always prove one ArkTS-to-controller dispatch path and no fallback edge back
to the controller. Runtime device checks are required only for interactions explicitly declared by
the approved Spec; do not add a device gesture merely because this topic was loaded. For each
declared interaction, cover its applicable outcome:

1. an inner KMP destination pops exactly once and consumes the event;
2. the KMP root leaves the event unconsumed so the ArkTS shell or system handles it;
3. an overlay/dialog/player handler wins before the navigation stack;
4. repeated back events do not recurse, double-pop, or use a stale controller;
5. hide/show lifecycle does not leave a dead or duplicate handler.

A missing or cyclic implementation is code-owned and routes to `incremental-migrate` followed by `validate`. Missing device/runtime infrastructure is `BLOCKED` only after static and build evidence pass; it must not conceal a code-owned gap.
