from device.adb_controller import AdbController
import logging

logger = logging.getLogger(__name__)

def execute(adb: AdbController, state: str = "on", device_id: str = None) -> bool:
    """
    Toggle Bluetooth on or off.
    ARGS: state=on|off
    """
    state = state.strip().lower()
    if state not in ("on", "off", "true", "false", "enable", "disable"):
        logger.error(f"set_bluetooth: invalid state '{state}'. Use on/off.")
        return False

    action = "enable" if state in ("on", "true", "enable") else "disable"

    cmd = []
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(["shell", "cmd", "bluetooth_manager", action])

    logger.info(f"Setting Bluetooth to: {action}")
    adb.run_cmd(*cmd)
    return True
