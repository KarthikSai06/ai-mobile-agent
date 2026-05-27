import logging
import time
import os
from device.adb_controller import AdbController
from ui.dump_ui import dump_ui_hierarchy
from ui.ui_parser import parse_ui_xml, format_ui_elements_for_llm
from executor.skill_executor import SkillExecutor
from planner.llm_planner import LLMPlanner

logger = logging.getLogger(__name__)

class AgentLoop:
    def __init__(self, device_id: str = None):
        from config import settings
        self.adb = AdbController(adb_path=settings.ADB_PATH)
        self.device_id = device_id
        
                                                            
        if not self.device_id:
             devices = self.adb.get_devices()
             if devices:
                 self.device_id = devices[0]
                 logger.info(f"Using device: {self.device_id}")
             else:
                 logger.error("No Android devices found. Ensure ADB is connected and authorized.")

        self.executor = SkillExecutor(self.adb, self.device_id)
        self.planner = LLMPlanner()
        self.history = []           # list of {"action": str, "outcome": str}
        self.last_ui_str = ""

    def _check_completion_via_screenshot(self, task: str, step: int, label: str) -> bool:
        """Take a screenshot and ask the vision model if the task is done."""
        from config import settings
        screenshot_path = os.path.join(settings.SCREENSHOTS_DIR, f"completion_{step}.png")
        if self.adb.take_screenshot(screenshot_path, self.device_id):
            if self.planner.check_task_done_from_screenshot(task, screenshot_path):
                logger.info(f"Task confirmed complete via screenshot ({label}). Done!")
                return True
        return False

    def run(self, task: str, max_steps: int = 15):
        """
        Orchestrates the main execution loop: Dump -> Parse -> Plan -> Execute
        Implements 3 vision triggers:
        (1) Loop detected -> vision first, BACK as fallback
        (2) no_change_streak >= 3 -> vision
        (3) vision_needed signal from executor -> vision locate
        Plus: task completion checking after key actions.
        """
        logger.info(f"Starting agent task: {task}")
        from config import settings

        # --- Task Refiner: Expand raw user instruction into explicit steps BEFORE looping ---
        logger.info("Refining task with LLM before starting...")
        task = self.planner.refine_task(task)
        logger.info(f"Refined task:\n{task}")

        no_change_streak = 0
        # Track how many successful actions have been executed
        # to decide when to check for task completion
        success_count = 0

        for step in range(max_steps):
            logger.info(f"=== Step {step+1}/{max_steps} ===")
            
            # 1. Dump UI hierarchy
            xml_path = dump_ui_hierarchy(self.adb, self.device_id)
            if not xml_path:
                logger.warning("UI dump failed — screen may have a fullscreen video/ad. Checking task status via screenshot...")
                screenshot_path = os.path.join(settings.SCREENSHOTS_DIR, f"recovery_{step}.png")
                if self.adb.take_screenshot(screenshot_path, self.device_id):
                    # ─── First, check if the task is already done (video playing, etc.) ───
                    if self.planner.check_task_done_from_screenshot(task, screenshot_path):
                        logger.info("Task confirmed complete via screenshot (no tap needed). Done!")
                        break  # clean exit — video is already playing

                    # ─── Task not done yet — ask vision model what to tap ───────────────
                    recovery = self.planner.get_action_from_screenshot(task, screenshot_path)
                    logger.info(f"Vision recovery action: {recovery}")
                    if recovery.get("skill") in ["tap", "scroll"]:
                        self.executor.execute_skill(recovery["skill"], recovery.get("args", {}))
                        time.sleep(1.0)  # wait for screen to settle after tap

                        # Check if the task is now complete (e.g. video is playing)
                        verify_path = os.path.join(settings.SCREENSHOTS_DIR, f"verify_{step}.png")
                        if self.adb.take_screenshot(verify_path, self.device_id):
                            if self.planner.check_task_done_from_screenshot(task, verify_path):
                                logger.info("Task confirmed complete via screenshot. Done!")
                                break  # clean exit — task succeeded
                        continue  # not done yet, retry this step
                logger.error("Vision recovery also failed. Aborting.")
                break
                
            # 2. Parse UI elements
            ui_elements = parse_ui_xml(xml_path)
            # Sort: clickable first, then top-to-bottom reading order, and cap at 80 elements to match formatted indices
            ui_elements = sorted(ui_elements, key=lambda e: (not e["clickable"], e["center_y"]))[:80]
            ui_str = format_ui_elements_for_llm(ui_elements)
            logger.info(f"UI Elements sent to LLM:\n{ui_str}")
            
            # Check for UI change and update no_change_streak
            if self.last_ui_str == ui_str:
                no_change_streak += 1
            else:
                no_change_streak = 0
            self.last_ui_str = ui_str

            # --- Trigger 2: NO_CHANGE streak (UI-based) >= 3 → Vision ---
            if no_change_streak >= 3:
                logger.warning(f"Trigger 2: {no_change_streak} consecutive NO_CHANGE steps. Escalating to vision.")
                # Before escalating, check if the task is already done
                if self._check_completion_via_screenshot(task, step, "no-change check"):
                    break
                screenshot_path = os.path.join(settings.SCREENSHOTS_DIR, f"no_change_{step}.png")
                if self.adb.take_screenshot(screenshot_path, self.device_id):
                    recent = " → ".join(h["action"] for h in self.history[-3:] if isinstance(h, dict))
                    hint = (
                        f"The agent is stuck. Task: {task}\n"
                        f"Recent actions: {recent}\n"
                        "Look at the screenshot and find the NEXT element to tap to make progress. "
                        "Do NOT tap the search bar if results are visible below it. Tap the actual result or the next input field."
                    )
                    vision_action = self.planner.get_action_from_screenshot(task, screenshot_path, hint=hint)
                    logger.info(f"Vision NO_CHANGE action: {vision_action}")
                    if vision_action.get("skill") in ["tap", "scroll"]:
                        self.executor.execute_skill(vision_action["skill"], vision_action.get("args", {}))
                no_change_streak = 0
                time.sleep(1.0)
                continue

            action_plan = self.planner.plan_next_action(task, ui_str, self.history)
                
            skill_name = action_plan.get("skill")
            args = action_plan.get("args", {})
            
            logger.info(f"Planned Action -> SKILL: {skill_name}, ARGS: {args}")
            
                                                                    
            self.executor.set_last_elements(ui_elements)

                               
            if skill_name == "done":
                logger.info("Task marked as DONE by planner.")
                break
                
            # Execute the planned action
            result = self.executor.execute_skill(skill_name, args)

            # --- Trigger 3: tap(text=X) not found in UI → Vision Locate ---
            if isinstance(result, dict) and result.get("vision_needed"):
                label = result.get("label", "")
                logger.warning(f"Trigger 3: tap(text='{label}') not found. Escalating to vision.")
                screenshot_path = os.path.join(settings.SCREENSHOTS_DIR, f"vision_locate_{step}.png")
                tap_success = False
                if self.adb.take_screenshot(screenshot_path, self.device_id):
                    hint = f"Find and tap the element labeled '{label}' or scroll to reveal it."
                    vision_action = self.planner.get_action_from_screenshot(task, screenshot_path, hint=hint)
                    logger.info(f"Vision locate action: {vision_action}")
                    if vision_action.get("skill") in ["tap", "scroll"]:
                        self.executor.execute_skill(vision_action["skill"], vision_action.get("args", {}))
                        tap_success = True
                outcome = "SUCCESS" if tap_success else "FAILED"
                self.history.append({"action": f"{skill_name}({args})", "outcome": outcome})
                logger.info(f"History entry (vision locate): {skill_name}({args}) → {outcome}")
                time.sleep(1.0)
                continue

            success = bool(result)

            if not success:
                outcome = "FAILED"
                logger.warning("Action execution failed or returned False.")
            else:
                is_input_field = False
                if skill_name == "tap":
                    target_el = None
                    if "id" in args and isinstance(args["id"], int) and args["id"] < len(ui_elements):
                        target_el = ui_elements[args["id"]]
                    elif "x" in args and "y" in args:
                        for el in ui_elements:
                            if el.get("center_x") == args["x"] and el.get("center_y") == args["y"]:
                                target_el = el
                                break
                    
                    if target_el:
                        res_id = target_el.get("resource_id", "").lower()
                        class_name = target_el.get("class_name", "").lower()
                        text = target_el.get("text", "").lower()
                        desc = target_el.get("content_desc", "").lower()
                        
                        if (
                            "query" in res_id or "search" in res_id or "input" in res_id or "edit" in res_id or
                            "edittext" in class_name or
                            "search" in text or "type" in text or "listen" in text or "find" in text or
                            "search" in desc or "type" in desc or "listen" in desc or "find" in desc
                        ):
                            is_input_field = True

                post_xml_path = dump_ui_hierarchy(self.adb, self.device_id)
                if post_xml_path:
                    post_ui_elements = parse_ui_xml(post_xml_path)
                    post_ui_str = format_ui_elements_for_llm(post_ui_elements)
                    if post_ui_str == ui_str and not is_input_field:
                        outcome = "NO_CHANGE"
                    else:
                        outcome = "SUCCESS"
                        success_count += 1
                else:
                    outcome = "SUCCESS"
                    success_count += 1

            action_record = f"{skill_name}({args})"
            self.history.append({"action": action_record, "outcome": outcome})
            logger.info(f"History entry: {action_record} → {outcome}")

            # --- Task Completion Check ---
            # After 3+ successful actions, periodically check if the task is done
            # This catches cases where the agent has completed the task but
            # doesn't realize it (e.g. directions are showing, video is playing)
            if success and success_count >= 3 and success_count % 2 == 1:
                logger.info("Checking if task is complete after multiple successful actions...")
                if self._check_completion_via_screenshot(task, step, "periodic check"):
                    break

            # --- Trigger 1: Loop Detected → Vision First, BACK as fallback ---
            if (len(self.history) >= 3 and
                    self.history[-1]["action"] == self.history[-2]["action"] == self.history[-3]["action"]):
                logger.warning(f"Trigger 1: Loop — '{action_record}' repeated 3x. Trying vision before BACK.")
                # First check if the task is actually done despite the loop
                if self._check_completion_via_screenshot(task, step, "loop-check"):
                    break
                screenshot_path = os.path.join(settings.SCREENSHOTS_DIR, f"loop_{step}.png")
                vision_tapped = False
                if self.adb.take_screenshot(screenshot_path, self.device_id):
                    recent = " → ".join(h["action"] for h in self.history[-3:] if isinstance(h, dict))
                    hint = (
                        f"The agent is looping on the same action. Task: {task}\n"
                        f"Repeated action: {action_record}\n"
                        "This action is not making progress. Look at the screenshot and find a DIFFERENT element — "
                        "specifically the next result, button, or input field needed for the task. "
                        "Do NOT tap the same element as before. If search results are visible, tap one of them."
                    )
                    vision_action = self.planner.get_action_from_screenshot(task, screenshot_path, hint=hint)
                    logger.info(f"Vision loop-break action: {vision_action}")
                    if vision_action.get("skill") in ["tap", "scroll"]:
                        self.executor.execute_skill(vision_action["skill"], vision_action.get("args", {}))
                        vision_tapped = True
                if not vision_tapped:
                    logger.warning("Vision gave no tap — falling back to BACK key.")
                    self.executor.execute_skill("press_key", {"key": "BACK"})
                time.sleep(0.8)

            time.sleep(1.0)
            
        else:
            logger.warning(f"Task reached maximum steps ({max_steps}) without finishing.")
            
        logger.info("Agent loop finished.")
