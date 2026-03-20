import logging
import re
import os
import shlex
import base64
import traceback

logger = logging.getLogger(__name__)

                                               
try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("openai package not found. Will use mock planner unless installed.")

class LLMPlanner:
    def __init__(self):
        from config import settings
        self.api_key = settings.OPENAI_API_KEY
        self.base_url = settings.LLM_BASE_URL
        self.model = settings.LLM_MODEL
        self.vision_model = getattr(settings, "LLM_VISION_MODEL", "moondream:latest")
        
        self.system_prompt = """You are an Android agent. Output ONE action per turn.

Skills:
  tap            ARGS: id=<n>   OR   x=<n> y=<n>
  type_text      ARGS: text=<string>
  open_app       ARGS: package_name=<pkg>   (no other args)
  press_key      ARGS: key=HOME|BACK|ENTER
  scroll         ARGS: x1=500 y1=1500 x2=500 y2=500
  save_memory    ARGS: key=<name> value=<x,y or description>
  delete_memory  ARGS: key=<name>
  done           ARGS: (none)

Rules:
  1. open_app only needs package_name. Never add id/x/y/text to it.
  2. Prefer id over coordinates when available.
  3. If you just tapped a text field/search bar and it succeeded, DO NOT tap it again. Assume the keyboard is open and proceed immediately to type_text.
  4. If Stored Memory contains the coordinates for an element you need, use those coordinates directly instead of searching the UI.
  5. After successfully locating a hard-to-find element (e.g., a search bar or send button), call save_memory to store its coordinates for future use.
  6. CRITICAL: After typing a search term, the search bar element will now show your typed text (e.g., text='bujji' desc='Search Chats'). Do NOT tap this element — it is the search bar, not a result. Tap the actual search result that appears BELOW it (e.g., 'Bujji, bot', 'Bujji, @Karthikkammalabot').
  7. CRITICAL — Identifying your current screen:
     - YOU ARE ON A PROFILE PAGE if you see 'Message', 'Mute', 'Call'/'Share' buttons in a horizontal row near y=738 AND there is NO 'Bot menu' or 'Emoji, stickers, and GIFs' element visible. Action: tap the 'Message' button (at y=738) to enter the chat.
     - YOU ARE IN THE CHAT WINDOW if you see 'desc=Emoji, stickers, and GIFs' or 'desc=Bot menu' in the UI elements. The message input box will be labeled 'Message' near y > 2000. Action: IMMEDIATELY tap the 'Message' input box (at the bottom) and type your text. Do NOT tap the contact name/header (e.g., 'Bujji\nbot' at the top) — that takes you BACK to the profile page and will undo all progress.
  8. CRITICAL: Never tap a three-dot menu button or options icon unless explicitly needed. If you see a dropdown with 'Night Mode', 'New Group', 'Saved Messages' — press BACK immediately to close it and look for the correct element instead.
  9. Output ONLY the two lines below — nothing else.

Format (copy exactly):
SKILL: <name>
ARGS: <key=val ...>"""
        
        if HAS_OPENAI and self.api_key:
             self.client = openai.OpenAI(
                 api_key=self.api_key,
                 base_url=self.base_url if self.base_url else None
             )
        else:
             self.client = None

    def plan_next_action(self, task: str, ui_elements_str: str, history: list, vision_insight: str = None) -> dict:
        """
        Queries the LLM to decide the next action.
        Returns a dictionary like {"skill": "tap", "args": {"x": 100, "y": 200}}
        """
        # Format history with outcome labels so the model can learn from past mistakes
        history_lines = []
        for h in history[-5:]:
            if isinstance(h, dict):
                history_lines.append(f"  {h['action']} → {h['outcome']}")
            else:
                history_lines.append(f"  {h}")
        history_str = "\n".join(history_lines) if history_lines else "  (none)"

        # Load saved memory and inject into prompt
        import json, os
        memory_str = ""
        memory_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage", "memory.json")
        if os.path.exists(memory_path):
            try:
                with open(memory_path, "r", encoding="utf-8") as f:
                    mem = json.load(f)
                if mem:
                    memory_lines = "\n".join(f"  {k}: {v}" for k, v in mem.items())
                    memory_str = f"\nStored Memory (use these coordinates/info directly):\n{memory_lines}\n"
            except Exception:
                pass

        # Fix 1: Always pass the FULL UI to the LLM — vision is a soft hint, not a filter
        hint_line = ""
        if vision_insight:
            hint_line = f"\nVision hint: the relevant element is likely in the {vision_insight} area.\n"

        user_prompt = (
            f"Task: {task}\n"
            f"{hint_line}"
            f"{memory_str}"
            f"\nAction History:\n{history_str}\n"
            f"\nExample:\nSKILL: tap\nARGS: id=3\n"
            f"\nUI Elements:\n{ui_elements_str}\n"
            f"\nYour action:"
        )

        if not self.client:
            logger.warning("No LLM client configured. Returning mock 'done' action.")
            print("\n--- MOCK LLM PLANNER ---")
            print(f"Task: {task}")
            print(f"UI Elements found: {len(ui_elements_str.splitlines())}")
            print("------------------------\n")
            return {"skill": "done", "args": {}}

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            output = self._call_llm(messages)
        except Exception as e:
            logger.error(f"LLM API Error: {e}")
            return {"skill": "done", "args": {}}

        result = self._parse_llm_output(output)

        # Fix 5: If output was malformed, retry once with a stripped-down prompt
        if result is None:
            logger.warning("Malformed LLM output. Retrying with simplified prompt.")
            retry_messages = [
                {"role": "system", "content": "Output ONLY:\nSKILL: <name>\nARGS: <key=val>"},
                {"role": "user", "content": f"Task: {task}\nReply with one action."},
            ]
            try:
                retry_output = self._call_llm(retry_messages)
                result = self._parse_llm_output(retry_output)
            except Exception as e:
                logger.error(f"Retry LLM API Error: {e}")

            if result is None:
                logger.error("Retry also produced malformed output. Aborting step.")
                return {"skill": "done", "args": {}}

        return result

    def refine_task(self, raw_task: str) -> str:
        """
        Takes the user's raw instruction and rewrites it into a clear, step-by-step
        sequence of Android UI interaction steps. Called once at the start of every task.
        Returns the refined task string, or the original if refinement fails.
        """
        if not self.client:
            return raw_task

        prompt = (
            f"You are an Android automation planner. The user wants to: \"{raw_task}\"\n\n"
            "Rewrite this as a numbered, step-by-step list of exact UI interactions to perform on an Android phone. "
            "Be very specific — specify which app to open, which button to tap, what text to type, and when to press send/enter. "
            "Do NOT include steps about confirming the task is done. Keep it concise, max 8 steps.\n\n"
            "Example output:\n"
            "1. Open Telegram (package: org.telegram.messenger)\n"
            "2. Tap the element with desc='Search Chats' — this is the search bar at the top of the Chats list (do NOT tap the three-dot menu icon)\n"
            "3. Type 'bujji' into the search bar\n"
            "4. If the result shows a bot/user (e.g., 'Bujji, bot'), tap it\n"
            "5. If a profile page opens with 'Message', 'Mute', 'Call' buttons — tap the 'Message' button\n"
            "6. Tap the message input box labeled 'Message'\n"
            "7. Type 'hi'\n"
            "8. Tap the Send button\n\n"
            "Now generate the steps for the user's task:"
        )

        try:
            messages = [{"role": "user", "content": prompt}]
            refined = self._call_llm(messages)
            logger.info(f"Task refined:\n{refined}")
            return f"{raw_task}\n\nDetailed steps:\n{refined}"
        except Exception as e:
            logger.error(f"refine_task error: {e}")
            return raw_task

    def _call_llm(self, messages: list) -> str:
        """Calls the LLM and returns the raw text response."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.0,
        )
        return response.choices[0].message.content.strip()

    def get_action_from_screenshot(self, task: str, screenshot_path: str, hint: str = None) -> dict:
        """
        When the agent is stuck or uiautomator cannot dump the UI, send a screenshot
        to the vision model and ask it to return the exact pixel coordinates to tap.
        Optional hint provides extra context (e.g. element label to locate).
        Returns {"skill": "tap", "args": {"x": ..., "y": ...}} or {"skill": "done", ...}.
        """
        if not self.client or not os.path.exists(screenshot_path):
            logger.warning("Vision fallback: no client or screenshot missing.")
            return {"skill": "done", "args": {}}

        try:
            with open(screenshot_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")

            hint_line = f"\nHint: {hint}" if hint else ""
            prompt = (
                f"You are controlling an Android phone. The task is: {task}{hint_line}\n"
                "Look at this screenshot. Find the most useful element to tap to make progress on the task "
                "(e.g. a Skip button, search bar, video thumbnail, close button, or a list item).\n"
                "Reply with ONLY two integers separated by a space: the X and Y pixel coordinates to tap.\n"
                "Example: 540 1200"
            )

            response = self.client.chat.completions.create(
                model=self.vision_model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                    ]
                }],
                temperature=0.0,
            )
            raw = response.choices[0].message.content.strip()
            logger.info(f"Vision action output: {raw}")

            # Parse "x y" or "x, y" format
            parts = re.findall(r"\d+", raw)
            if len(parts) >= 2:
                x, y = int(parts[0]), int(parts[1])
                logger.info(f"Vision suggests tapping ({x}, {y})")
                return {"skill": "tap", "args": {"x": x, "y": y}}

        except Exception as e:
            logger.error(f"Vision action error: {e}")

        return {"skill": "done", "args": {}}

    def check_task_done_from_screenshot(self, task: str, screenshot_path: str) -> bool:
        """
        After a vision-based tap (e.g. on a video), uiautomator can't read the
        player UI. This method takes a screenshot and asks the vision model whether
        the task has been successfully completed.
        Returns True if the model says YES.
        """
        if not self.client or not os.path.exists(screenshot_path):
            return False

        try:
            with open(screenshot_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")

            prompt = (
                f"You are verifying whether a task was completed on an Android phone.\n"
                f"Task: {task}\n"
                "Look at this screenshot carefully. Has the task been successfully completed?\n"
                "Examples of 'done': video is playing, app is open, message sent, search results shown.\n"
                "Reply with ONLY 'YES' or 'NO'."
            )

            response = self.client.chat.completions.create(
                model=self.vision_model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                    ]
                }],
                temperature=0.0,
            )
            answer = response.choices[0].message.content.strip().upper()
            logger.info(f"Task completion check: '{answer}' for task: {task}")
            return answer.startswith("YES")

        except Exception as e:
            logger.error(f"Task completion check error: {e}")
            return False


    def analyze_with_vision(self, task: str, screenshot_path: str) -> str:
        """
        Uses a vision model to act as a Visual Analyst and return a screen quadrant.
        """
        if not self.client or not os.path.exists(screenshot_path):
            logger.warning("No LLM client or screenshot not found. Returning empty vision insight.")
            return ""
            
        try:
            with open(screenshot_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
                
            prompt = (
                "You are a visual analyst checking a phone screenshot. "
                f"The user wants to: {task}\n"
                "Look at this screenshot and find the most relevant icon, button, or search field to accomplish this task. "
                "Reply ONLY with its approximate location using EXACTLY the co-ordinates of the button "
            )
            
            response = self.client.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                temperature=0.0
            )
            output = response.choices[0].message.content.strip().lower()
            logger.info(f"Vision Model Output: {output}")
            
                                                                                
            valid_quadrants = ["top-left", "top-right", "bottom-left", "bottom-right", "center", "top-center", "bottom-center", "top", "bottom", "left", "right"]
            for quad in valid_quadrants:
                if quad in output:
                    return quad
                    
            return output                                                             
        except Exception as e:
            logger.error(f"Vision LLM API Error: {e}")
            return ""

    def _parse_llm_output(self, output: str):
        """
        Parses output like:
        SKILL: tap
        ARGS: x=650 y=140
        Returns a dict on success, or None if the output is malformed.
        """
        logger.debug(f"LLM Raw Output:\n{output}")
        if not output or "SKILL:" not in output:
            logger.warning("LLM returned empty or malformed output (no SKILL: found).")
            return None

        result: dict = {"skill": "done", "args": {}}
        
        skill_match = re.search(r"SKILL:\s*(\w+)", output)
        if skill_match:
            result["skill"] = skill_match.group(1).lower()
            
        args_match = re.search(r"ARGS:\s*(.*)", output, re.DOTALL)
        if args_match:
            args_str = args_match.group(1).strip()
                                                                                    
                                                                                 
            args_pairs = re.findall(r"(\w+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|(\S+))", args_str)
            
            for match in args_pairs:
                key = match[0]
                                                              
                val = match[1] or match[2] or match[3]
                
                                        
                if val.isdigit() or (val.startswith('-') and val[1:].isdigit()):                              
                    result["args"][key] = int(val)
                elif val.lower() == "true":
                    result["args"][key] = True
                elif val.lower() == "false":
                    result["args"][key] = False
                else:
                    result["args"][key] = val
                    
        return result
                
    def _filter_ui_by_quadrant(self, ui_elements_str: str, quadrant: str) -> str:
        """
        Filters the raw UI elements string down to only elements that reside in the specified 
        quadrant (e.g. 'top-right', 'bottom-center').
        Standard phone dimensions are typically 1080x2400.
        """
                                                                              
                                                                                             
        MAX_X = 1080
        MAX_Y = 2400
        MID_X = MAX_X // 2
        MID_Y = MAX_Y // 2
        
        filtered_lines = []
        for line in ui_elements_str.splitlines():
                                  
            match = re.search(r"center=\((\d+),(\d+)\)", line)
            if not match:
                filtered_lines.append(line)                                         
                continue
                
            x, y = int(match.group(1)), int(match.group(2))
            
                                                       
            in_quadrant = False
            quadrant_words = quadrant.split("-") if "-" in quadrant else [quadrant]
            
            if "top-left" == quadrant and x <= MID_X and y <= MID_Y: in_quadrant = True
            elif "top-right" == quadrant and x > MID_X and y <= MID_Y: in_quadrant = True
            elif "bottom-left" == quadrant and x <= MID_X and y > MID_Y: in_quadrant = True
            elif "bottom-right" == quadrant and x > MID_X and y > MID_Y: in_quadrant = True
            elif "top-center" == quadrant and y <= MID_Y: in_quadrant = True                                        
            elif "bottom-center" == quadrant and y > MID_Y: in_quadrant = True                                     
            elif "center" == quadrant and (MID_X - 250) < x < (MID_X + 250) and (MID_Y - 500) < y < (MID_Y + 500): in_quadrant = True
            elif "top" == quadrant and y <= MID_Y: in_quadrant = True
            elif "bottom" == quadrant and y > MID_Y: in_quadrant = True
            elif "left" == quadrant and x <= MID_X: in_quadrant = True
            elif "right" == quadrant and x > MID_X: in_quadrant = True
            
                                              
            if in_quadrant:
                filtered_lines.append(line)
        
                                                                                                    
        if not filtered_lines:
            return ui_elements_str
            
        return "\n".join(filtered_lines)
