from device.adb_controller import AdbController
import logging

logger = logging.getLogger(__name__)

def execute(adb: AdbController, text: str, x: int = None, y: int = None, device_id: str = None) -> bool:
    """
    Types the given text using ADB.
    If x and y are provided, it taps at that location first to ensure the field is focused.
    """
    if x is not None and y is not None:
        logger.info(f"Tapping at ({x}, {y}) before typing.")
        adb.run_cmd("shell", "input", "tap", str(x), str(y))
    
    # ADB input text doesn't handle spaces well unless properly escaped
    escaped_text = text.replace(" ", "%s")
    cmd = []
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(["shell", "input", "text", escaped_text])
    
    logger.info(f"Executing TYPE_TEXT: '{text}'")
    adb.run_cmd(*cmd)
    return True
