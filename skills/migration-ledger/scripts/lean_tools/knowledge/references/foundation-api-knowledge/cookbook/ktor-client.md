# Ktor Client Cookbook

Track: CPF-KMP-CMP 0.3.0.

Use for replacing Retrofit/OkHttp-style API clients in shared KMP code when HarmonyOS is in scope.

## Coordinates

- `io.ktor:ktor-client-core:3.3.3-0.3.0`
- `io.ktor:ktor-client-cio:3.3.3-0.3.0`
- `io.ktor:ktor-client-curl:3.3.3-0.3.0`
- `io.ktor:ktor-client-content-negotiation:3.3.3-0.3.0`
- `io.ktor:ktor-serialization-kotlinx-json:3.3.3-0.3.0`
- Optional: `io.ktor:ktor-client-logging:3.3.3-0.3.0`

## Confirmed Packages And APIs

Evidence source: [foundation_api_evidence.json](../foundation_api_evidence.json). The CPF demo repository is only
`demo_source_example` evidence: at commit `f448266c705546247ab79a6f49367c4b254ade9b`, its Coil
sample selects Curl in `ohosArm64Main`, but its Ktor "TLS" scenario requests `http://example.com`
and therefore does not prove HTTPS/TLS.

- `io.ktor.client.HttpClient`
- `io.ktor.client.request.*`
- `io.ktor.client.statement.*`
- `io.ktor.client.call.*`
- `io.ktor.client.plugins.contentnegotiation.ContentNegotiation`
- `io.ktor.serialization.kotlinx.json.json`
- `kotlinx.serialization.json.Json`

## Recommended Imports

```kotlin
import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.request.get
import io.ktor.client.request.parameter
import io.ktor.client.request.url
import io.ktor.http.ContentType
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import kotlinx.serialization.json.Json
```

## Preferred Pattern

Create one small API client around an injected `HttpClient`; keep DTO mapping separate from UI state.

```kotlin
class NewsApi(
    private val client: HttpClient,
    private val baseUrl: String,
) {
    suspend fun topic(id: String): TopicDto =
        client.get {
            url("$baseUrl/topics/$id")
            contentType(ContentType.Application.Json)
        }.body()
}
```

Configure plugins in common code but inject a platform-selected engine:

```kotlin
fun createJson() = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
}

expect fun createPlatformHttpClientEngine(): HttpClientEngine

fun createHttpClient() = HttpClient(createPlatformHttpClientEngine()) {
    install(ContentNegotiation) {
        json(createJson())
    }
}
```

For the verified CPF `ohosArm64` track, keep Curl in the OHOS source set rather than making CIO a
shared default:

```kotlin
// ohosArm64Main
actual fun createPlatformHttpClientEngine(): HttpClientEngine = Curl.create()
```

```kotlin
ohosArm64Main.dependencies {
    implementation("io.ktor:ktor-client-curl:3.3.3-0.3.0")
}
```

Select and verify the corresponding engine independently for Android and any Apple target. Do not
let an engine dependency in `commonMain` decide production engine selection by accident.

## Android Source Replacement

- Retrofit interface method -> concrete suspend function on a Ktor-backed client.
- `@GET`, `@Query`, `@Path` annotations -> explicit `client.get { url(...); parameter(...) }`.
- OkHttp interceptor assumptions -> explicit Ktor plugin or wrapper; do not keep OkHttp reachable in common/Harmony code unless target support is proven.

## HarmonyOS Constraints

- `ohosArm64` is available for the listed 0.3.0 Ktor artifacts; `ohosX64` is not available in the current metadata.
- Do not make simulator/x64 a required gate unless the user explicitly asked for x64 support.
- Declare `ohos.permission.INTERNET` in the Harmony entry module for network traffic. Network-state
  inspection can require an additional permission; resolve it against the target SDK instead of
  copying a demo manifest wholesale.
- `TLS sessions are not supported on Native platform` is an engine-selection failure signal, not a
  reason to disable TLS or retry plain HTTP. Trace the actual engine and load
  [native-networking-engine.md](../../native-networking-engine.md).
- Do not assume native HTTPS/TLS works from `HttpClient(CIO)` without target-specific runtime evidence.

## Required Runtime Gate

Build/package success and `HttpClient` construction are insufficient. On the required physical
device, call a stable `https://` endpoint and assert the expected status and body. Record engine
class, URL scheme, result, and failure category. Keep permission/DNS/VPN, TCP, TLS, HTTP, decoding,
and cancellation failures distinct.

## Avoid

- Do not keep Retrofit/OkHttp in `commonMain` or `ohosMain`.
- Do not return raw JSON strings as final logic when source has typed DTO behavior.
- Do not write placeholder API clients if Ktor is selected and compile evidence exists.
- Do not count a caught exception as a passing network test.
