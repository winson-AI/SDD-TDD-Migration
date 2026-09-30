# XML to Compose Multiplatform Mapping

Use this guide after the Android analysis contract has combined XML with runtime behavior. The goal is behavioral and semantic parity, not a one-to-one widget rewrite.

## Structural mappings

- Linear/Frame/Constraint containers usually become the smallest suitable `Row`, `Column`, `Box` or custom layout; preserve measured intent, ordering and overlays.
- RecyclerView becomes a keyed lazy list/grid. Port adapter item identity, each ViewHolder binding, item states and actions.
- View visibility becomes conditional composition when removal is intended, or explicit visibility/alpha/layout handling when space must remain.
- SwipeRefreshLayout maps to the target-supported pull-refresh component; do not invent gesture handling if a verified cross-platform API exists.
- TextInput, checkbox, switch and selectable rows must preserve enabled/read-only/error/focus semantics and event timing.

## Build the skeleton first

Read `uiContract.layoutClosure`, every screen root and attachment tree, all state machines/navigation, and every `criticalLayoutContracts` item before writing leaf UI. Implement and compile each screen/surface skeleton first. Walk nodes top down and map every `layout.rawAttrs` property deliberately; do not fall back to Material defaults when the contract provides size, spacing, color, typography, background, image, elevation, indicator or semantics. Then apply state effects and event behavior.

- Map `viewport_anchor` to a real anchored slot or alignment whose content is excluded/reserved correctly; never emit it as an ordinary child of a scrolling `Column`.
- Map `overlay` with `Box`, popup/layer APIs or an equivalent custom layout; preserve z-order and hit targets.
- Map `sibling_constraint` by preserving the relationship, not XML source order.
- Map collapsing headers, pagers and tabs as bounded cooperating regions; do not flatten them into one scroll stream.
- Implement every source-backed state/data/orientation variant. A single hardcoded channel/item/layout branch is incomplete.

In the existing implementation dimension_evidence, reference one layout mapping record per frozen UI layout contract with target file/symbol/source set, actual mechanism, state handling, scroll handling and gate evidence. A mechanism name without matching code does not satisfy the mapping.

In the same submitted UI evidence, record one node mapping per frozen source-tree node. `mappedAttrs` must exactly
cover the contract node's `layout.rawAttrs` keys. `resourceMappings` must exactly cover the
node-linked, non-structural in-scope resources, using one
`{"resourceId": "...", "targetRefs": ["real composeResources file", "generated resource accessor"]}`
entry per resource. The owning node target is the consumer symbol. A registry/helper that only
registers the resource id is not a target ref. Layout XML itself is structural input
(`compose_structure`), not a copied runtime resource.

## State and semantics

Use one state-driven render path for loading, content, empty, error and transient overlays. Preserve accessibility semantics, content descriptions, roles, touch targets and stable test identifiers. Navigation and snackbars are effects, not durable screen state.

## Measurement and scrolling

- Assign a single vertical scroll owner to each screen region. Do not place `LazyColumn` or another vertically scrollable child under `Column(Modifier.verticalScroll())`.
- Give lazy lists and tab/page content bounded constraints. In a fixed header + tabs layout, keep the root `Column` bounded and size `HorizontalPager` or the selected tab with the remaining `weight` rather than making the root vertically scrollable.
- Put headers that must scroll with list items inside the same lazy container using `item { ... }`. Do not solve nested scrolling with arbitrary fixed heights.
- Reject an arbitrary fixed height used to make pager/list measurement compile; preserve bounded remaining-space ownership instead.
- Audit every `LazyColumn`, `LazyVerticalGrid`, `verticalScroll`, pager and custom layout path on the actual device target; a successful compile does not validate runtime measurement constraints.

## Resources and platforms

Put cross-platform strings, images, colors and fonts in Compose Multiplatform Resources and use generated resource accessors from common code. Convert compatible vector/raster assets rather than replacing them with glyphs. Platform-only resources need an explicit adapter in `androidMain`, `ohosMain` or the corresponding platform source set.

Spec-Designer freezes the allocated task's transitive resource closure and exact strategies. Implementer/Fixer performs authorized resource conversion and production wiring, with output referenced in the existing Resource dimension_evidence and Ledger submission. Do not add another resource controller or manifest. See [SDD knowledge mapping](sdd-adaptation.md). Use this decision order:

| Source need | Default route |
|---|---|
| Existing target asset or design token | Reuse it and cite the real symbol/file |
| Standalone Android `<vector>` | Normalize external references, copy as XML, build, then consume `Res.drawable.*` |
| PNG/JPEG/WebP/bitmap | Copy the appropriate source asset/qualifiers into `composeResources/drawable` |
| `shape`/`selector`/`ripple`/`layer-list`/`inset`/`animated-vector` | Recreate the state, shape, layer or animation in Compose, or use a format verified on every required target |
| String/color/dimension/font | Move to the matching Compose Resource kind and generated accessor |
| Raw file or audio | Put it under `composeResources/files`; use `Res.readBytes` only for bounded content or `Res.getUri`/a platform playback boundary for large media |
| Icon dependency | Use only after the exact version exposes KLIB/variants for every required target |
| SVG | Do not generate it by default; use only when the selected decoder/path is verified on every required target, because SVG decoding is not available on Android through the common raw-resource API |

Treat Android drawable XML by root type, not extension:

- Copy a standalone `<vector>` into `composeResources/drawable` only after every attribute value
  beginning with `@` or `?` has been resolved. Inline fixed colors/dimensions. Remove theme tint
  such as `android:tint="?attr/..."` and apply dynamic color at the `Icon`/`Image` call through
  Compose `tint` or `ColorFilter`.
- When a multi-color vector varies by theme and cannot use one tint, emit light/dark qualified
  vectors with literal values or draw it with Compose; do not leave Android theme references.
- Rewrite `shape`, `selector`, `ripple`, `layer-list`, `inset` and `animated-vector` as Compose
  shape/state/layer/animation semantics, or use a verified cross-platform raster/vector format.
  Do not copy them as if `painterResource` accepted arbitrary Android drawable XML.
- Build after conversion to generate `Res.drawable.*`, then inspect the source XML again. Packaging
  success alone does not prove a dormant or unconsumed vector can be decoded at runtime.

Generated resource accessors are the application API:

- In the resource-owning Gradle module, use generated `Res.<kind>.<name>` directly.
- For cross-module use, set `compose.resources { publicResClass = true }` in the owning module or
  expose a public wrapper from that module.
- Never use production `@OptIn(InternalResourceApi::class)`, construct `DrawableResource` or
  `ResourceItem` directly, or hand-author paths that imitate generated accessors. Generated sources
  under `build/` may use internal APIs; application sources must not.
- A compile error around `ImageVector.Builder`/`path` is evidence to inspect imports, Compose
  version and classpath. It is not proof that OHOS lacks vector support and does not authorize an
  internal-resource workaround.

Keep list/grid/pager/tab content driven by the contracted binding or typed capability. A
hardcoded fixed collection may be useful in a preview, but it is not the migrated production
content provider.

Do not import Android `R`, Context, Drawable, View or lifecycle APIs into common source sets. When an API differs by platform, keep CMP rendering shared and isolate only the platform capability.

## Evidence

Verify contracted states through source-backed structure, semantics, interactions and runtime checks. Pixel and semantic comparison are read-only evidence operations within the existing Test-Runner flow; Fixer owns code changes and MO/Auditor retains acceptance.
