# Kotlinx Serialization JSON Cookbook

Track: CPF-KMP-CMP 0.3.0.

Use for replacing Gson/Moshi/simple Jackson JSON handling in shared KMP code.

## Coordinates

- `org.jetbrains.kotlinx:kotlinx-serialization-core:1.9.1-0.3.0`
- `org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.1-0.3.0`

## Confirmed Packages And APIs

Evidence source: [foundation_api_evidence.json](../foundation_api_evidence.json).

- `kotlinx.serialization.json.Json`
- `JsonBuilder.ignoreUnknownKeys`
- `JsonBuilder.explicitNulls`
- `JsonBuilder.isLenient`
- `JsonBuilder.encodeDefaults`
- `Json.parseToJsonElement`

## Recommended Imports

```kotlin
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
```

## Preferred Pattern

Define DTOs with `@Serializable` and configure one shared `Json`.

```kotlin
@Serializable
data class ArticleDto(
    val id: String,
    val title: String,
    @SerialName("image_url") val imageUrl: String? = null,
)

val appJson = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    encodeDefaults = true
}
```

## Android Source Replacement

- Gson/Moshi model adapters -> `@Serializable` DTOs and `Json`.
- `@SerializedName` / Moshi `@Json` -> `@SerialName`.
- Lenient unknown-field parsing -> `ignoreUnknownKeys = true`.

## HarmonyOS Constraints

- `kotlinx-serialization-json:1.9.1-0.3.0` has both `ohosArm64` and `ohosX64`.
- Serialization plugin version must match the Kotlin `0.3.0` track used by the template.

## Avoid

- Do not manually parse JSON strings with regex/string slicing when DTO behavior is in scope.
- Do not keep Gson/Moshi/Jackson in common/Harmony code unless target support is separately proven.
