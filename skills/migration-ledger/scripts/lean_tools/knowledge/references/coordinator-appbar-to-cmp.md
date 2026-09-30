# Coordinator And App Bar To CMP

Use this reference when Android source contains `CoordinatorLayout`, `AppBarLayout`, `CollapsingToolbarLayout`, `app:layout_behavior`, `app:layout_scrollFlags`, `AppBarLayout.OnOffsetChangedListener`, pager/tab coordination, persistent bottom sheets, floating children or related runtime layout mutations.

Do not translate these classes one by one. Recover the coordinated behavior, then implement the smallest equivalent CMP skeleton in `commonMain`.

Primary Android references:

- <https://developer.android.com/develop/ui/compose/migrate/migration-scenarios/coordinator-layout>
- <https://developer.android.com/develop/ui/compose/touch-input/scroll/nested-scroll-modifiers>

## Analyze the behavior first

Read the complete cooperating group:

- direct children of `CoordinatorLayout` and their z-order;
- `AppBarLayout` children, collapse modes and scroll flags;
- the scrolling sibling using `appbar_scrolling_view_behavior`;
- pager adapter pages and the vertical scroll owner inside each page;
- anchored FAB, snackbar, bottom bar, TabLayout, overlay and BottomSheet behavior;
- layout qualifiers, insets and runtime calls changing visibility, translation, elevation, height or layout parameters;
- offset/state callbacks that update titles, tabs, scrims, system bars, player state or navigation.

Do not infer behavior from XML alone. Add source-backed `criticalLayoutContracts` for every relationship that normal hierarchy order would lose.

## Choose the CMP mechanism

Use a standard Material behavior only when it represents the source behavior without approximation:

| Android behavior | Preferred CMP mechanism |
|---|---|
| top-level slots, FAB, snackbar, fixed top/bottom regions | `Scaffold` slots |
| pinned toolbar | `TopAppBarDefaults.pinnedScrollBehavior()` |
| `scroll`/enter-always toolbar | `enterAlwaysScrollBehavior()` |
| `scroll\|exitUntilCollapsed` | `exitUntilCollapsedScrollBehavior()` |
| standard app-bar coordination | `TopAppBarScrollBehavior` plus root `Modifier.nestedScroll(...)` |
| `ViewPager`/`ViewPager2` | bounded `HorizontalPager` |
| bottom-anchored `TabLayout` | `Scaffold.bottomBar` or `Box` with `Alignment.BottomCenter` |
| overlays or floating player chrome | ordered children in `Box` |
| modal sheet | verified CMP `ModalBottomSheet` |
| persistent/collapsible `BottomSheetBehavior` | verified `BottomSheetScaffold` or custom anchored state; do not replace it with a modal sheet |

Use a custom `NestedScrollConnection` when the source has parallax, multiple collapse stages, custom minimum height, non-toolbar content in the app bar, dynamic tab translation, player/header coupling or any callback that cannot be expressed by a standard `TopAppBarScrollBehavior`.

Verify the selected APIs exist in the target Compose version and required CMP targets. Do not guess a Material API or add an Android-only interop API to `commonMain`.

## Build the coordinated skeleton

Implement and compile the skeleton before leaf content:

```text
Box or Scaffold
├── collapsing/fixed header region
├── bounded remaining-space content
│   └── HorizontalPager when pages exist
│       └── exactly one vertical scroll owner per selected page
├── anchored top/bottom controls
└── overlays or persistent sheet
```

Rules:

- Attach the `NestedScrollConnection` at the lowest common parent of the header and scrolling content.
- Let the header consume only its collapse range; dispatch remaining delta to the selected page.
- Keep pager/page content bounded by parent constraints. Never place `HorizontalPager`, `LazyColumn` or another vertical scrollable under an unbounded root `verticalScroll`.
- Reserve fixed top/bottom slot space exactly once through Scaffold content padding or explicit constraints.
- Keep fixed tabs outside the page scroll stream. A `TabRow` after detail content is not equivalent to a bottom-anchored `TabLayout`.
- Preserve overlay order and input ownership. Do not flatten overlay children into a `Column`.
- Preserve all source visibility/translation rules and data/orientation variants as state, not hardcoded layout.
- Avoid arbitrary fixed heights used only to suppress infinite-constraint failures.

## Custom collapsing state

For non-standard headers, model collapse as state derived from bounded pixel offsets:

```kotlin
val collapseRangePx = expandedHeightPx - collapsedHeightPx
var headerOffsetPx by remember { mutableFloatStateOf(0f) }

val connection = remember(collapseRangePx) {
    object : NestedScrollConnection {
        override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
            val previous = headerOffsetPx
            headerOffsetPx = (headerOffsetPx + available.y)
                .coerceIn(-collapseRangePx, 0f)
            return Offset(0f, headerOffsetPx - previous)
        }
    }
}
```

Treat this as a pattern, not copy-paste output. Reconcile fling/post-scroll behavior, density changes, restored state, minimum height and the source callback semantics. Use `derivedStateOf` for collapse progress and keep business/player events outside the layout object.

## Pager and bottom tabs

When the Android source combines `AppBarLayout`, pager content and a bottom TabLayout:

- bound `HorizontalPager` to the remaining viewport;
- give each page its own `LazyColumn`/scroll owner;
- anchor the TabRow to the viewport and reserve its measured height from pager content;
- synchronize selected tab and pager state in both directions;
- implement source rules that hide/translate tabs when page count, pager visibility or visible height changes;
- restore selected page only when the source does so.

Do not solve this layout using one vertically scrolling detail `Column` followed by a TabRow and fixed-height page lists.

## Insets and OHOS

- Keep CMP layout/inset ownership consistent with `platformContracts.windowPolicy`; apply safe-area/navigation-bar padding once.
- Keep HarmonyOS window and system-bar calls in the ArkTS host. `fillMaxSize()` and nested scrolling do not configure the host window.
- Prefer pure CMP coordination for shared UI. Android View interop such as `rememberNestedScrollInteropConnection()` is an Android incremental bridge and must stay in `androidMain`; it is not an OHOS implementation.
- Validate touch/fling, collapse restoration, navigation-bar overlap and IME behavior on OHOS when the affected screen is required there.

## Contract and ledger closure

Use one or more `criticalLayoutContracts` items instead of one vague “Coordinator migrated” item. Common kinds are:

- `collapsing_region` for app-bar collapse/parallax;
- `scroll_topology` for header/pager/page coordination;
- `viewport_anchor` for fixed tabs/FAB/bars;
- `overlay` for player or floating layers;
- `adaptive_variant` for orientation/data-dependent arrangements;
- `composite` only when the behaviors cannot be independently accepted.

Record source callback rules under `stateRules` and layout alternatives under `variants`. In `layoutMappings`, trace each rule/variant to target symbols through `stateHandling` and `variantHandling`.

## Validation gate

Before marking the slice implemented:

- run the required common and target builds;
- inspect target parent/child topology and modifier ownership against every layout contract;
- reject nested vertical scroll owners, unbounded pager/list content, duplicate inset padding and arbitrary fixed-height workarounds;
- execute a `ui-structure` check for anchors, overlays, bounded regions, scroll ownership and state/variant code paths;
- execute `ui-runtime` checks when collapse, fling, sheet state or host insets cannot be established statically;
- record the layout contract ids in the checks and retain logs.

Compilation proves API and type compatibility only. It does not prove coordinated scrolling or placement.
