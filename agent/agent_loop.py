import logging
import time
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
        
        # If no device_id provided, pick the first connected
        if not self.device_id:
             devices = self.adb.get_devices()
             if devices:
                 self.device_id = devices[0]
                 logger.info(f"Using device: {self.device_id}")
             else:
                 logger.error("No Android devices found. Ensure ADB is connected and authorized.")

        self.executor = SkillExecutor(self.adb, self.device_id)
        self.planner = LLMPlanner()
        self.history = []

    def run(self, task: str, max_steps: int = 15):
        """
        Orchestrates the main execution loop: Dump -> Parse -> Plan -> Execute
        """
        logger.info(f"Starting agent task: {task}")
        
        for step in range(max_steps):
            logger.info(f"=== Step {step+1}/{max_steps} ===")
            
            # 1. Dump UI
            xml_path = dump_ui_hierarchy(self.adb, self.device_id)
            if not xml_path:
                logger.error("Failed to dump UI hierarchy. Aborting.")
                break
                
            # 2. Parse UI Elements
            ui_elements = parse_ui_xml(xml_path)
            ui_str = format_ui_elements_for_llm(ui_elements)
            logger.info(f"UI Elements sent to LLM:\n{ui_str}")
            
            # 3. Plan Next Action
            action_plan = self.planner.plan_next_action(task, ui_str, self.history)
            skill_name = action_plan.get("skill")
            args = action_plan.get("args", {})
            
            logger.info(f"Planned Action -> SKILL: {skill_name}, ARGS: {args}")
            
            # Update executor with latest elements for ID resolution
            self.executor.set_last_elements(ui_elements)

            # 4. Execute Action
            if skill_name == "done":
                logger.info("Task marked as DONE by planner.")
                break
                
            success = self.executor.execute_skill(skill_name, args)
            
            # Save to history for the next iteration
            action_record = f"{skill_name}({args})"
            self.history.append(action_record)
            
            if not success:
                logger.warning("Action execution failed or returned False.")
            
            # Wait for UI to settle and animations to finish
            time.sleep(2.0)
            
        else:
            logger.warning(f"Task reached maximum steps ({max_steps}) without finishing.")
            
        logger.info("Agent loop finished.")
