import logging
import re
import os
import shlex

logger = logging.getLogger(__name__)

# Fallback mechanism if OpenAI is not installed
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
        
        if HAS_OPENAI and self.api_key:
             self.client = openai.OpenAI(
                 api_key=self.api_key,
                 base_url=self.base_url if self.base_url else None
             )
        else:
             self.client = None

    def plan_next_action(self, task: str, ui_elements_str: str, history: list) -> dict:
        """
        Queries the LLM to decide the next action.
        Returns a dictionary like {"skill": "tap", "args": {"x": 100, "y": 200}}
        """
        system_prompt = """
You are an AI Android automation agent.
Your goal is to accomplish the user's task using the following available skills:

- tap(x, y) OR tap(id=<number>) -> Prefer 'id' if available in UI Elements
- type_text(text)
- open_app(package_name)
- press_key(key) -> key can be HOME, BACK, ENTER, SEARCH
- scroll(x1, y1, x2, y2)
- done() -> call this ONLY when the task is fully complete

Guidance:
- Use IDs for accuracy: Always prefer `tap(id=N)` or `type_text(id=N, text="...")` over coordinate-based actions if an ID is available in the UI list.
- Provide all arguments: When using a skill, always provide all required arguments in the `ARGS:` section (e.g., `ARGS: package_name="com.android.settings"` for `open_app`).
- Navigate towards the goal: If you don't see the target app or element, try to find a search bar, open the app drawer, or use `open_app` with its name.
- Stuck?: If you repeat an action twice and the UI doesn't change, try `press_key(key=BACK)` or a different approach.
- Done: Only use the `done()` skill when the USER's task is fully accomplished.
- Search Logic: If you're not sure of the exact package name, use the common name (e.g., `settings`, `chrome`). 
- Common Packages: Clock (`com.android.BBKClock`, `com.android.deskclock`), Settings (`com.android.settings`), YouTube (`com.google.android.youtube`).

Format:
SKILL: <skill_name>
ARGS: <key_1>=<val_1> <key_2>=<val_2>

Example:
SKILL: tap
ARGS: id=12
"""
        
        history_str = "\n".join([f"Executed: {h}" for h in history[-5:]]) # Keep last 5 actions

        user_prompt = f"""
Task: {task}

UI Elements:
{ui_elements_str}

Action History:
{history_str}

What is your next action?
"""
        
        if self.client:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.0
                )
                output = response.choices[0].message.content.strip()
                return self._parse_llm_output(output)
            except Exception as e:
                logger.error(f"LLM API Error: {e}")
                return {"skill": "done", "args": {}}
        else:
            logger.warning("No LLM client configured. Returning mock 'done' action.")
            print("\n--- MOCK LLM PLANNER ---")
            print("To use the real LLM Planner, 'pip install openai' and export OPENAI_API_KEY.")
            print(f"Task: {task}")
            print(f"UI Elements found: {len(ui_elements_str.splitlines())}")
            print("------------------------\n")
            return {"skill": "done", "args": {}}

    def _parse_llm_output(self, output: str) -> dict:
        """
        Parses output like:
        SKILL: tap
        ARGS: x=650 y=140
        """
        logger.debug(f"LLM Raw Output:\n{output}")
        result = {"skill": "done", "args": {}}
        
        skill_match = re.search(r"SKILL:\s*(\w+)", output)
        if skill_match:
            result["skill"] = skill_match.group(1).lower()
            
        args_match = re.search(r"ARGS:\s*(.*)", output, re.DOTALL)
        if args_match:
            args_str = args_match.group(1).strip()
            # Regex to match key="value", key='value', or key=value (without spaces)
            # 1: key, 2: double-quoted val, 3: single-quoted val, 4: unquoted val
            args_pairs = re.findall(r"(\w+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|(\S+))", args_str)
            
            for match in args_pairs:
                key = match[0]
                # Take the first non-empty group among 2, 3, 4
                val = match[1] or match[2] or match[3]
                
                # Handle primitive types
                if val.isdigit() or (val.startswith('-') and val[1:].isdigit()): # Added negative number check
                    result["args"][key] = int(val)
                elif val.lower() == "true":
                    result["args"][key] = True
                elif val.lower() == "false":
                    result["args"][key] = False
                else:
                    result["args"][key] = val
                
        return result
