import os
import time
import logging
from device.adb_controller import AdbController
from config import settings

logger = logging.getLogger(__name__)

def dump_ui_hierarchy(adb: AdbController, device_id: str = None) -> str:
    """
    Dumps the UI hierarchy from the Android device and pulls the XML file to the local storage.
    Returns the path to the downloaded XML file.
    """
    remote_path = "/sdcard/ui_dump.xml"
    local_filename = f"ui_dump_{int(time.time())}.xml"
    local_path = os.path.join(settings.STORAGE_DIR, local_filename)
    
    cmd_prefix = []
    if device_id:
        cmd_prefix = ["-s", device_id]

    logger.info("Dumping UI hierarchy...")
    
    # Dump UI
    dump_cmd = cmd_prefix + ["shell", "uiautomator", "dump", remote_path]
    dump_output = adb.run_cmd(*dump_cmd)
    
    if "UI hierchary dumped to" not in dump_output and "dumped to" not in dump_output:
        logger.warning(f"Unexpected output from uiautomator dump: {dump_output}")

    # Pull the file
    pull_cmd = cmd_prefix + ["pull", remote_path, local_path]
    adb.run_cmd(*pull_cmd)
    
    if os.path.exists(local_path):
        logger.info(f"UI dumped to {local_path}")
        return local_path
    else:
        logger.error("Failed to pull UI dump.")
        return ""
