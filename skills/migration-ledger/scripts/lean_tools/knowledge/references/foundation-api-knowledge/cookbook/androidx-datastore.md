# AndroidX DataStore Cookbook

Track: CPF-KMP-CMP 0.3.0.

Use when preserving Android DataStore preferences/proto behavior on an `ohosArm64` target.

## Coordinates

- `androidx.datastore:datastore:1.3.0-alpha05-0.3.0`
- `androidx.datastore:datastore-core:1.3.0-alpha05-0.3.0`
- `androidx.datastore:datastore-preferences:1.3.0-alpha05-0.3.0`
- `androidx.datastore:datastore-preferences-core:1.3.0-alpha05-0.3.0`

Gradle module metadata confirms `ohosArm64`; current metadata does not publish `ohosX64`.

## Evidence Boundary

[foundation_api_evidence.json](../foundation_api_evidence.json) is the coordinate/variant authority. The CPF
`kmp-thirdlibdemo` source at commit `f448266c705546247ab79a6f49367c4b254ade9b` is
`demo_source_example` evidence for the host-path pattern below; it is not device-runtime proof.

## Required Architecture

- Keep serializers, migrations, keys, typed repository behavior, and `DataStoreFactory`/
  `PreferenceDataStoreFactory` setup in shared code when their APIs are target-compatible.
- Obtain the application-private files directory from the Harmony host before first store access.
  Pass it through an explicit platform boundary (for example the existing NAPI/ArkTS host bridge),
  then build the Okio path and create parent directories.
- Create one process-level DataStore instance and one owned `SupervisorJob` scope per backing file.
  Do not create a store during each composition, screen entry, repository call, or ViewModel
  construction.
- Preserve corruption handlers and source migrations deliberately; never discard legacy data just
  to make startup succeed.

The demo's relevant order is:

```text
EntryAbility.onCreate
  -> pass context.filesDir through the native bridge
  -> set the Kotlin/Native DataStore base path
  -> lazily create the singleton DataStore
  -> shared repository reads/writes the store
```

Do not copy the demo's temporary-directory fallback into production. Missing host initialization
must be a typed prerequisite/startup failure when persistence is required.

## Android Source Replacement

- Preserve Preferences versus Proto DataStore semantics; do not collapse typed Proto state into
  ad-hoc strings.
- Preserve `Flow` delivery, migrations, corruption behavior, update atomicity, and cancellation.
- Keep Android `Context` and Android file APIs out of `commonMain`/`ohosArm64Main`.

## Required Runtime Gate

On the required physical device:

1. start from a clean app data directory;
2. write representative values through production wiring;
3. collect from the real `Flow`;
4. recreate the repository/store owner without creating a competing instance;
5. restart the app process and read the same values;
6. execute applicable migration/corruption behavior.

Record the resolved backing path without logging secrets or user data. Same-process read-after-write,
temporary storage, or a caught file error is not persistence evidence.

## Avoid

- Do not create multiple DataStore instances for the same file.
- Do not initialize the store before the host supplies its private files directory.
- Do not use cache/temp storage for durable source behavior.
- Do not convert persistence failures into defaults without an explicit source-equivalent recovery
  contract.
