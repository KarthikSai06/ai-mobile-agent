from device.adb_controller import AdbController
import logging

logger = logging.getLogger(__name__)

# Stream IDs for Android audio manager
STREAM_IDS = {
    "ring":    2,
    "media":   3,
    "alarm":   4,
    "notification": 5,
    "system":  1,
}

def execute(adb: AdbController, level: int = 5, stream: str = "media", device_id: str = None) -> bool:
    """
    Set volume for a given audio stream.
    ARGS:
      level=0-15        — volume level (max varies per device, 15 is safe max)
      stream=media|ring|alarm|notification|system
    """
    stream_id = STREAM_IDS.get(stream.strip().lower(), 3)  # default: media
    level = max(0, min(15, int(level)))

    cmd_prefix = ["-s", device_id] if device_id else []

    logger.info(f"Setting {stream} volume to {level} (stream_id={stream_id})")
    adb.run_cmd(*(cmd_prefix + [
        "shell", "media", "volume",
        "--set", str(level),
        "--stream", str(stream_id),
        "--show"
    ]))
    return True
