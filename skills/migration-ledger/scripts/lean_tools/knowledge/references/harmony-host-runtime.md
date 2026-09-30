# Harmony Host Runtime Contract

KMP compilation and native publication do not make the generated `harmonyApp` runtime-correct. Treat the Harmony host as part of each affected vertical slice: manifest permissions, Ability/window setup, system bars, safe areas, keyboard behavior and device networking are production code.

## Permission closure

Derive permissions from source-backed capabilities and the selected Harmony implementation. Do not copy the Android manifest wholesale and do not retain template permissions without a used capability.

- Internet access requires `ohos.permission.INTERNET` in the entry module's `module.json5` `requestPermissions`.
- Network-state inspection, location, camera, media, notifications and other capabilities may require additional permissions. Resolve exact names and authorization mode against the target Harmony SDK; distinguish manifest-only permissions from user-authorized permissions that also need reason/usedScene and a runtime request/denial path.
- Each permission decision records capability, permission name, declaration site, whether a runtime prompt is required, denial behavior and owning acceptance id.
- A network library compiling is not permission evidence. `network-smoke` must exercise the real production client on a device/emulator, including DNS, HTTPS/TLS, response parsing and the offline/error path.

## Window and system-bar closure

Choose one explicit `windowPolicy` from source behavior and target product intent:

### `fit_system_bars`

Content does not draw behind the status or navigation bar. The Harmony host/window and CMP root must agree on who supplies the safe-area padding. Verify there is no overlap and no double top/bottom padding.

### `edge_to_edge`

The Harmony window deliberately lays content behind system bars. Configure the main window through the target SDK's supported WindowStage/window API, choose status/navigation bar visibility and styling, and make the CMP root consume status, cutout, navigation/gesture and IME insets exactly once. Edge-to-edge does not mean hiding controls under the navigation bar.

Record:

- `systemBars`: status and navigation bar policy;
- `insetOwnership`: Harmony host, CMP root, or a documented split;
- `imePolicy`: resize/pan/overlay behavior;
- orientation, cutout/foldable behavior and bar foreground/background styling when relevant.

## Dynamic full-screen transitions

Model source-driven full-screen as paired `windowPolicy.transitions`, not as `fullscreenSupport: true`. Each enter/exit transition records its trigger, layout mode, visible bars, orientation and Android `sourceEvidenceIds`. An enter transition must describe immersive layout and hidden bars; its exit transition must restore the initial `mode` and `systemBars`.

Execute the policy with the target Harmony SDK's ArkTS `window.Window` APIs. For API 20 projects the relevant host calls are `setWindowLayoutFullScreen(boolean)` and `setWindowSystemBarEnable(Array<'status' | 'navigation'>)`. Inspect the installed SDK before emitting code because signatures and preferred APIs can vary by SDK level.

- Apply the initial static policy after obtaining the main window in `EntryAbility.onWindowStageCreate`.
- On full-screen enter, call `setWindowLayoutFullScreen(true)` and `setWindowSystemBarEnable([])`.
- On exit, restore the contracted initial layout and bars, commonly `setWindowLayoutFullScreen(false)` plus `setWindowSystemBarEnable(['status', 'navigation'])` for `fit_system_bars`.
- Keep these APIs in the ArkTS Harmony host. CMP/common code emits a semantic enter/exit intent through the smallest existing platform bridge; it must not import or imitate Harmony window APIs.
- If the target has no usable runtime bridge and the selected feature requires dynamic full-screen, mark the owning acceptance item `blocked`; do not silently make the whole app permanently immersive.

`Modifier.fillMaxSize()` only fills the Compose constraints supplied by the host. It is never evidence that the Harmony window is edge-to-edge or immersive.

Do not hard-code a remembered Harmony API signature. Inspect the target SDK/API level and existing `EntryAbility.ets`; use the supported window API for that project and retain source evidence for the decision.

## Required implementation surfaces

- `harmonyApp/entry/src/main/module.json5` or the target's real entry manifest.
- `EntryAbility.ets`/main WindowStage setup when the selected policy needs host configuration.
- CMP root/scaffold inset consumption when CMP owns all or part of safe areas.
- Permission request/denial adapter for user-authorized capabilities.

Map these files/symbols to the frozen Adhesive item and TASK in the existing implementation `task_trace` and `dimension_evidence`. Reference the production bindings and platform-host CASE/PATH/ASSERT evidence through Ledger; use the [SDD knowledge mapping](sdd-adaptation.md).

## Device gates

- `network-smoke`: launch the installed HAP and perform a real request through production wiring; retain endpoint class, result, error/log evidence and offline behavior. Do not expose secrets in logs.
- `window-insets`: capture status/navigation bars and first/last interactive content in portrait plus any required orientation; assert no obstruction or double padding.
- `window-fullscreen-transition`: enter full-screen through the migrated user action, assert both system bars are hidden and required orientation is applied, then exit and assert the initial layout, bars and orientation are restored. Retain device evidence for both states.
- Exercise gesture-navigation and three-button/navigation-bar configurations when supported by the target device matrix.
- Exercise IME appearance on screens with text input and confirm focused content/actions remain reachable.

HAP assembly alone cannot satisfy either gate.
