"""Android application package name mappings.

Maps user-friendly app names to Android package names. The mapping data
itself lives in knowledge/app_packages/ (not here) so this module stays
free of any specific vendor/app names - only generic lookup logic.
Launching only needs the package name (see device.py::launch_app) - Android
resolves the launcher activity itself via `monkey -c android.intent.category.LAUNCHER`,
unlike HarmonyOS which needs an explicit bundle+ability pair.

Only entries with a high-confidence, long-stable package name are included.
Verify/extend with `adb shell pm list packages | grep <keyword>` on the
actual test device before relying on an app not listed here - package names
occasionally change across app major versions, and this list is a starting
set, not exhaustive.

System/OEM apps (settings, camera, gallery, etc.) are intentionally omitted:
unlike HarmonyOS's unified system apps, these vary per Android OEM/ROM.
"""

from ...utils.utils import flatten_categories, load_knowledge_json

# Known launcher (home screen) package names, used by get_current_app() to
# detect "System Home" instead of misreporting the OEM launcher as an app.
LAUNCHER_PACKAGES: set[str] = set(load_knowledge_json("app_packages", "android_launchers.json").get("packages", []))

APP_PACKAGES: dict[str, str] = flatten_categories(load_knowledge_json("app_packages", "android.json"))


def get_package_name(app_name: str) -> str | None:
    """
    Get the Android package name for an app.

    Args:
        app_name: The display name of the app.

    Returns:
        The Android package name, or None if not found.
    """
    return APP_PACKAGES.get(app_name)


def get_app_name(package_name: str) -> str | None:
    """
    Get the app name from a package name.

    Args:
        package_name: The Android package name.

    Returns:
        The display name of the app, or None if not found.
    """
    for name, package in APP_PACKAGES.items():
        if package == package_name:
            return name
    return None


def list_supported_apps() -> list[str]:
    """
    Get a list of all supported app names.

    Returns:
        List of app names.
    """
    return list(APP_PACKAGES.keys())
