import logging
from device.adb_controller import AdbController
from skills import tap, type_text, open_app, press_key, scroll

logger = logging.getLogger(__name__)

class SkillExecutor:
    def __init__(self, adb: AdbController, device_id: str = None):
        self.adb = adb
        self.device_id = device_id
        self.last_elements = []  # To store the last parsed UI state
        
        # Map skill names to their corresponding execute functions
        self.skills = {
            "tap": tap.execute,
            "type_text": type_text.execute,
            "open_app": open_app.execute,
            "press_key": press_key.execute,
            "scroll": scroll.execute
        }

    def set_last_elements(self, elements: list):
        """Updates the internal cache of UI elements for ID lookup."""
        self.last_elements = elements

    def _resolve_id_to_coords(self, args: dict) -> dict:
        """If 'id' is present in args, resolve it to 'x' and 'y' using last_elements index or node_id."""
        if "id" in args and self.last_elements:
            node_id = str(args["id"])
            
            # Try to resolve by index if it's a number (as formatted in format_ui_elements_for_llm)
            if node_id.isdigit():
                idx = int(node_id)
                if 0 <= idx < len(self.last_elements):
                    element = self.last_elements[idx]
                    cx, cy = element.get("center_x"), element.get("center_y")
                    if cx is not None and cy is not None:
                        args["x"] = cx
                        args["y"] = cy
                        args.pop("id", None)
                        logger.info(f"Resolved index ID {node_id} to coordinates ({cx}, {cy}). Element: {element}")
                        return args

            # Fallback to searching by node_id or resource_id if we ever store those
            for element in self.last_elements:
                if str(element.get("resource_id")) == node_id:
                    args["x"] = element["center_x"]
                    args["y"] = element["center_y"]
                    args.pop("id", None)
                    logger.info(f"Resolved resource ID {node_id} to coordinates ({args['x']}, {args['y']})")
                    break
        return args

    def execute_skill(self, skill_name: str, args: dict) -> bool:
        """
        Executes a skill given its name and arguments.
        """
        if skill_name not in self.skills:
            logger.error(f"Unknown skill: {skill_name}")
            return False
            
        skill_func = self.skills[skill_name]
        
        # Resolve IDs if present
        # Always resolve id to x, y if possible, then remove id
        if "id" in args:
            args = self._resolve_id_to_coords(args)
            args.pop("id", None) # Ensure it's gone even if not resolved
        
        import inspect
        sig = inspect.signature(skill_func)
        valid_args = sig.parameters.keys()
        
        # Inject standard arguments
        call_args = {"adb": self.adb, "device_id": self.device_id}
        
        # Filter and add skill-specific arguments
        for k, v in args.items():
            if k in valid_args:
                call_args[k] = v
            else:
                logger.warning(f"Skill {skill_name} doesn't accept argument {k}. Skipping.")
        
        try:
            logger.info(f"Executing {skill_name} with args: {call_args}")
            return skill_func(**call_args)
        except Exception as e:
            logger.error(f"Error executing skill {skill_name}: {e}")
            return False
