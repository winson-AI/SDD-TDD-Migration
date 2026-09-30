# Coil Compose Cookbook

Track: CPF-KMP-CMP 0.3.0.

Use for replacing Glide/Picasso/Android Coil image rendering in Compose UI.

## Coordinates

- `io.coil-kt.coil3:coil:3.3.0-0.3.0`
- `io.coil-kt.coil3:coil-compose:3.3.0-0.3.0`
- Optional networking: `io.coil-kt.coil3:coil-network-ktor3:3.3.0-0.3.0`
- Optional GIF: `io.coil-kt.coil3:coil-gif:3.3.0-0.3.0`

## Confirmed Packages And APIs

Evidence source: [foundation_api_evidence.json](../foundation_api_evidence.json). The CPF demo repository at commit
`f448266c705546247ab79a6f49367c4b254ade9b` is `demo_source_example` evidence for using a
platform engine factory: Android selects the Android engine and `ohosArm64Main` selects Curl.

- `coil3.compose.AsyncImage`
- `coil3.compose.rememberAsyncImagePainter`
- `coil3.compose.SubcomposeAsyncImage`
- `coil3.compose.setSingletonImageLoaderFactory`

## Recommended Imports

```kotlin
import coil3.compose.AsyncImage
import coil3.compose.rememberAsyncImagePainter
import androidx.compose.foundation.Image
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
```

## Preferred Pattern

Use `AsyncImage` for normal image slots and pass source URLs/models from state.

```kotlin
@Composable
fun ArticleImage(
    imageUrl: String?,
    contentDescription: String?,
    modifier: Modifier = Modifier,
) {
    AsyncImage(
        model = imageUrl,
        contentDescription = contentDescription,
        contentScale = ContentScale.Crop,
        modifier = modifier,
    )
}
```

Use `rememberAsyncImagePainter` when the UI already owns an `Image` composable:

```kotlin
val painter = rememberAsyncImagePainter(model = imageUrl)
Image(
    painter = painter,
    contentDescription = contentDescription,
    modifier = modifier,
)
```

## Android Source Replacement

- `ImageView` + Glide/Picasso/Coil Android extension -> Compose `AsyncImage`.
- Drawable placeholder resources -> Compose placeholder state or static resource painter, if migrated.
- Do not replace real image loading with a colored box unless image loading is explicitly out of scope.

## HarmonyOS Constraints

- `coil-compose:3.3.0-0.3.0` has `ohosArm64`; current metadata does not show `ohosX64`.
- If source behavior requires network images, include `coil-network-ktor3` and route its
  `HttpClientEngine` through the same target-specific Ktor engine factory used by API traffic.
- For the current CPF track, resolve `io.ktor:ktor-client-curl:3.3.3-0.3.0` for `ohosArm64Main`;
  never inherit CIO as a Native HTTPS default from `commonMain`.
- Declare `ohos.permission.INTERNET`; treat remote image errors as network failures, not visual
  placeholders.

## Required Runtime Gate

On the required physical device, load one deterministic HTTPS image with the production
`ImageLoader`. Require `onSuccess`, non-zero decoded dimensions, and no fallback fixture. Exercise
the explicit error/placeholder state with a controlled failure. Cache verification requires two
loads and an observed memory/disk data source; object construction alone is insufficient.

## Avoid

- Do not import Android `ImageView`, `BitmapFactory`, Glide, Picasso, or Android Coil APIs in common/Harmony source sets.
- Do not hardcode fixture image colors when the source screen displays remote or resource images.
- Do not mark `onError` or a swallowed network exception as successful image loading.
