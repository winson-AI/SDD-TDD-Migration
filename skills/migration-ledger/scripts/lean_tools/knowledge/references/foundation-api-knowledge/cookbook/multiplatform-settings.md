# Multiplatform Settings Cookbook

Track: CPF-KMP-CMP 0.3.0.

Use for replacing SharedPreferences, simple DataStore preferences, or small key-value settings.

## Coordinates

- `com.russhwolf:multiplatform-settings:1.3.0-0.3.0`
- Optional coroutines: `com.russhwolf:multiplatform-settings-coroutines:1.3.0-0.3.0`
- Optional serialization: `com.russhwolf:multiplatform-settings-serialization:1.3.0-0.3.0`

## Confirmed Packages And APIs

Evidence source: [foundation_api_evidence.json](../foundation_api_evidence.json).

The CPF demo repository at commit `f448266c705546247ab79a6f49367c4b254ade9b` proves only sample
source integration. It does not establish that every no-arg or DataStore-backed Settings factory
uses a persistent Harmony backend in the target application.

- `com.russhwolf.settings.*`
- `KeychainSettings` is present for Apple targets; use platform-appropriate settings factories for other targets.

## Recommended Imports

```kotlin
import com.russhwolf.settings.Settings
```

## Preferred Pattern

Keep application preferences behind a small repository interface.

```kotlin
interface UserSettings {
    var darkThemeEnabled: Boolean
    var followedTopicIds: Set<String>
}

class DefaultUserSettings(
    private val settings: Settings,
) : UserSettings {
    override var darkThemeEnabled: Boolean
        get() = settings.getBoolean("darkThemeEnabled", false)
        set(value) = settings.putBoolean("darkThemeEnabled", value)

    override var followedTopicIds: Set<String>
        get() = settings.getStringOrNull("followedTopicIds")
            ?.split(",")
            ?.filter { it.isNotBlank() }
            ?.toSet()
            ?: emptySet()
        set(value) = settings.putString("followedTopicIds", value.joinToString(","))
}
```

## Android Source Replacement

- `SharedPreferences.getBoolean/string/int` -> `Settings.getBoolean/getString/getInt`.
- `SharedPreferences.Editor.put*().apply()` -> `Settings.put*`.
- DataStore preferences can map here only for simple key-value state; for transactional or flow-heavy persistence, use a more complete store.

## HarmonyOS Constraints

- `multiplatform-settings:1.3.0-0.3.0` has `ohosArm64`; current metadata does not show `ohosX64`.
- Platform settings construction may need target-specific actual code. Do not assume Android `Context`.
- Record the concrete OHOS backend and its application-private storage location. A no-arg factory
  is not persistence evidence.
- Own one Settings/store instance per backing file when the selected adapter uses DataStore.

## Required Runtime Gate

Write representative Boolean, numeric, string, and serialized values, recreate the repository,
restart the app process, and read them back. Verify delete/default semantics separately. An
in-memory pass or a temporary-directory backend does not preserve Android SharedPreferences or
DataStore behavior.

## Avoid

- Do not store complex relational data in settings when source uses Room/SQLite.
- Do not keep Android `SharedPreferences` or `DataStore` APIs in common/Harmony source sets.
- Do not claim persistence from same-process read-after-write alone.
