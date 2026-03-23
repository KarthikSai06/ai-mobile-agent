from device.adb_controller import AdbController
import logging

logger = logging.getLogger(__name__)

def execute(adb: AdbController, state: str = "on", device_id: str = None) -> bool:
    """
    Toggle airplane mode on or off.
    ARGS: state=on|off
    Note: On Android 10+ this may require root or a privileged shell.
    """
    state = state.strip().lower()
    enabled = "1" if state in ("on", "true", "enable") else "0"

    cmd_prefix = ["-s", device_id] if device_id else []

    logger.info(f"Setting airplane mode to: {'on' if enabled == '1' else 'off'}")

    # Set the global setting
    adb.run_cmd(*(cmd_prefix + [
        "shell", "settings", "put", "global", "airplane_mode_on", enabled
    ]))

    # Broadcast the change so the system reacts
    adb.run_cmd(*(cmd_prefix + [
        "shell", "am", "broadcast",
        "-a", "android.intent.action.AIRPLANE_MODE",
        "--ez", "state", "true" if enabled == "1" else "false"
    ]))
    return True
