import os
import time
import logging
from device.adb_controller import AdbController
from config import settings

logger = logging.getLogger(__name__)

def dump_ui_hierarchy(adb: AdbController, device_id: str = None) -> str:
    """
    Dumps the UI hierarchy from the Android device and pulls the XML file to local storage.
    On each failure, performs a small scroll to try to unblock uiautomator
    (e.g. when a YouTube ad / fullscreen video is playing).
    Returns the local XML path on success, or "" after 3 scroll attempts.
    """
    remote_path = "/sdcard/ui_dump.xml"
    local_filename = f"ui_dump_{int(time.time())}.xml"
    local_path = os.path.join(settings.STORAGE_DIR, local_filename)

    cmd_prefix = []
    if device_id:
        cmd_prefix = ["-s", device_id]

    logger.info("Dumping UI hierarchy...")

    for attempt in range(2):  # attempt 0 = first try, attempt 1 = scroll + retry
        adb.run_cmd(*(cmd_prefix + ["shell", "rm", "-f", remote_path]))
        time.sleep(1.5)

        dump_output = adb.run_cmd(*(cmd_prefix + ["shell", "uiautomator", "dump", remote_path]))
        if "UI hierchary dumped to" not in dump_output and "dumped to" not in dump_output:
            logger.warning(f"Unexpected uiautomator output on attempt {attempt+1}: {dump_output}")

        time.sleep(0.5)

        adb.run_cmd(*(cmd_prefix + ["pull", remote_path, local_path]))
        if os.path.exists(local_path):
            logger.info(f"UI dumped to {local_path} on attempt {attempt+1}")
            return local_path

        logger.warning(f"UI dump failed on attempt {attempt+1}.")
        if attempt < 1:
            # Scroll significantly to nudge the view and unblock uiautomator
            logger.info(f"Scrolling to unblock UI dump (attempt {attempt+1}/1)...")
            adb.run_cmd(*(cmd_prefix + ["shell", "input", "swipe", "500", "1500", "500", "500", "300"]))
            time.sleep(2.5)

    logger.error("UI dump failed after 1 scroll attempt. Signalling for vision recovery.")
    return ""
