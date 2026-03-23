from device.adb_controller import AdbController
import json
import os
import logging

logger = logging.getLogger(__name__)

def execute(adb: AdbController, save_as: str = "", device_id: str = None,
            _last_elements: list = None) -> bool:
    """
    Extracts all visible text from the current screen using the last parsed UI elements.
    Optionally saves the result to agent memory.
    ARGS:
      save_as=<key>   — memory key to store the extracted text (optional)
    Returns True and logs the extracted text.
    """
    if not _last_elements:
        logger.warning("extract_text: no UI elements available. Run after a UI dump step.")
        return False

    texts = []
    for el in _last_elements:
        t = el.get("text", "").strip()
        d = el.get("content_desc", "").strip()
        if t and t not in texts:
            texts.append(t)
        if d and d not in texts and d != t:
            texts.append(d)

    extracted = "\n".join(texts) if texts else "(no text found on screen)"
    logger.info(f"Extracted text from screen:\n{extracted}")
    print(f"\n[extract_text]\n{extracted}\n")

    # Optionally save to memory
    if save_as:
        memory_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "storage", "memory.json"
        )
        try:
            mem = {}
            if os.path.exists(memory_path):
                with open(memory_path, "r", encoding="utf-8") as f:
                    mem = json.load(f)
            mem[save_as] = extracted
            with open(memory_path, "w", encoding="utf-8") as f:
                json.dump(mem, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved extracted text to memory key '{save_as}'")
        except Exception as e:
            logger.error(f"extract_text: failed to save to memory: {e}")

    return True
