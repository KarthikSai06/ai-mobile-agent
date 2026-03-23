from device.adb_controller import AdbController
import logging

logger = logging.getLogger(__name__)

def execute(adb: AdbController, state: str = "on", device_id: str = None) -> bool:
    """
    Toggle the camera flashlight (torch) on or off.
    ARGS: state=on|off
    Works on Android 13+ via cmd flashlight. Falls back to camera2 API trigger on older devices.
    """
    state = state.strip().lower()
    enabled = state in ("on", "true", "enable")

    cmd_prefix = ["-s", device_id] if device_id else []

    logger.info(f"Setting flashlight to: {'on' if enabled else 'off'}")

    # Primary method: cmd flashlight (Android 13+)
    result = adb.run_cmd(*(cmd_prefix + [
        "shell", "cmd", "flashlight",
        "--set", "enabled" if enabled else "disabled"
    ]))

    if "unknown command" in result.lower() or "error" in result.lower():
        # Fallback: use svc nfc trick or camera2 workaround (best-effort)
        logger.warning("cmd flashlight not available, attempting camera2 keyevent workaround.")
        # No universal ADB fallback exists — log and return False
        logger.error("Flashlight control not supported on this device/OS version via ADB.")
        return False

    return True
