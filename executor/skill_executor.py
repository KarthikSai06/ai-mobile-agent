import logging
from device.adb_controller import AdbController
from skills import (
    tap, type_text, open_app, press_key, scroll, save_memory, delete_memory,
    set_wifi, set_bluetooth, set_brightness, set_volume,
    set_airplane_mode, set_flashlight, set_mobile_data, extract_text,
    take_screenshot, summarize_text,
)

logger = logging.getLogger(__name__)

class SkillExecutor:
    def __init__(self, adb: AdbController, device_id: str = None):
        self.adb = adb
        self.device_id = device_id
        self.last_elements = []

        self.skills = {
            "tap": tap.execute,
            "type_text": type_text.execute,
            "open_app": open_app.execute,
            "press_key": press_key.execute,
            "scroll": scroll.execute,
            "save_memory": save_memory.execute,
            "delete_memory": delete_memory.execute,
            # System control skills
            "set_wifi": set_wifi.execute,
            "set_bluetooth": set_bluetooth.execute,
            "set_brightness": set_brightness.execute,
            "set_volume": set_volume.execute,
            "set_airplane_mode": set_airplane_mode.execute,
            "set_flashlight": set_flashlight.execute,
            "set_mobile_data": set_mobile_data.execute,
            # Text extraction
            "extract_text": extract_text.execute,
            # Summarize on-screen content via LLM
            "summarize_text": summarize_text.execute,
            # Screenshot
            "take_screenshot": take_screenshot.execute,
        }


    def set_last_elements(self, elements: list):
        """Updates the internal cache of UI elements for ID lookup."""
        self.last_elements = elements

    def _resolve_memory_refs(self, args: dict) -> dict:
        """
        Expands @memory_key references in string argument values.
        e.g. {"text": "@bujji_summary"} → {"text": "<full stored summary>"}
        Lets the LLM say: ARGS: text=@bujji_summary
        """
        import json, os
        memory_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "storage", "memory.json"
        )
        mem = {}
        if os.path.exists(memory_path):
            try:
                with open(memory_path, "r", encoding="utf-8") as f:
                    mem = json.load(f)
            except Exception:
                pass

        resolved = {}
        for k, v in args.items():
            if isinstance(v, str) and v.startswith("@"):
                key = v[1:]
                if key in mem:
                    logger.info(f"Resolved memory ref @{key} → {len(str(mem[key]))} chars")
                    resolved[k] = mem[key]
                else:
                    logger.warning(f"Memory ref @{key} not found. Keeping original value.")
                    resolved[k] = v
            else:
                resolved[k] = v
        return resolved

    def _resolve_id_to_coords(self, args: dict) -> dict:
        """Resolve 'id' in args to x/y coordinates using last_elements (by index or resource_id)."""
        if "id" not in args or not self.last_elements:
            return args

        node_id = str(args["id"])

        # Try numeric index first
        if node_id.isdigit():
            idx = int(node_id)
            if 0 <= idx < len(self.last_elements):
                element = self.last_elements[idx]
                cx, cy = element.get("center_x"), element.get("center_y")
                if cx is not None and cy is not None:
                    args["x"] = cx
                    args["y"] = cy
                    args.pop("id", None)
                    logger.info(f"Resolved index ID {node_id} → ({cx}, {cy})")
                    return args

        # Try resource_id string match
        for element in self.last_elements:
            if str(element.get("resource_id")) == node_id:
                args["x"] = element["center_x"]
                args["y"] = element["center_y"]
                args.pop("id", None)
                logger.info(f"Resolved resource ID {node_id} → ({args['x']}, {args['y']})")
                return args

        return args

    def _resolve_text_to_coords(self, args: dict) -> dict:
        """
        If the LLM sends tap(text='Telegram') instead of tap(id=N),
        search last_elements by text or content-desc and resolve to x/y.
        """
        label = args.pop("text", None)
        if not label or not self.last_elements:
            if label:
                args["text"] = label  # put it back if we can't resolve
            return args

        label_lower = label.lower()
        for element in self.last_elements:
            el_text = str(element.get("text", "")).lower()
            el_desc = str(element.get("content_desc", "")).lower()
            if label_lower in el_text or label_lower in el_desc:
                args["x"] = element["center_x"]
                args["y"] = element["center_y"]
                logger.info(f"Resolved text='{label}' → ({args['x']}, {args['y']}) via element text/desc")
                return args

        logger.warning(f"Could not resolve text='{label}' to any UI element. Signalling vision_needed.")
        return {"vision_needed": True, "label": label}  # signal agent_loop to escalate to vision

    def execute_skill(self, skill_name: str, args: dict):
        """
        Executes a skill given its name and arguments.
        """
        if skill_name not in self.skills:
            logger.error(f"Unknown skill: {skill_name}")
            return False

        skill_func = self.skills[skill_name]

        if "id" in args:
            args = self._resolve_id_to_coords(args)
            args.pop("id", None)

        # For tap: if x/y still absent but LLM sent text=, resolve via element label
        if skill_name == "tap" and "x" not in args and "y" not in args and "text" in args:
            args = self._resolve_text_to_coords(args)
            # If vision escalation is needed, propagate the signal up to agent_loop
            if isinstance(args, dict) and args.get("vision_needed"):
                return args  # Return vision_needed signal dict

        # Guard: tap requires x and y — fail fast if still missing after all resolution
        if skill_name == "tap" and (not isinstance(args, dict) or "x" not in args or "y" not in args):
            logger.error(f"tap skill called without x/y and could not resolve them from args {args}. Skipping.")
            return False

        # Memory key resolution: if any arg value is "@key_name", replace with stored memory value
        args = self._resolve_memory_refs(args)

        import inspect
        sig = inspect.signature(skill_func)
        valid_args = sig.parameters.keys()

        call_args = {"adb": self.adb, "device_id": self.device_id}

        # Pass last_elements to extract_text / summarize_text so they can read current screen content
        if skill_name in ("extract_text", "summarize_text"):
            call_args["_last_elements"] = self.last_elements

        import re

        for k, v in args.items():
            if k in valid_args:
                if k in ['x', 'y', 'x1', 'y1', 'x2', 'y2'] and isinstance(v, str):
                    try:
                        clean_val = re.sub(r'[^\d-]', '', str(v))
                        v = int(clean_val) if clean_val else 0
                    except Exception as e:
                        logger.warning(f"Failed to sanitize coordinate {k}={v}: {e}")
                call_args[k] = v
            else:
                logger.warning(f"Skill {skill_name} doesn't accept argument {k}. Skipping.")

        try:
            logger.info(f"Executing {skill_name} with args: {call_args}")
            return skill_func(**call_args)
        except Exception as e:
            logger.error(f"Error executing skill {skill_name}: {e}")
            return False

