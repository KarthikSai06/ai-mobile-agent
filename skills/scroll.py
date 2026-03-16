from device.adb_controller import AdbController
import logging

logger = logging.getLogger(__name__)

def execute(adb: AdbController, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 500, device_id: str = None) -> bool:
    """
    Swipes from (x1, y1) to (x2, y2).
    """
    cmd = []
    if device_id:
        cmd.extend(["-s", device_id])
    
    cmd.extend(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])
    
    logger.info(f"Executing SCROLL/SWIPE from ({x1}, {y1}) to ({x2}, {y2})")
    adb.run_cmd(*cmd)
    return True
