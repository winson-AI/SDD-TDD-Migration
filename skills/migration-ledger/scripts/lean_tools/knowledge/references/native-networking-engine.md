# KMP Networking Engine Compatibility

Read this reference when the Android source or KMP target uses HTTP clients, WebSocket clients, Ktor, Retrofit/OkHttp migrations, generated API clients, download/upload code, auth refresh, or any `https://` network path.

## Principle

Compile compatibility is not network runtime compatibility. Kotlin/JVM engines can rely on JVM TLS providers, while Kotlin/Native targets need a verified native engine and TLS provider for each required platform.

Do not approve a shared networking implementation just because Android/JVM builds and requests work.

## Known Runtime Failure

Ktor `CIO` is not a safe default for Kotlin/Native iOS or HarmonyOS/OpenHarmony HTTPS traffic. On affected native targets it can throw:

```text
tls sessions are not supported on native platform
```

JVM works because it can use JDK TLS support. Native targets must use a target-verified engine or a platform actual implementation.

## Migration Rules

- Do not hard-code `HttpClient(CIO)` in `commonMain` when iOS, HarmonyOS, or another Kotlin/Native target is required.
- Network client construction must be target-aware: use an `expect`/`actual` client or engine factory, target source-set dependency injection, or an existing project platform abstraction.
- For iOS, prefer a verified native-capable engine such as Darwin when using Ktor.
- For Android/JVM, use the target project's existing verified engine such as OkHttp, Android, or a JVM-safe engine.
- For HarmonyOS/OpenHarmony, use only an engine/library combination verified for the required HarmonyOS KMP target. If no verified HTTPS-capable engine exists, record a blocker or route networking through an approved platform actual implementation.
- Every selected engine must be declared in the correct source set. Do not place a JVM-only engine dependency in `commonMain` when native targets consume it.
- If migrating Retrofit/OkHttp source code, separate API shape and serialization from platform engine choice. Preserve request/response behavior, headers, auth refresh, timeouts, retries, cancellation, and error mapping.

## Required Evidence

For every migrated network capability, record:

- Required target matrix: Android/JVM, iOS, HarmonyOS/OpenHarmony, and any other native targets.
- HTTP client library and engine selected per target.
- Source set placement for each engine dependency.
- TLS support evidence or blocker for every required native target.
- At least one `https://` smoke path or test/manual validation plan for each required native target when runtime execution is feasible.
- Failure handling parity: timeout, TLS failure, DNS/network unavailable, HTTP error, serialization error, cancellation, and retry exhaustion.

## Gate Rule

If required native targets exist and shared/reachable code constructs Ktor `CIO` for `https://` traffic, the networking gate fails unless there is project-specific evidence that the exact target provides working TLS support.

Failure classification:

```text
native_networking_engine_mismatch
```

Remediation:

- Replace hard-coded `CIO` with target-aware engine selection.
- Move engine dependencies to target-specific source sets.
- Use Darwin or another verified native-capable engine for iOS.
- Use a verified HarmonyOS-capable engine/platform actual for HarmonyOS, or record a blocker with evidence and impact.
- Rerun the affected build/runtime validation gate and cite both failing and fixed evidence.
