# SQLDelight Native Driver Cookbook

Track: CPF-KMP-CMP 0.3.0.

Use for replacing Room/SQLite persistence when SQLDelight is selected.

## Coordinates

- `app.cash.sqldelight:runtime:2.2.1-0.3.0`
- `app.cash.sqldelight:coroutines-extensions:2.2.1-0.3.0`
- `app.cash.sqldelight:native-driver:2.2.1-0.3.0`

Official CPF-KMP-CMP forks:

- [SQLDelight](https://gitcode.com/CPF-KMP-CMP/sqldelight)
- [SQLiter](https://gitcode.com/CPF-KMP-CMP/SQLiter)

## Confirmed Packages And APIs

Evidence source: [foundation_api_evidence.json](../foundation_api_evidence.json).

The CPF demo repository at commit `f448266c705546247ab79a6f49367c4b254ade9b` is
`demo_source_example` evidence for moving driver creation into an OHOS actual and using an
application-private path. Its catch-all fallback to `inMemoryDriver` is not persistence proof and
must not be copied into production migration code.

- `app.cash.sqldelight.driver.native.NativeSqliteDriver`
- `app.cash.sqldelight.driver.native.*`

## Recommended Imports

```kotlin
import app.cash.sqldelight.db.SqlDriver
import app.cash.sqldelight.driver.native.NativeSqliteDriver
```

## Required Gradle Configuration For HarmonyOS

When the module applies the SQLDelight Gradle plugin and declares an `ohosArm64` binary, disable
SQLDelight's global native SQLite linker option:

```kotlin
sqldelight {
    // SQLiter's OHOS KLIB already carries and links the real static SQLite archive.
    // The plugin default would append a second system-style -lsqlite3 lookup.
    linkSqlite.set(false)

    databases {
        create("AppDatabase") {
            packageName.set("com.example.database")
            srcDirs("src/commonMain/sqldelight")
        }
    }
}
```

Place the runtime in shared code and the native driver only in the supported OHOS source set:

```kotlin
kotlin {
    ohosArm64()

    sourceSets {
        commonMain.dependencies {
            implementation("app.cash.sqldelight:runtime:2.2.1-0.3.0")
        }
        ohosArm64Main.dependencies {
            implementation("app.cash.sqldelight:native-driver:2.2.1-0.3.0")
        }
    }
}
```

Do not declare `ohosX64()` for a source-set dependency graph reachable from this driver unless a
newer artifact's Gradle metadata proves that variant exists. Version `2.2.1-0.3.0` publishes
`ohosArm64`, not `ohosX64`.

If the same Gradle module also builds an Apple target that requires the system SQLite library,
keep `linkSqlite.set(false)` and add `-lsqlite3` only to the affected Apple binaries. Never restore
the plugin's global setting for an OHOS-bearing module.

## Why `linkSqlite.set(false)` Is Required

The CPF SQLDelight plugin currently defaults `linkSqlite` to `true`. Its `LinkSqlite.kt` applies
`compilationUnit.linkerOpts("-lsqlite3")` to every Kotlin/Native binary, including `ohosArm64`.

The CPF SQLiter OHOS cinterop already declares these static libraries in `sqlite3.def`:

```text
staticLibraries.ohos_arm64 = libsqlite3.a libz.a libclang_rt.builtins.a
```

As a result, the failing link command contains both the real bundled `libsqlite3.a` and a later,
redundant `-lsqlite3`. The OHOS sysroot does not expose a library under that linker lookup name, so
the redundant option fails with:

```text
The ohos link FAILED: unable to find library -lsqlite3
```

This failure does not mean SQLite is absent from the SQLiter KLIB. Fix the consumer configuration;
do not manufacture another SQLite archive.

## Preferred Driver Pattern

Keep driver creation behind expect/actual or a platform factory.

```kotlin
interface DatabaseDriverFactory {
    fun createDriver(): SqlDriver
}
```

In native/Harmony-specific source sets, create a `NativeSqliteDriver` with a simple database file name and platform-provided writable base path when supported by the target API.

```kotlin
class OhosDatabaseDriverFactory(
    private val databaseDir: String,
) : DatabaseDriverFactory {
    override fun createDriver(): SqlDriver {
        return NativeSqliteDriver(
            schema = AppDatabase.Schema,
            name = "app.db",
            onConfiguration = { configuration ->
                configuration.copy(
                    extendedConfig = configuration.extendedConfig.copy(
                        basePath = databaseDir,
                    ),
                )
            },
        )
    }
}
```

## Android Source Replacement

- Room DAO interfaces -> SQLDelight `.sq` queries plus generated database APIs.
- `Room.databaseBuilder(context, Db::class.java, "name")` -> platform-specific `SqlDriver` factory.
- `Flow` query observation -> SQLDelight coroutines extensions when selected.

## HarmonyOS Constraints

- `native-driver:2.2.1-0.3.0` has `ohosArm64`; current metadata does not show `ohosX64`.
- Do not pass a path containing `/` as the database `name`. Keep filename and writable directory/base path separate if the driver/config API supports it.
- Obtain the writable application database directory from the Harmony host/platform boundary and
  pass it as SQLiter `extendedConfig.basePath`; keep `name` as a filename.

## Required Link Gate

Compilation is insufficient because the defect occurs during final Kotlin/Native linkage. For each
OHOS build type used by the active slice, execute the real shared-library or executable link task,
for example:

```bash
./gradlew :composeApp:linkDebugSharedOhosArm64 --no-daemon --console=plain
```

The gate fails if the final link command still contains a free-standing `-lsqlite3`, or if source
configuration contains a migration-authored SQLite shim. Inspect the produced ELF with the OHOS
LLVM tools when available:

```bash
llvm-nm <libkn.so> | rg 'sqlite3_(open|prepare|step|close|libversion)'
llvm-readobj --needed-libs <libkn.so>
```

Required outcome:

- the link task exits zero;
- real `sqlite3_*` symbols are present in the final binary;
- `NeededLibraries` does not contain `libsqlite3.so`;
- no migration-authored `sqlite3lib/`, empty `libsqlite3.a`, or OHOS `-L...sqlite3...` workaround
  exists.

The SQLiter KLIB may legitimately contribute a temporary extracted `libsqlite3.a` inside the
Kotlin/Native link workspace. That is distinct from a migration-authored shim in project sources.

## Avoid

- Do not keep Room or Android `Context` database APIs in common/Harmony code.
- Do not silently replace persisted state with an in-memory map unless persistence is out of scope or blocked with evidence.
- Do not fix `unable to find library -lsqlite3` by creating an empty or dummy `libsqlite3.a`.
- Do not add project `sqlite3lib` directories, manual `-L` search paths, or a second SQLite build
  when the selected SQLiter OHOS KLIB already carries the static archive.
- Do not accept `compileKotlinOhosArm64` alone as database integration evidence; run the final link
  task and inspect its product.
- Do not catch file-driver creation failure and silently return an in-memory driver when source
  behavior requires persistence. Surface a typed startup/storage error and keep the acceptance gate
  failing until the real file database survives close/reopen and app restart.
