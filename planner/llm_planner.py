import logging
import re
import os
import hashlib
import json
import shlex
import base64
import traceback
import httpx

logger = logging.getLogger(__name__)

# ── LLM Response Cache ───────────────────────────────────────────────────────
# Avoids redundant API calls when the same input is seen multiple times.
_llm_cache: dict = {}   # hash -> response string
MAX_CACHE_SIZE = 128


def _cache_key(*parts: str) -> str:
    """SHA-256 hex digest of the concatenated inputs."""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _cache_get(key: str):
    return _llm_cache.get(key)


def _cache_set(key: str, value: str):
    if len(_llm_cache) >= MAX_CACHE_SIZE:
        # Evict the oldest entry (insertion-order FIFO for Python 3.7+)
        oldest = next(iter(_llm_cache))
        del _llm_cache[oldest]
    _llm_cache[key] = value


# ── Task Progress Tracker ────────────────────────────────────────────────────
class TaskProgressTracker:
    """
    Tracks which high-level steps of the refined task have been completed,
    so the LLM always knows what's done and what remains.
    """

    def __init__(self, refined_task: str):
        # Extract numbered lines as steps ("1. Open app", "2. Tap search", ...)
        self._steps = re.findall(r"^\s*\d+\.\s+(.+)", refined_task, re.MULTILINE)
        self._done: list[bool] = [False] * len(self._steps)
        self._current = 0

    @property
    def has_steps(self) -> bool:
        return bool(self._steps)

    def mark_done(self, step_index: int):
        if 0 <= step_index < len(self._done):
            self._done[step_index] = True
            self._current = step_index + 1

    def infer_progress_from_history(self, history: list):
        """
        Heuristically advances the current step pointer based on
        the number of SUCCESS outcomes in the history so far.
        """
        success_count = sum(
            1 for h in history
            if isinstance(h, dict) and h.get("outcome") == "SUCCESS"
        )
        # Advance one step per two successes (conservative)
        new_current = min(success_count // 2, len(self._steps))
        if new_current > self._current:
            for i in range(self._current, new_current):
                self._done[i] = True
            self._current = new_current

    def progress_summary(self) -> str:
        """Returns a human-readable summary for injection into the LLM prompt."""
        if not self._steps:
            return ""
        lines = ["Task Progress:"]
        for i, step in enumerate(self._steps):
            if self._done[i]:
                lines.append(f"  ✓ Step {i+1} (done): {step}")
            elif i == self._current:
                lines.append(f"  ► Step {i+1} (CURRENT): {step}")
            else:
                lines.append(f"  □ Step {i+1} (pending): {step}")
        return "\n".join(lines)


# ── Structured Logging Adapter ───────────────────────────────────────────────
class TaskLogger(logging.LoggerAdapter):
    """Injects task_id into every log record for correlation."""

    def process(self, msg, kwargs):
        task_id = self.extra.get("task_id", "")
        return f"[{task_id}] {msg}" if task_id else msg, kwargs

                                                
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
        # Progress tracker is created per-task by the AgentLoop
        self.progress_tracker: TaskProgressTracker | None = None
        self._task_id: str = ""
        self._log = TaskLogger(logger, {})
        
        self.system_prompt = """You are an Android phone automation agent. You output exactly ONE action per turn.

Available Skills:
  tap            ARGS: id=<n>   OR   x=<n> y=<n>
  type_text      ARGS: text=<string>
  open_app       ARGS: package_name=<app_name_or_pkg>   (use app name like 'Spotify' or package like 'com.spotify.music')
  open_url       ARGS: url=<full_url_or_deep_link>      (use for any URL, YouTube link, WhatsApp link, Maps link, etc.)
  press_key      ARGS: key=HOME|BACK|ENTER|VOLUME_UP|VOLUME_DOWN
  scroll         ARGS: x1=500 y1=1500 x2=500 y2=500
  save_memory    ARGS: key=<name> value=<x,y or description>
  delete_memory  ARGS: key=<name>
  set_wifi       ARGS: state=on|off
  set_bluetooth  ARGS: state=on|off
  set_brightness ARGS: level=<0-255 or 50%> mode=manual|auto
  set_volume     ARGS: level=<0-15> stream=media|ring|alarm|notification|system
  set_airplane_mode ARGS: state=on|off
  set_flashlight ARGS: state=on|off
  set_mobile_data ARGS: state=on|off
  extract_text   ARGS: save_as=<memory_key>
  summarize_text ARGS: save_as=<memory_key>
  take_screenshot ARGS: filename=<optional_name>
  chat_reply     ARGS: message=<text>
  done           ARGS: (none)

CRITICAL RULES:
  1. open_app ONLY needs package_name. You can use the plain app name (e.g. 'Spotify', 'YouTube', 'Google Maps') OR the full package name. Never add id/x/y/text to it.
  2. Prefer id=<n> (element index) over raw x/y coordinates when available.
  3. If your last action was tapping a search bar (SUCCESS), you MUST use type_text next. Do NOT tap the search bar again.
  4. After typing a search term, tap the RESULT below the search bar, NOT the search bar itself.
  5. If an element is NOT visible, use scroll to find it. Do NOT guess coordinates.
  6. ONLY use skills from the list above. Do NOT invent skills like 'search', 'find', 'swipe', 'input'.
  7. To search inside an app: (a) tap search icon/bar, (b) type_text, (c) press_key ENTER. Do NOT press BACK after typing — it cancels the search.
  8. For system tasks (WiFi, Bluetooth, etc.) use the dedicated skill directly.
  9. After typing text, press_key ENTER to submit if no Send button is visible.
  10. If the task contains a full URL (starting with http/https) or a known deep link, use open_url IMMEDIATELY as the first action. Do NOT navigate manually to websites.
  11. If Task Progress shows ALL steps marked as done (✓), output SKILL: done immediately. Do NOT plan any more actions.
  12. You can use 'chat_reply' to tell the user something helpful mid-task, or to summarize results. Example: ARGS: message=I found 3 emails from Internshala.

OUTPUT FORMAT — you MUST reply with EXACTLY these two lines and nothing else:
SKILL: <skill_name>
ARGS: <key=value key=value ...>

Examples:
SKILL: tap
ARGS: id=33

SKILL: open_app
ARGS: package_name=Swiggy

SKILL: open_app
ARGS: package_name=com.google.android.youtube

SKILL: type_text
ARGS: text=meghana biriyani

SKILL: press_key
ARGS: key=ENTER

SKILL: done
ARGS: (none)

SKILL: open_url
ARGS: url=https://www.youtube.com/watch?v=dQw4w9WgXcQ

SKILL: open_url
ARGS: url=https://wa.me/919876543210"""
        
        if HAS_OPENAI and self.api_key:
             self.client = openai.OpenAI(
                 api_key=self.api_key,
                 base_url=self.base_url if self.base_url else None,
                 timeout=httpx.Timeout(30.0, connect=10.0)
             )
        else:
             self.client = None

    def set_task(self, task_id: str, refined_task: str):
        """Initialise per-task state: correlation ID and progress tracker."""
        self._task_id = task_id
        self._log = TaskLogger(logger, {"task_id": task_id})
        self.progress_tracker = TaskProgressTracker(refined_task)
        self._log.info(f"Progress tracker initialised with {len(self.progress_tracker._steps)} steps.")

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

        # --- Context-Aware Progress Injection ---
        progress_str = ""
        tracker = getattr(self, "progress_tracker", None)
        if tracker and tracker.has_steps:
            tracker.infer_progress_from_history(history)
            progress_str = f"\n{tracker.progress_summary()}\n"

        # Fix 1: Always pass the FULL UI to the LLM — vision is a soft hint, not a filter
        hint_line = ""
        if vision_insight:
            hint_line = f"\nVision hint: the relevant element is likely in the {vision_insight} area.\n"

        user_prompt = (
            f"Task: {task}\n"
            f"{progress_str}"
            f"{hint_line}"
            f"{memory_str}"
            f"\nAction History:\n{history_str}\n"
            f"\nIMPORTANT: Reply with ONLY two lines: SKILL: <name> and ARGS: <key=val>\n"
            f"\nUI Elements:\n{ui_elements_str}\n"
            f"\nYour action (SKILL: and ARGS: only):"
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

        # If output was malformed, retry once with the failed output included for correction
        if result is None:
            logger.warning("Malformed LLM output. Retrying with format correction prompt.")
            retry_messages = [
                {"role": "system", "content": "You are an Android automation agent. Output ONLY two lines:\nSKILL: <name>\nARGS: <key=val ...>\n\nValid skills: tap, type_text, open_app, press_key, scroll, done\ntap needs: id=<n> OR x=<n> y=<n>\nopen_app needs: package_name=<pkg>"},
                {"role": "user", "content": (
                    f"Task: {task}\n\n"
                    f"Your previous response was:\n{output}\n\n"
                    f"This was malformed. Rewrite it as EXACTLY two lines:\n"
                    f"SKILL: <skill_name>\nARGS: <key=value ...>\n\n"
                    f"Reply now:"
                )},
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
        Uses a cache to avoid redundant LLM calls for identical inputs.
        """
        if not self.client:
            return raw_task

        # --- Cache check ---
        cache_key = _cache_key("refine", raw_task, self.model)
        cached = _cache_get(cache_key)
        if cached:
            self._log.info("refine_task: cache HIT — skipping LLM call.")
            return cached

        prompt = (
            f"You are an Android automation planner. The user wants to: \"{raw_task}\"\n\n"
            "Rewrite this as a numbered, step-by-step list of exact UI interactions to perform on an Android phone. "
            "Be very specific — specify which app to open (include package name), which button to tap, what text to type, and when to press enter.\n\n"
            "IMPORTANT RULES:\n"
            "- Do NOT include login/signup steps unless the user explicitly asked to log in\n"
            "- Do NOT include a 'Close app' step at the end\n"
            "- Do NOT assume the user needs to authenticate\n"
            "- Keep it concise, max 6 steps\n"
            "- Only include observable UI actions (tap, type, scroll)\n\n"
            "Example output:\n"
            "1. Open Swiggy (package: com.swiggy.android)\n"
            "2. Tap the search bar at the top\n"
            "3. Type 'biryani' into the search bar\n"
            "4. Press Enter to search\n"
            "5. Tap on the first result\n"
            "6. Tap 'Add' button next to the item\n\n"
            "Now generate the steps for the user's task:"
        )

        try:
            messages = [{"role": "user", "content": prompt}]
            refined = self._call_llm(messages)
            self._log.info(f"Task refined:\n{refined}")
            result = f"{raw_task}\n\nDetailed steps:\n{refined}"
            _cache_set(cache_key, result)
            return result
        except Exception as e:
            self._log.error(f"refine_task error: {e}")
            return raw_task

    def _call_llm(self, messages: list) -> str:
        """Calls the LLM and returns the raw text response."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
            )
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            logger.error(f"LLM API call timed out or connection failed: {e}")
            raise
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
                f"You are an expert Android AI agent. The current task is: '{task}'{hint_line}\n"
                "Analyze this screenshot carefully. Identify the SINGLE most crucial element you must tap to make progress "
                "(e.g., a search bar, a specific product in a list, an 'Add to Cart' or 'Buy' button, a profile/chat, or a 'Skip Ad' button).\n"
                "If the element is visible, provide the EXACT X and Y pixel coordinates for the center of that element.\n"
                "If the element is NOT visible and you realistically need to scroll down to find it, reply with exactly the word SCROLL.\n"
                "CRITICAL: Reply with EXCLUSIVELY the X and Y integers separated by a single space, OR the word SCROLL. Do NOT include words, explanations, or punctuation."
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
            content = response.choices[0].message.content
            raw = content.strip() if content else ""
            logger.info(f"Vision action output: {raw}")

            if raw.upper() == "SCROLL":
                logger.info("Vision suggests SCROLLING")
                return {"skill": "scroll", "args": {"x1": 500, "y1": 1500, "x2": 500, "y2": 500}}

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
        Asks the vision model whether the task has been completed.
        Returns True if the model confirms YES.
        Handles verbose models that ignore YES/NO-only instructions.
        Uses a file-hash-based cache to avoid duplicate API calls for the same screenshot.
        """
        if not self.client or not os.path.exists(screenshot_path):
            return False

        try:
            with open(screenshot_path, "rb") as f:
                raw_bytes = f.read()
                b64 = base64.b64encode(raw_bytes).decode("utf-8")

            # Cache keyed on task + screenshot content hash
            img_hash = hashlib.md5(raw_bytes).hexdigest()  # fast, non-cryptographic
            cache_key = _cache_key("completion", task, img_hash)
            cached = _cache_get(cache_key)
            if cached is not None:
                self._log.info(f"check_task_done: cache HIT ({cached}) for screenshot {os.path.basename(screenshot_path)}")
                return cached == "YES"

            prompt = (
                f"Task: {task}\n"
                "Has this task been successfully completed based on the screenshot?\n"
                "Reply with ONLY the single word YES or NO. Nothing else."
            )

            response = self.client.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {"role": "system", "content": "You are a task verifier. You answer ONLY with YES or NO."},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                        ]
                    }
                ],
                temperature=0.0,
                max_tokens=10,
            )
            content = response.choices[0].message.content
            raw = content.strip().upper() if content else ""
            self._log.info(f"Task completion check raw: '{raw[:80]}' for task: {task}")

            # Robust YES/NO scan — handles verbose models that ignore format instructions
            if "YES" in raw:
                _cache_set(cache_key, "YES")
                return True
            if "NO" in raw:
                _cache_set(cache_key, "NO")
                return False
            # If truly ambiguous, default to False (keep going)
            self._log.warning("Vision model gave ambiguous completion answer. Defaulting to False.")
            return False

        except Exception as e:
            err = str(e)
            if "must be a string" in err or "not a multimodal" in err:
                self._log.warning(f"Vision model '{self.vision_model}' doesn't support images. Skipping completion check.")
            else:
                self._log.error(f"Task completion check error: {e}")
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
        Multi-strategy parser for LLM output.
        Tries multiple formats to extract skill name and arguments.
        Returns a dict on success, or None if all strategies fail.
        """
        if not output:
            logger.warning("LLM returned empty output.")
            return None

        # Always log raw output at INFO level for debugging
        logger.info(f"LLM Raw Output:\n{output}")

        # Clean up markdown formatting artifacts
        cleaned = output.replace("**", "").replace("```", "").strip()

        # ── Strategy 1: Standard format (case-insensitive) ──
        # Matches: SKILL: tap / skill: tap / Skill: tap
        skill_match = re.search(r"(?i)skill:\s*(\w+)", cleaned)
        if skill_match:
            skill = skill_match.group(1).lower()
            result = {"skill": skill, "args": {}}

            args_match = re.search(r"(?i)args:\s*(.*)", cleaned, re.DOTALL)
            if args_match:
                args_str = args_match.group(1).strip()
                # Stop at newlines that don't look like args continuation
                args_str = args_str.split("\n")[0].strip()
                result["args"] = self._parse_args_string(skill, args_str)

            logger.info(f"Parsed (strategy 1 - standard): {result}")
            return result

        # ── Strategy 2: Function-call style ──
        # Matches: tap(x=100, y=200) or open_app(package_name=com.swiggy.android)
        func_match = re.search(r"(\w+)\s*\(\s*(.*?)\s*\)", cleaned)
        if func_match:
            skill = func_match.group(1).lower()
            valid_skills = {"tap", "type_text", "open_app", "open_url", "press_key", "scroll",
                          "save_memory", "delete_memory", "set_wifi", "set_bluetooth",
                          "set_brightness", "set_volume", "set_airplane_mode",
                          "set_flashlight", "set_mobile_data", "extract_text",
                          "summarize_text", "take_screenshot", "done"}
            if skill in valid_skills:
                args_str = func_match.group(2)
                result = {"skill": skill, "args": self._parse_args_string(skill, args_str)}
                logger.info(f"Parsed (strategy 2 - function call): {result}")
                return result

        # ── Strategy 3: JSON format ──
        # Matches: {"skill": "tap", "args": {"x": 100, "y": 200}}
        import json
        json_match = re.search(r'\{[^{}]*"skill"[^{}]*\}', cleaned)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                if "skill" in parsed:
                    result = {"skill": parsed["skill"].lower(), "args": parsed.get("args", {})}
                    logger.info(f"Parsed (strategy 3 - JSON): {result}")
                    return result
            except json.JSONDecodeError:
                pass

        # ── Strategy 4: Natural language extraction ──
        # Matches: "tap on element [33]", "I would tap at (416, 2058)"
        cleaned_lower = cleaned.lower()

        # Check for "open_app" or "open app" with package name
        pkg_match = re.search(r"(?:open[_ ]app|launch|open)\s+.*?(com\.\S+|org\.\S+)", cleaned_lower)
        if pkg_match:
            result = {"skill": "open_app", "args": {"package_name": pkg_match.group(1).rstrip(".)\"'")}}
            logger.info(f"Parsed (strategy 4 - natural language open_app): {result}")
            return result

        # Check for "tap" with coordinates
        tap_coord_match = re.search(r"tap\s+.*?(?:at\s+)?[\(]?\s*(\d{2,4})\s*[,\s]\s*(\d{2,4})\s*[\)]?", cleaned_lower)
        if tap_coord_match:
            result = {"skill": "tap", "args": {"x": int(tap_coord_match.group(1)), "y": int(tap_coord_match.group(2))}}
            logger.info(f"Parsed (strategy 4 - natural language tap coords): {result}")
            return result

        # Check for "tap" with element index
        tap_id_match = re.search(r"tap\s+.*?(?:element|id|index)?\s*\[?(\d{1,3})\]?", cleaned_lower)
        if tap_id_match:
            result = {"skill": "tap", "args": {"id": int(tap_id_match.group(1))}}
            logger.info(f"Parsed (strategy 4 - natural language tap id): {result}")
            return result

        # Check for "type" or "type_text" with text
        type_match = re.search(r"(?:type_text|type|enter|input)\s+['\"]?(.+?)['\"]?\s*$", cleaned_lower, re.MULTILINE)
        if type_match:
            result = {"skill": "type_text", "args": {"text": type_match.group(1).strip("'\" ")}}
            logger.info(f"Parsed (strategy 4 - natural language type_text): {result}")
            return result

        # Check for "press" key
        key_match = re.search(r"(?:press[_ ]key|press)\s+(\w+)", cleaned_lower)
        if key_match:
            key = key_match.group(1).upper()
            if key in ("HOME", "BACK", "ENTER", "SEARCH", "VOLUME_UP", "VOLUME_DOWN", "TAB"):
                result = {"skill": "press_key", "args": {"key": key}}
                logger.info(f"Parsed (strategy 4 - natural language press_key): {result}")
                return result

        # Check for "scroll"
        if re.search(r"\bscroll\b", cleaned_lower):
            result = {"skill": "scroll", "args": {"x1": 500, "y1": 1500, "x2": 500, "y2": 500}}
            logger.info(f"Parsed (strategy 4 - natural language scroll): {result}")
            return result

        # Check for "done"
        if re.search(r"\bdone\b|\btask.{0,10}complet", cleaned_lower):
            result = {"skill": "done", "args": {}}
            logger.info(f"Parsed (strategy 4 - natural language done): {result}")
            return result

        logger.warning(f"All parsing strategies failed for output: {cleaned[:200]}")
        return None

    def _parse_args_string(self, skill: str, args_str: str) -> dict:
        """Parse a key=value argument string into a dict."""
        args = {}
        if not args_str or args_str.strip() == "(none)":
            return args

        # Special-case: if skill is type_text, grab the FULL text value
        if skill == "type_text":
            # Try quoted first: text="..." or text='...'
            text_quoted = re.search(r'text\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', args_str)
            if text_quoted:
                args["text"] = text_quoted.group(1) or text_quoted.group(2)
            else:
                # Unquoted: capture everything after text= to end of line
                text_unquoted = re.search(r'text\s*=\s*(.+?)(?:\n|$)', args_str)
                if text_unquoted:
                    args["text"] = text_unquoted.group(1).strip()
            return args

        # Generic parser for all other skills
        args_pairs = re.findall(r"(\w+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|(\S+))", args_str)

        for match in args_pairs:
            key = match[0]
            val = match[1] or match[2] or match[3]

            if val.isdigit() or (val.startswith('-') and val[1:].isdigit()):
                args[key] = int(val)
            elif val.lower() == "true":
                args[key] = True
            elif val.lower() == "false":
                args[key] = False
            else:
                args[key] = val

        return args
                
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
