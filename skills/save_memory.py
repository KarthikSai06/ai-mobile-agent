import json
import os
import logging

logger = logging.getLogger(__name__)

MEMORY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage", "memory.json")

def execute(adb, key: str = None, value: str = None, device_id: str = None) -> bool:
    """
    Saves a key-value pair to memory.json.
    Use this to remember coordinated, UI element IDs, or successful action patterns
    that can be reused in future steps to avoid repeated searching.
    """
    if not key or not value:
        logger.error("save_memory: 'key' and 'value' are required.")
        return False

    try:
        memory = {}
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                memory = json.load(f)

        memory[key] = value
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=2)

        logger.info(f"Memory saved: '{key}' = '{value}'")
        return True
    except Exception as e:
        logger.error(f"save_memory error: {e}")
        return False
