from device.adb_controller import AdbController
import logging

logger = logging.getLogger(__name__)

def execute(adb: AdbController, level: str = "128", mode: str = "manual", device_id: str = None) -> bool:
    """
    Set screen brightness level or toggle auto-brightness.
    ARGS:
      level=0-255         — exact brightness value (only used in manual mode)
      level=10-100%       — percentage shorthand (e.g. level=50%)
      mode=auto|manual    — auto-brightness on/off (default: manual)
    """
    cmd_prefix = ["-s", device_id] if device_id else []

    # Handle auto mode
    if mode.strip().lower() == "auto":
        logger.info("Enabling auto-brightness")
        adb.run_cmd(*(cmd_prefix + ["shell", "settings", "put", "system", "screen_brightness_mode", "1"]))
        return True

    # Disable auto-brightness first
    adb.run_cmd(*(cmd_prefix + ["shell", "settings", "put", "system", "screen_brightness_mode", "0"]))

    # Resolve level
    level_str = str(level).strip().rstrip("%")
    try:
        val = int(level_str)
    except ValueError:
        logger.error(f"set_brightness: invalid level '{level}'")
        return False

    # Convert percentage to 0-255
    if "%" in str(level):
        val = max(0, min(255, int(val * 255 / 100)))
    else:
        val = max(0, min(255, val))

    logger.info(f"Setting brightness to: {val}/255")
    adb.run_cmd(*(cmd_prefix + ["shell", "settings", "put", "system", "screen_brightness", str(val)]))
    return True
