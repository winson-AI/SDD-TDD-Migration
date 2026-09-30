# HarmonyOS / OpenHarmony Targets

Read this reference during pre-flight target-matrix detection and Lean dependency resolution when HarmonyOS/OpenHarmony markers are present.

Also read [harmony-runtime-packaging.md](harmony-runtime-packaging.md) when `harmonyApp` or `publish*BinariesToHarmonyApp` is present. Dependency compatibility alone is not enough to declare HarmonyOS migration readiness.

## Detection Markers

Treat the target as HarmonyOS/OpenHarmony-aware if project files contain any of:

- `ohosArm64()`
- `ohosX64()`
- `ohosMain`
- `harmonyApp`
- `publish*BinariesToHarmonyApp`

## Target Matrix Defaults

- All declared non-Harmony targets are `required` by default, including Android and iOS targets.
- `ohosArm64` is `required` by default for physical-device deployment.
- `ohosX64` is `ignored_unless_requested` unless the user explicitly requests simulator/x64 support.
- Required compile gates do not imply running every platform's native test binary by default.
- Validation gates must separate compile, package/runtime, and test gates.

Dependency compatibility gates must evaluate only required targets. Unsupported optional targets must not cause behavior downgrades, replacement of real implementations, or stubbed APIs.

## Required Knowledge Base

When HarmonyOS/OpenHarmony markers are present, use the bundled [Foundation catalog](foundation-api-knowledge/index.json), its matching cookbook and [API evidence](foundation-api-knowledge/foundation_api_evidence.json) through `knowledge-query` / `foundation-resolve`. The managed result records absolute paths and hashes in `knowledge_refs`; freeze `dependency_resolution_ref` in the SDD plan. Missing selected knowledge is a scoped planning gap. Do not create a separate upstream knowledge-path configuration or guess versions from memory. See [SDD knowledge mapping](sdd-adaptation.md).

## Dependency Resolution Rules

For HarmonyOS/OpenHarmony targets:

- Classify `ohosArm64()`, `ohosX64()`, and `harmonyApp` targets as HarmonyOS KMP.
- Check the HarmonyOS KMP foundation library knowledge base before selecting versions or declaring required KMP libraries unsupported.
- For target-sensitive libraries used by `commonMain`, `ohosMain`, or HarmonyOS-reachable code, use the knowledge-base coordinate/version when available.
- Use the Foundation catalog target_support and hash-bound API evidence to record `ohosArm64` and `ohosX64` support separately. A library with `ohosArm64=yes` and `ohosX64=no` is compatible with the default benchmark target matrix when only `ohosArm64` is required.
- If the template declares `ohosX64()` but the user/benchmark did not require x64, do not let missing x64 variants downgrade behavior or fail migration readiness; remove x64 from required packaging/build gates or mark it `optional_x64_unsupported`.
- Dependency resolution must fail if target-sensitive versions are generated without the matching bundled Foundation catalog/evidence as the hash-bound version source when a matching knowledge-base coordinate exists.
- Dependency resolution must inventory Android-only source dependencies and imports before implementation. At minimum check Hilt/Dagger, Retrofit/OkHttp, Room/SQLite, DataStore/SharedPreferences/MMKV, Coil/Glide/Picasso, WorkManager, Firebase, protobuf/Wire, paging, logging, crypto, and test libraries.
- Each in-scope Android-only dependency must be mapped to one of: `reuse_existing`, `replace_with_foundation_library`, `wrap_with_expect_actual`, `out_of_scope`, or `blocked`.
- Do not replace in-scope persistence, networking, image loading, DI, logging, paging, protobuf, or stream-test behavior with final stubs, fixtures, manual service locators, fake API clients, or placeholders when the foundation library knowledge base lists a production-capable KMP/HarmonyOS library. Use the library or record a concrete build/API blocker and user-visible impact.

Target-sensitive libraries include Ktor, Coil, kotlinx serialization, kotlinx coroutines, Compose Multiplatform, Okio, SQLDelight, Room3, AndroidX SQLite, DataStore, multiplatform-settings, Koin, Kodein, Kermit, paging, Wire/pbandk, Turbine, and image/network/storage libraries.

## Packaging And Runtime Trap Index

Known HarmonyOS runtime/package consistency failures that must be checked by the runtime packaging gate. The last three are examples of broader runtime compatibility contracts, not one-off checks:

- `build-profile.json5` template ABI defaults include `x86_64` while the required KMP HarmonyOS target only publishes `ohosArm64`.
- `publish*BinariesToHarmonyApp` copies source `.xml` resources into `rawfile` instead of converted `.cvr` resources.
- `publish*BinariesToHarmonyApp` succeeds but no HAP packaging command is attempted, so HarmonyOS app assembly/signing/toolchain errors are hidden.
- `NativeSqliteDriver` receives a database name containing a path separator.
- HarmonyOS database base path uses the current working directory instead of app-context writable storage.
- WorkManager is kept reachable on HarmonyOS without a verified Room-compatible dependency path.
- Ktor `CIO` is kept reachable for HarmonyOS native `https://` traffic without exact TLS provider evidence, causing runtime failures such as `tls sessions are not supported on native platform`.
- HarmonyOS native link relies on an unavailable sysroot `libsqlite3` instead of a bundled SQLite library.

Abstract contracts behind those examples:

- Platform writable storage contract: all HarmonyOS-reachable file writes use platform-owned writable roots and correct filename/basePath/URI parameter split.
- Transitive runtime dependency contract: Android/high-level APIs are not kept reachable unless direct and implicit runtime dependencies are verified for required HarmonyOS targets.
- Native networking engine contract: HTTP/Ktor engines reachable on HarmonyOS native targets must have verified HTTPS/TLS support; `HttpClient(CIO)` is not accepted as the default native HTTPS path without target-specific evidence.
- Native system library contract: native/cinterop dependencies verify required sysroot libraries and symbols at link/package time, or use bundled/replaced implementations or blockers.
