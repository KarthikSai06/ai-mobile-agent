from device.adb_controller import AdbController
import logging
import os
import time

logger = logging.getLogger(__name__)

def execute(adb: AdbController, device_id: str = None, filename: str = None) -> bool:
    """
    Takes a screenshot of the device and saves it to the screenshots directory.
    Optional filename arg (without extension). Defaults to timestamp-based name.
    """
    from config import settings

    if not filename:
        filename = f"screenshot_{int(time.time())}"

    # Ensure .png extension
    if not filename.endswith(".png"):
        filename += ".png"

    save_path = os.path.join(settings.SCREENSHOTS_DIR, filename)

    logger.info(f"Executing TAKE_SCREENSHOT → saving to {save_path}")
    success = adb.take_screenshot(save_path, device_id)

    if success:
        logger.info(f"Screenshot saved: {save_path}")
    else:
        logger.error("Screenshot failed.")

    return success
