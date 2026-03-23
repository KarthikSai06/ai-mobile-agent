from device.adb_controller import AdbController
import logging

logger = logging.getLogger(__name__)

def execute(adb: AdbController, state: str = "on", device_id: str = None) -> bool:
    """
    Toggle WiFi on or off.
    ARGS: state=on|off
    """
    state = state.strip().lower()
    if state not in ("on", "off", "true", "false", "enable", "disable"):
        logger.error(f"set_wifi: invalid state '{state}'. Use on/off.")
        return False

    enabled = "true" if state in ("on", "true", "enable") else "false"

    cmd = []
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(["shell", "cmd", "wifi", "set-wifi-enabled", enabled])

    logger.info(f"Setting WiFi to: {enabled}")
    adb.run_cmd(*cmd)
    return True
