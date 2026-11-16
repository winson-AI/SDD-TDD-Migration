"""iOS application bundle ID mappings.

Maps user-friendly app names to iOS bundle identifiers, used with
WebDriverAgent's app_launch/app_stop/app_current. The mapping data itself
lives in knowledge/app_packages/ (not here) so this module stays free of
any specific vendor/app names - only generic lookup logic.

Only Apple's own built-in apps are listed with confidence - their bundle
IDs have been stable for years and are extremely well documented.
Third-party apps are deliberately NOT guessed here: unlike Android package
names (routinely visible in Play Store URLs), iOS bundle IDs aren't
reliably inferable, and a wrong guess silently launches nothing useful.
Add them to the knowledge data file once confirmed on the target build
(e.g. via `ideviceinstaller -l` on a real device, or Xcode's Devices window).

Also note: the iOS Simulator can only run apps built for the simulator SDK
from source - it cannot run App Store binaries (no App Store on simulator).
Third-party apps are only reachable this way on a real device.
"""

import re

from ...utils.utils import flatten_categories, load_knowledge_json

APP_PACKAGES: dict[str, str] = flatten_categories(load_knowledge_json("app_packages", "ios.json"))


def get_package_name(app_name: str) -> str | None:
    """
    Get the iOS bundle identifier for an app.

    Args:
        app_name: The display name of the app.

    Returns:
        The bundle identifier, or None if not found.
    """
    return APP_PACKAGES.get(app_name) or (app_name if re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", app_name) else None)


def get_app_name(bundle_id: str) -> str | None:
    """
    Get the app name from a bundle identifier.

    Args:
        bundle_id: The iOS bundle identifier.

    Returns:
        The display name of the app, or None if not found.
    """
    for name, bid in APP_PACKAGES.items():
        if bid == bundle_id:
            return name
    return None


def list_supported_apps() -> list[str]:
    """
    Get a list of all supported app names.

    Returns:
        List of app names.
    """
    return list(APP_PACKAGES.keys())
