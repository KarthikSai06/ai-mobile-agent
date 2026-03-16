from device.adb_controller import AdbController
import logging

logger = logging.getLogger(__name__)

def execute(adb: AdbController, key: str, device_id: str = None) -> bool:
    """
    Presses a physical or standard key.
    Examples: HOME, BACK, ENTER, SEARCH
    """
    key_mapping = {
        "HOME": "KEYCODE_HOME",
        "BACK": "KEYCODE_BACK",
        "ENTER": "KEYCODE_ENTER",
        "SEARCH": "KEYCODE_SEARCH",
        "VOLUME_UP": "KEYCODE_VOLUME_UP",
        "VOLUME_DOWN": "KEYCODE_VOLUME_DOWN",
        "TAB": "KEYCODE_TAB"
    }
    
    keycode = key_mapping.get(key.upper(), key)
    
    cmd = []
    if device_id:
        cmd.extend(["-s", device_id])
    
    cmd.extend(["shell", "input", "keyevent", keycode])
    
    logger.info(f"Executing PRESS_KEY: '{key}' ({keycode})")
    adb.run_cmd(*cmd)
    return True
