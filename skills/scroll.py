from device.adb_controller import AdbController
import logging

logger = logging.getLogger(__name__)

def execute(adb: AdbController, direction: str = None, x1: int = None, y1: int = None, x2: int = None, y2: int = None, duration_ms: int = 500, device_id: str = None) -> bool:
    """
    Scrolls the screen by direction ('up', 'down', 'left', 'right') or swipes from (x1, y1) to (x2, y2).
    """
    if direction:
        direction = direction.lower()
        # Default typical screen swipe coordinates (center screen)
        # down = swipe finger up (scroll content down)
        if direction == "down":
            x1, y1, x2, y2 = 500, 1500, 500, 500
        elif direction == "up":
            x1, y1, x2, y2 = 500, 500, 500, 1500
        elif direction == "left":
            x1, y1, x2, y2 = 800, 1000, 200, 1000
        elif direction == "right":
            x1, y1, x2, y2 = 200, 1000, 800, 1000
        else:
            logger.error(f"Invalid scroll direction: {direction}")
            return False

    if x1 is None or y1 is None or x2 is None or y2 is None:
        logger.error("Scroll requires either 'direction' or ('x1', 'y1', 'x2', 'y2').")
        return False

    cmd = []
    if device_id:
        cmd.extend(["-s", device_id])
    
    cmd.extend(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])
    
    logger.info(f"Executing SCROLL/SWIPE from ({x1}, {y1}) to ({x2}, {y2})")
    adb.run_cmd(*cmd)
    return True
