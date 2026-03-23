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
        # no_change_streak is managed as a local var inside run() — not stored on self

    def run(self, task: str, max_steps: int = 15):
        """
        Orchestrates the main execution loop: Dump -> Parse -> Plan -> Execute
        Implements 3 vision triggers:
        (1) Loop detected -> vision first, BACK as fallback
        (2) no_change_streak >= 3 -> vision
        (3) vision_needed signal from executor -> vision locate
        """
        logger.info(f"Starting agent task: {task}")
        from config import settings

        # --- Task Refiner: Expand raw user instruction into explicit steps BEFORE looping ---
        logger.info("Refining task with LLM before starting...")
        task = self.planner.refine_task(task)
        logger.info(f"Refined task:\n{task}")

        no_change_streak = 0

        for step in range(max_steps):
            logger.info(f"=== Step {step+1}/{max_steps} ===")
            
            # 1. Dump UI hierarchy
            xml_path = dump_ui_hierarchy(self.adb, self.device_id)
            if not xml_path:
                logger.warning("UI dump failed — screen may have a fullscreen video/ad. Trying vision recovery...")
                screenshot_path = os.path.join(settings.SCREENSHOTS_DIR, f"recovery_{step}.png")
                if self.adb.take_screenshot(screenshot_path, self.device_id):
                    recovery = self.planner.get_action_from_screenshot(task, screenshot_path)
                    logger.info(f"Vision recovery action: {recovery}")
                    if recovery.get("skill") == "tap":
                        self.executor.execute_skill("tap", recovery["args"])
                        time.sleep(2.5)  # wait for screen to settle after tap

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
                    if vision_action.get("skill") == "tap":
                        self.executor.execute_skill("tap", vision_action["args"])
                no_change_streak = 0
                time.sleep(2.0)
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
                    if vision_action.get("skill") == "tap":
                        self.executor.execute_skill("tap", vision_action["args"])
                        tap_success = True
                outcome = "SUCCESS" if tap_success else "FAILED"
                self.history.append({"action": f"{skill_name}({args})", "outcome": outcome})
                logger.info(f"History entry (vision locate): {skill_name}({args}) → {outcome}")
                time.sleep(2.0)
                continue

            success = bool(result)

            # Re-dump UI after the action to detect whether anything changed
            post_xml_path = dump_ui_hierarchy(self.adb, self.device_id)
            post_ui_str = ""
            if post_xml_path:
                post_elements = parse_ui_xml(post_xml_path)
                post_ui_str = format_ui_elements_for_llm(post_elements)

            if not success:
                outcome = "FAILED"
                logger.warning("Action execution failed or returned False.")
            elif post_ui_str and post_ui_str == ui_str:
                outcome = "NO_CHANGE"
                logger.info("Action executed but UI did not change (e.g., keyboard pop-up or scroll end).")
            else:
                outcome = "SUCCESS"

            action_record = f"{skill_name}({args})"
            self.history.append({"action": action_record, "outcome": outcome})
            logger.info(f"History entry: {action_record} → {outcome}")

            # --- Trigger 1: Loop Detected → Vision First, BACK as fallback ---
            if (len(self.history) >= 3 and
                    self.history[-1]["action"] == self.history[-2]["action"] == self.history[-3]["action"]):
                logger.warning(f"Trigger 1: Loop — '{action_record}' repeated 3x. Trying vision before BACK.")
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
                    if vision_action.get("skill") == "tap":
                        self.executor.execute_skill("tap", vision_action["args"])
                        vision_tapped = True
                if not vision_tapped:
                    logger.warning("Vision gave no tap — falling back to BACK key.")
                    self.executor.execute_skill("press_key", {"key": "BACK"})
                time.sleep(1.5)

            time.sleep(2.0)
            
        else:
            logger.warning(f"Task reached maximum steps ({max_steps}) without finishing.")
            
        logger.info("Agent loop finished.")
