# `@ohos/webrtc` host integration

Use this only when a migration needs WebRTC on HarmonyOS/OpenHarmony and the target requires `ohosArm64`. It is a host capability, not a dependency for `commonMain` or `ohosMain`.

## Verified route

```text
commonMain action/state
  -> ohosMain typed actual
  -> dlsym("libentry.so", "lk_host_...")
  -> libentry.so NAPI thread-safe callback
  -> ArkTS host
  -> @ohos/webrtc HAR / libohos_webrtc.so
```

Pin `@ohos/webrtc` in the entry module. The verified package version is `1.0.2`; re-check the version, API and ABI instead of silently upgrading.

The ArkTS host owns `PeerConnectionFactory`, `RTCPeerConnection`, sources, tracks and render surfaces. Keep the KMP API semantic and small. Register callbacks before creating the KMP controller so `ohosMain` cannot call an unregistered bridge.

For Kotlin/Native symbol lookup, explicitly open the module that exports the bridge:

```kotlin
val handle = dlopen("libentry.so", RTLD_NOW)
val start = dlsym(handle, "lk_host_camera_start")
```

`dlopen(null)` did not expose the entry symbols on the verified API 20 physical device even though the NAPI module was loaded.

Camera flow must request `ohos.permission.CAMERA` dynamically in ArkTS, then create a WebRTC `VideoSource`, `VideoTrack`, and attach it to a `RTCPeerConnection`. Stop and release the source/track on disable, switch, page disappearance and application teardown. A thread-safe callback being scheduled is not the camera result; production state parity also needs exactly-once success/denial/failure feedback to KMP.

## Proof ladder

Do not collapse these into one “WebRTC supported” flag:

1. ohpm package resolves and the lockfile pins it.
2. `ohosArm64` compile and publish pass.
3. HAP builds and contains `libs/arm64-v8a/libohos_webrtc.so`.
4. KMP resolves the bridge and ArkTS creates factory plus PeerConnection on a device.
5. Permission grant creates a camera VideoTrack; front/back switch works; asynchronous result reaches KMP state.
6. SDP/ICE/signaling publishes the track to the intended service.
7. Remote/local tracks render into the product UI.
8. Audio, screen share, data channel and lifecycle behavior pass separately.

This experience verified steps 1-4 and the successful capture/switch portion of step 5. Permission-denial/failure feedback and steps 6-8 remain capability-specific work and must stay blocked until evidenced.

The upstream standalone probe is not bundled or supported by this adapter. `knowledge-query` is read-only: it does not install packages or execute any probe. Spec-Designer records the required package/bridge checks as frozen TASK/PATH/ASSERT; Test-Runner runs the approved checks through the existing SDD build/automation flow. Keep evidence under the current run and apply the [SDD knowledge mapping](../sdd-adaptation.md).

Non-fatal resource collision warnings from the HAR can be recorded as warnings. Missing arm64 native packaging, bridge symbols, permissions or device initialization is a failure.
