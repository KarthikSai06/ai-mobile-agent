import json
import os
import logging

logger = logging.getLogger(__name__)

MEMORY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage", "memory.json")

def execute(adb, key: str = None, device_id: str = None) -> bool:
    """
    Deletes a key from memory.json.
    Use this to remove stale or incorrect coordinates/patterns that are no longer valid.
    """
    if not key:
        logger.error("delete_memory: 'key' is required.")
        return False

    try:
        if not os.path.exists(MEMORY_FILE):
            logger.warning("delete_memory: memory.json does not exist.")
            return False

        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            memory = json.load(f)

        if key not in memory:
            logger.warning(f"delete_memory: key '{key}' not found in memory.")
            return False

        del memory[key]
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=2)

        logger.info(f"Memory deleted: '{key}'")
        return True
    except Exception as e:
        logger.error(f"delete_memory error: {e}")
        return False
