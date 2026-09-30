# HarmonyOS System Capability Routing

Use this reference whenever an in-scope Android behavior reaches an Android framework API, system service, permission, OS-managed side effect, native library, or JVM-only SDK and HarmonyOS/OpenHarmony is a required target.

## Principle

`expect/actual` is only a source-set boundary. It is not an implementation decision and must never satisfy a platform acceptance item by itself.

Resolve every Harmony capability through this order:

1. Reuse an existing production implementation in the target.
2. Use a verified KMP library with the required `ohosArm64` variant and runtime semantics.
3. Use a verified Harmony native/ArkTS package from the external-capability registry through a typed host bridge when it is not a KMP library.
4. Call a verified Harmony Native C API from `ohosMain` through Kotlin/Native platform bindings or `cinterop`.
5. Call a verified ArkTS system Kit through a typed ArkTS/NAPI bridge when the capability belongs to Ability, WindowStage, permission UI, lifecycle, or another ArkTS-only surface.
6. Use a documented C API + ArkTS hybrid when native data processing and host lifecycle/system integration are both required.
7. Mark the capability blocked only after the preceding production routes have concrete unavailable or insufficient evidence.

Do not choose a route from memory. Inspect the target's installed SDK/API level, native headers and libraries, ArkTS declaration files, existing `harmonyApp` host code, and build configuration before recording symbols or signatures.

When the KMP foundation catalog has no match, use `knowledge-query` with `mode: external` and the required capability query before declaring the capability unavailable. The [external catalog](external-capabilities/index.json) provides matching records/cookbooks; its upstream standalone probe is explicitly unsupported. Plan target-local checks as frozen TASK/PATH/ASSERT and execute them through Test-Runner. Registry evidence can nominate a route; only target compile/package/runtime evidence can verify it.

For example, `@ohos/webrtc` is an ArkTS HAR backed by native libraries, not an `ohosMain` KMP dependency. Its contract route is `arkts_bridge` (or `hybrid_capi_arkts` when additional native processing is introduced), with WebRTC ownership in the Harmony host and a bounded typed bridge from KMP.

## Canonical Contract

Spec-Designer records every required Harmony capability decision in the allocated module/task Adhesive analysis and frozen OpenSpec design/tasks. Bind each decision to source evidence, CASE/PATH/ASSERT and implementation guidance; use the [SDD knowledge mapping](sdd-adaptation.md).

Each decision records:

- Android source evidence and affected acceptance ids.
- Required Harmony target and semantic capability.
- All checked production routes.
- One selected route: `reuse_existing`, `kmp_library`, `ohos_capi`, `arkts_bridge`, `hybrid_capi_arkts`, `blocked`, or `out_of_scope`.
- Target SDK version, API surface, symbols/coordinates and evidence path.
- Common boundary, OHOS implementation, production DI/factory binding, generated files, errors, threading, cancellation and lifecycle semantics.
- Capability-specific runtime checks and whether runtime verification is required.

`wrap_with_expect_actual`, “use LocationKit”, “use native API”, or “implement in ArkTS later” without this closure is an unresolved plan and blocks implementation.

## Implementation Surfaces

### KMP library

- Keep platform-neutral API/serialization/domain code in `commonMain`.
- Put engine/driver construction in `ohosMain` when target-specific.
- Use the pinned Harmony foundation coordinate and API knowledge.
- Verify transitive native libraries and runtime behavior, not only Gradle metadata.

### OHOS C API

- Keep the semantic interface in `commonMain`.
- Implement the production adapter in `ohosMain`.
- Use the target SDK's generated platform bindings when available; otherwise add a bounded `.def` and native wrapper.
- Record included headers, libraries, symbols, memory ownership, callback threading, error conversion and cancellation behavior.
- Verify link symbols and exercise the real capability on `ohosArm64`.

### ArkTS Bridge

- Keep Ability, WindowStage, permission prompt and ArkTS Kit calls in `harmonyApp`.
- Add the smallest typed bridge between `ohosMain` and ArkTS; do not expose arbitrary script evaluation.
- Use request ids for asynchronous calls and guarantee exactly one success/error/cancellation completion.
- Propagate Ability/window lifecycle and unregister callbacks when the owning scope is destroyed.
- Record Kotlin, native/NAPI, ArkTS, manifest and module registration files in the submitted implementation task_trace/dimension_evidence and referenced production-binding evidence.

### Hybrid

- Use C API for native processing or data plane work.
- Use ArkTS for host lifecycle, UI-mediated authorization and system integration.
- Define one production boundary so callers do not choose between the two paths.

## Platform-First Slice Order

For a slice with any required platform capability:

1. Inspect and record the SDK route.
2. Implement the smallest production platform adapter.
3. Wire the adapter through DI/factory/repository to the common behavior.
4. Complete the state and CMP UI that consume this production route.
5. Submit the implementation with the platform closure and TASK evidence.
6. After implementation acceptance, Test-Runner runs the frozen narrow compile/link/HAP and runtime PATHs before claiming platform fidelity. Keep normal SDD coding-before-testing gates; the domain ordering does not create an extra execution phase.

UI-first fixture flow remains allowed only for a contract-authorized renderable fallback. It cannot cover a platform-host acceptance item or make a missing production adapter implemented.

## Gate Rules

An implemented Harmony capability requires:

- a matching frozen Adhesive item and submitted implementation task_trace/dimension_evidence;
- real `ohosMain` or `harmonyApp` target files;
- exact production binding and used SDK symbols;
- focused test references and executed gate evidence;
- no fixed `false`, `null`, `404`, no-op, in-memory-only, always-throwing or unavailable default implementation;
- required target compile/link and current HAP packaging;
- matching formal PATH/ASSERT results and execution receipts in the current Ledger;
- successful device/runtime evidence when `runtimeVerificationRequired` is true.

Missing device, SDK, signing or hardware is Yellow with a concrete root cause and no fabricated execution. Apply the existing SDD build/automation distinction and repair budget; automation unavailable follows the deferred path and does not block unrelated tasks or Auditor review. It cannot produce Green for an unexecuted path.

Do not promote a component-level probe to end-to-end acceptance. WebRTC factory initialization and local camera capture can be device-verified while SDP/ICE negotiation, SFU publication, audio device integration or video rendering remain blocked. Record those statuses separately.
