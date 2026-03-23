from device.adb_controller import AdbController
import logging

logger = logging.getLogger(__name__)

def execute(adb: AdbController, state: str = "on", device_id: str = None) -> bool:
    """
    Toggle mobile data on or off.
    ARGS: state=on|off
    """
    state = state.strip().lower()
    action = "enable" if state in ("on", "true", "enable") else "disable"

    cmd_prefix = ["-s", device_id] if device_id else []

    logger.info(f"Setting mobile data to: {action}")
    adb.run_cmd(*(cmd_prefix + ["shell", "svc", "data", action]))
    return True
