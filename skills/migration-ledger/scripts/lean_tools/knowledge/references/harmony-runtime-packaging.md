# HarmonyOS Runtime And Packaging Consistency

Read this reference when HarmonyOS/OpenHarmony markers are present and the migration produces or validates `harmonyApp`.

## Principle

KMP Gradle declarations are the source of truth for HarmonyOS native targets. Generated `harmonyApp` files must be derived from that source of truth, and packaged output must be checked after `publish*BinariesToHarmonyApp` runs.

Do not rely on template defaults, cached generated files, or manual edits in `harmonyApp/entry/build-profile.json5`.

When `harmonyApp` exists, HarmonyOS package validation includes HAP packaging. A successful `publish*BinariesToHarmonyApp` proves native artifacts were copied into the HarmonyOS app; it does not by itself prove a `.hap` package can be assembled.

Preserve the effective target bundle name during migration. Do not copy Android `applicationId`
into `app.json5` or a product override. Signing configuration and release identity management are
outside this migration workflow.

## Generation Rules

During the assigned Implementer/Fixer task, after SPEC freeze:

- Derive `harmonyApp/entry/build-profile.json5` `abiFilters` from declared KMP HarmonyOS targets and the actually published `entry/libs/` ABI directories.
- If only `ohosArm64()` is required, emit only `arm64-v8a`. Do not keep template `x86_64` unless `ohosX64()` is explicitly required or simulator/x64 support is requested.
- Publish Compose resources from the converted/prepared `.cvr` output, not the source `.xml` resources.
- Ensure publish tasks depend on the resource conversion task, such as `convertXmlValueResources`, before copying resources into `harmonyApp`.
- Add a package-time resource assertion: `entry/src/main/resources/rawfile` must not contain source `.xml` value resources and must contain converted `.cvr` resources when Compose resources are present.
- Apply the platform writable storage contract for databases, caches, downloads, logs, exports, and any other persisted files. Writable locations must come from HarmonyOS app-context APIs, not process current working directory, relative paths, or hard-coded Android/Linux paths.
- Keep library filename parameters distinct from base paths. Known case: SQLDelight `NativeSqliteDriver` `name` must be a simple filename without `/` or path separators, with writable directory supplied through `extendedConfig.basePath`.
- Apply the transitive runtime dependency contract for Android framework or high-level library migrations. Do not keep APIs reachable on HarmonyOS unless their implicit runtime dependency chain is verified for the required HarmonyOS targets.
- Known case: if Android WorkManager behavior is migrated and the target has no verified Room-compatible dependency path, use a platform scheduler behind expect/actual instead of depending on WorkManager internals.
- Known case: Ktor `CIO` is not a safe HarmonyOS/OpenHarmony Kotlin/Native HTTPS engine default. If HarmonyOS-reachable code can construct `HttpClient(CIO)` for `https://` traffic and no exact target TLS provider evidence exists, fail the transitive runtime dependency contract with `native_networking_engine_mismatch` and replace it with target-aware engine selection or a platform actual/blocker.
- Apply the native system library contract for C/C++/interop dependencies. Do not assume sysroot libraries are available because they are common on Android, Linux, iOS, or desktop; verify linkability or bundle/replace/report a blocker.
- Known case: if HarmonyOS native linking reports missing SQLite symbols or the sysroot lacks a linkable `libsqlite3`, bundle a verified SQLite amalgamation static library for the HarmonyOS target and document the source/version.

## Runtime Compatibility Contracts

### Platform Writable Storage Contract

Any migrated feature that writes files must identify:

- File category: database, cache, download, log, export, preference/data store, media, or other.
- Platform-owned writable root from app context or the target project's existing platform abstraction.
- Library API parameter split between filename, directory/basePath, URI, or full path.
- Evidence that common/shared code does not depend on CWD, relative writable paths, hard-coded `/data/...`, or Android-only storage APIs.

### Transitive Runtime Dependency Contract

Any migrated Android API or high-level library must be checked beyond direct compile compatibility:

- Identify implicit runtime dependencies such as Room, SQLite, Lifecycle/Startup, Android services, file locks, media backends, networking engines, notification/permission systems, or platform schedulers.
- Verify each dependency against the required HarmonyOS target matrix.
- For networking engines, verify HTTPS/TLS support on HarmonyOS/OpenHarmony native targets. Ktor `CIO` must not be treated as verified native TLS support without project-specific runtime evidence.
- If the chain is not verified, isolate behind expect/actual, replace with a platform implementation, or record a blocker with source and target evidence.

### Native System Library Contract

Any native or cinterop dependency must be checked at link/package time:

- Identify required system libraries and symbols, such as SQLite, zlib, ssl/crypto, iconv, curl, pthread, dl, log, graphics/media libraries, or vendor SDKs.
- Verify the required HarmonyOS sysroot provides a linkable library and the expected symbols.
- If unavailable, bundle a verified static/dynamic library, replace the dependency, disable an optional capability with justification, or record a blocker.

## Consistency Gate

Run this gate after every successful `publish*BinariesToHarmonyApp` execution and before declaring HarmonyOS package/runtime validation complete.

After the publish gate, attempt HAP packaging from the HarmonyOS app directory when `hvigorw` or `hvigor` is available:

```text
./hvigorw assembleHap
hvigorw assembleHap
hvigor assembleHap
```

Use the wrapper when present. If multiple build modes/products exist, use the target project's default debug/dev flavor unless the user requested a release package. Collect produced `.hap` files from `harmonyApp/**/build/**/outputs/**/*.hap` or the equivalent project output path.

If HAP packaging cannot run, record `hap_packaging_status: BLOCKED` or `SKIPPED_WITH_REASON` with exact evidence. Valid blockers include missing `hvigor`/`hvigorw`, missing DevEco/HarmonyOS SDK, missing signing material, missing Node/npm runtime, or an upstream `publish*BinariesToHarmonyApp` failure. Only a produced and verified HAP artifact can support package Green. A concrete environment blocker remains Yellow/unexecuted with evidence; a failed executed build remains Red. Neither is PASS.

| ID | Check | Failure Classification | Fixer action after assignment |
|---|---|---|---|
| C1 | `build-profile.json5` `abiFilters` is a subset of declared required KMP HarmonyOS targets and published `entry/libs/` ABI directories | `harmony_abi_mismatch` | Rewrite `abiFilters` to the union of published required ABI directories; drop optional x64 unless requested; rerun publish |
| C2 | `rawfile` contains zero source `.xml` value resources and contains `.cvr` resources when converted resources exist | `harmony_resource_format_mismatch` | Rewrite publish copy source to prepared/converted resources, add conversion dependency, rerun publish |
| C3 | Platform writable storage contract passes for all HarmonyOS-reachable file writes; known case: SQLDelight filename/basePath split and app-context DB path | `platform_writable_storage_mismatch` | Route writable roots through app context/platform abstraction, split filename/basePath parameters, rerun affected package/runtime gate |
| C4 | Transitive runtime dependency contract passes for Android/high-level APIs reachable on HarmonyOS; known cases: WorkManager is not kept reachable without verified Room support; Ktor `CIO` is not kept reachable for native `https://` without exact HarmonyOS TLS evidence | `transitive_runtime_dependency_mismatch` / `native_networking_engine_mismatch` | Replace with expect/actual platform implementation, target-aware networking engine, verify dependency chain/TLS support, or report blocker with dependency evidence |
| C5 | Native system library contract passes for all native/cinterop dependencies; known case: SQLite link does not rely on unavailable sysroot `libsqlite3` | `native_system_library_mismatch` | Bundle verified native library, replace dependency, disable optional capability with justification, or report blocker; rerun native link/package |
| C6 | HAP packaging is attempted when `harmonyApp` exists and `hvigorw`/`hvigor` is available; produced `.hap` artifacts are collected or an exact blocker is recorded | `hap_packaging_failed` / `hap_packaging_blocked` | Fix build-profile/signing/SDK/tooling issue when actionable, rerun publish and HAP packaging, or record external blocker with command evidence |
| C7 | Capability-derived permissions are declared in the real entry `module.json5`; production networking includes `ohos.permission.INTERNET` and an installed-HAP `network-smoke` result | `harmony_permission_mismatch` / `harmony_network_runtime_failed` | Repair manifest/runtime authorization handling, reinstall, then rerun the production network path including HTTPS and offline behavior |
| C8 | Explicit `windowPolicy` is implemented consistently by EntryAbility/window setup and CMP inset consumption; `window-insets` covers status/navigation bars and IME | `harmony_window_policy_mismatch` / `harmony_inset_mismatch` | Align host full-screen policy and single inset owner, reinstall, and recapture device evidence |

Retain consistency analysis in the current role's `.sdd-runs/<run_id>/staging/<instance_id>/<request_id>/` using the resolved run root. Test-Runner retains actual build/package commands and evidence in the existing `runs/build` runner, and device evidence in `runs/harmony`. Submit references through the existing Ledger event and PATH/ASSERT result; the OpenSpec hub projects the accepted status. See [SDD knowledge mapping](sdd-adaptation.md).

## Report Requirements

Migration and validation reports must include:

- Declared HarmonyOS KMP targets.
- Published `entry/libs/` ABI directories.
- Final `build-profile.json5` `abiFilters`.
- HAP packaging command, status, and produced `.hap` artifact paths, or exact blocker/skipped reason.
- Resource package check result, including `.xml` and `.cvr` counts under `rawfile`.
- Platform writable storage strategy for HarmonyOS-reachable file writes, including database paths when persistence exists.
- Transitive runtime dependency strategy for Android/high-level APIs, including scheduler strategy when source uses WorkManager or periodic/background jobs.
- Native networking engine strategy when HTTP/Ktor/Retrofit/OkHttp/API clients are reachable, including per-target engine choice and HarmonyOS HTTPS/TLS evidence or blocker.
- Native system library strategy for C/C++/interop dependencies, including SQLite link strategy when SQLDelight, Room, AndroidX SQLite, or native SQLite is reachable on HarmonyOS.
- Harmony host permission closure and device `network-smoke` evidence for production networking.
- `windowPolicy` (`fit_system_bars` or `edge_to_edge`), status/navigation bar behavior, inset owner, IME policy and `window-insets` evidence.

If an assigned Fixer action is applied, Test-Runner reruns the affected publish/build gate and cites both failing and passing evidence. Keep the current repair budget and role separation; this recipe grants no extra retry or write permission.
