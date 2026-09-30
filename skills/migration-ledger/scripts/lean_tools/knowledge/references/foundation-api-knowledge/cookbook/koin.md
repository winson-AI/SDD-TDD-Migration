# Koin Cookbook

Track: CPF-KMP-CMP 0.3.0.

Use for replacing Hilt/Dagger or manual singleton graphs when dependency injection is in scope.

## Coordinates

- `io.insert-koin:koin-core:4.1.1-0.3.0`
- Optional Compose: `io.insert-koin:koin-compose:4.1.1-0.3.0`
- Optional ViewModel: `io.insert-koin:koin-compose-viewmodel:4.1.1-0.3.0`

## Confirmed Packages And APIs

Evidence source: [foundation_api_evidence.json](../foundation_api_evidence.json).

- `org.koin.core.Koin`
- `org.koin.dsl.*`
- `org.koin.core.module.*`
- `org.koin.core.context.*`
- `Koin.loadModules`
- `Koin.getScope`, `Koin.getScopeOrNull`

## Recommended Imports

```kotlin
import org.koin.core.context.startKoin
import org.koin.core.module.Module
import org.koin.dsl.module
```

## Preferred Pattern

Keep DI module declarations in shared code when dependencies are multiplatform.

```kotlin
val appModule = module {
    single { createJson() }
    single { createHttpClient() }
    single { NewsApi(get(), baseUrl = get()) }
    single<NewsRepository> { DefaultNewsRepository(get()) }
}
```

Start Koin from the platform entry point:

```kotlin
fun initDependencies(extraModules: List<Module> = emptyList()) {
    startKoin {
        modules(appModule + extraModules)
    }
}
```

## Android Source Replacement

- Hilt `@Inject` constructor -> Koin `single { Type(get()) }` or `factory { Type(get()) }`.
- Hilt `@Module` / `@Provides` -> Koin `module { single { ... } }`.
- Android `@HiltViewModel` -> use target architecture's state holder pattern or Koin ViewModel only when selected and supported.

## HarmonyOS Constraints

- `koin-core:4.1.1-0.3.0` has `ohosArm64`; current metadata does not show `ohosX64`.
- Avoid Android-specific Koin integrations unless their Harmony target support is proven.

## Avoid

- Do not replace non-trivial DI graphs with global mutable singletons if Koin is selected.
- Do not keep Hilt/Dagger annotations in common/Harmony code.
