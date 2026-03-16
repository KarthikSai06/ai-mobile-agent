from device.adb_controller import AdbController
import logging

logger = logging.getLogger(__name__)

def execute(adb: AdbController, x: int, y: int, device_id: str = None) -> bool:
    """
    Taps on the screen at the given (x, y) coordinates.
    """
    cmd = []
    if device_id:
        cmd.extend(["-s", device_id])
    
    cmd.extend(["shell", "input", "tap", str(x), str(y)])
    
    logger.info(f"Executing TAP at ({x}, {y})")
    adb.run_cmd(*cmd)
    return True
