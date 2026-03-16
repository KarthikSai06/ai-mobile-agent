from device.adb_controller import AdbController
import logging

logger = logging.getLogger(__name__)

def execute(adb: AdbController, package_name: str = None, device_id: str = None) -> bool:
    """
    Opens an application given its package name with verification and fallback.
    """
    if not package_name:
        logger.error("open_app: No package_name provided.")
        return False
    # 1. Check if already focused
    current_focus = adb.get_current_focus(device_id)
    if current_focus == package_name:
        logger.info(f"App '{package_name}' is already in focus.")
        return True

    # 2. Try to launch
    launch_cmd = []
    if device_id:
        launch_cmd.extend(["-s", device_id])
    launch_cmd.extend(["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"])
    
    logger.info(f"Attempting to launch: '{package_name}'")
    adb.run_cmd(*launch_cmd)

    # 3. Verify launch
    import time
    time.sleep(1) # Wait for launch
    if adb.get_current_focus(device_id) == package_name:
        return True

    # 4. Fallback: Search for package if not focused
    logger.warning(f"Failed to launch '{package_name}'. Searching for alternatives...")
    possible_packages = adb.list_packages(package_name, device_id)
    
    if not possible_packages:
        # Try a broader search (e.g., if LLM said 'settings' instead of 'com.android.settings')
        possible_packages = adb.list_packages("", device_id)
        possible_packages = [p for p in possible_packages if package_name.lower() in p.lower()]

    if possible_packages:
        best_match = possible_packages[0] # Simplest heuristic: take the first match
        logger.info(f"Found alternative package: '{best_match}'. Attempting launch...")
        launch_cmd[-4] = best_match # Replace package name in monkey command
        adb.run_cmd(*launch_cmd)
        time.sleep(1)
        return adb.get_current_focus(device_id) == best_match

    logger.error(f"Could not find or launch package for '{package_name}'")
    return False
