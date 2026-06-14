from device.adb_controller import AdbController
import logging
import json
import os

logger = logging.getLogger(__name__)

# ── Load alias table once at import time ────────────────────────────────────
_ALIASES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "app_aliases.json")
try:
    with open(_ALIASES_PATH, "r", encoding="utf-8") as _f:
        _RAW = json.load(_f)
    # Strip the _comment key, lowercase all keys for case-insensitive lookup
    APP_ALIASES: dict[str, str] = {k.lower(): v for k, v in _RAW.items() if not k.startswith("_")}
    logger.debug(f"Loaded {len(APP_ALIASES)} app aliases from app_aliases.json")
except Exception as e:
    APP_ALIASES = {}
    logger.warning(f"Could not load app_aliases.json: {e}")


def _resolve_package(name_or_pkg: str, adb: AdbController, device_id: str) -> str:
    """
    Given an app name (e.g. 'Spotify') or package name (e.g. 'com.spotify.music'),
    returns the best matching installed package name.

    Resolution order:
      1. Already looks like a package name (contains '.') → return as-is
      2. Exact alias match  (case-insensitive)
      3. Partial alias match (input is a substring of an alias key)
      4. Fuzzy match against installed packages on the device
      5. Give up → return original input unchanged
    """
    candidate = name_or_pkg.strip()

    key = candidate.lower()

    # 1. Exact alias match
    if key in APP_ALIASES:
        pkg = APP_ALIASES[key]
        logger.info(f"Resolved '{candidate}' → '{pkg}' (exact alias)")
        return pkg

    # 2. Looks like a package name -> verify it's actually installed
    if "." in candidate and " " not in candidate:
        installed = adb.list_packages(candidate, device_id)
        if candidate in installed:
            logger.info(f"Resolved '{candidate}' → '{candidate}' (verified installed package)")
            return candidate
        else:
            logger.info(f"'{candidate}' looks like a package but is not installed. Checking aliases...")

    # 3. Partial alias match — e.g. 'maps' matches 'google maps'
    # Also handles hallucinated packages like 'com.swiggy.android' matching alias 'swiggy'
    for alias_key, pkg in APP_ALIASES.items():
        if len(alias_key) > 2 and (key in alias_key or alias_key in key):
            logger.info(f"Resolved '{candidate}' → '{pkg}' (partial alias '{alias_key}')")
            return pkg

    # 4. Fuzzy match against installed packages on the device
    logger.info(f"No alias for '{candidate}'. Searching installed packages...")
    installed = adb.list_packages(candidate, device_id)
    key_parts = key.replace(" ", "").replace("-", "")
    for pkg in installed:
        pkg_short = pkg.split(".")[-1].lower()          # e.g. 'music' from 'com.spotify.music'
        pkg_flat  = pkg.replace(".", "").lower()         # e.g. 'comspotifymusic'
        if key_parts in pkg_flat or key_parts in pkg_short:
            logger.info(f"Resolved '{candidate}' → '{pkg}' (fuzzy installed match)")
            return pkg

    logger.warning(f"Could not resolve '{candidate}' to any package. Trying as-is.")
    return candidate


def execute(adb: AdbController, package_name: str = None, query: str = None, device_id: str = None) -> bool:
    """
    Opens an application given its name or package name.

    Accepts both:
      - Package names:  'com.spotify.music'
      - App names:      'Spotify', 'YouTube', 'Google Maps'
      
    If 'query' is provided, attempts to launch the app directly into search results using android.intent.action.SEARCH.
    """
    if not package_name:
        logger.error("open_app: No package_name provided.")
        return False

    # Resolve app name / alias → actual package name
    package_name = _resolve_package(package_name, adb, device_id)

    # Known package name correction
    if package_name == "com.telegram.messenger":
        package_name = "org.telegram.messenger"

    # Already in focus?
    current_focus = adb.get_current_focus(device_id)
    if current_focus == package_name:
        logger.info(f"App '{package_name}' is already in focus.")
        return True

    # Launch via intent or monkey
    launch_cmd = []
    if device_id:
        launch_cmd.extend(["-s", device_id])
        
    if query:
        logger.info(f"Deep searching: '{package_name}' for '{query}'")
        launch_cmd.extend(["shell", "am", "start", "-a", "android.intent.action.SEARCH", "-p", package_name, "-e", "query", f'"{query}"'])
    else:
        logger.info(f"Launching: '{package_name}'")
        launch_cmd.extend(["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"])

    adb.run_cmd(*launch_cmd)

    import time
    time.sleep(1.2)
    if adb.get_current_focus(device_id) == package_name:
        return True

    # If we tried a query intent and it failed to open the app, fall back to normal launch
    if query:
        logger.warning(f"Search intent failed for '{package_name}'. Falling back to standard launch.")
        fallback_launch = []
        if device_id:
            fallback_launch.extend(["-s", device_id])
        fallback_launch.extend(["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"])
        adb.run_cmd(*fallback_launch)
        time.sleep(1.2)
        if adb.get_current_focus(device_id) == package_name:
            return True

    # Fallback: search installed packages for the closest match
    logger.warning(f"Failed to launch '{package_name}'. Searching installed packages for alternatives...")
    base = package_name.split(".")[-1].lower()
    possible = adb.list_packages(base, device_id)
    matches = [p for p in possible if base in p.lower()]

    if matches:
        best = matches[0]
        logger.info(f"Trying alternative package: '{best}'")
        fallback_cmd = []
        if device_id:
            fallback_cmd.extend(["-s", device_id])
        fallback_cmd.extend(["shell", "monkey", "-p", best, "-c", "android.intent.category.LAUNCHER", "1"])
        adb.run_cmd(*fallback_cmd)
        time.sleep(1.2)
        return adb.get_current_focus(device_id) == best

    logger.error(f"Could not find or launch any package for '{package_name}'")
    return False
