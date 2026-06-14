import asyncio
import logging
import base64
import os
import time
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP
from config.settings import ADB_PATH
from device.adb_controller import AdbController
from executor.skill_executor import SkillExecutor
from ui.dump_ui import dump_ui_hierarchy
from ui.ui_parser import parse_ui_xml, format_ui_elements_for_llm

log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "logs", "mcp_server.log")
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler()]
)
logger = logging.getLogger("mcp_server")

# Initialize MCP Server
mcp = FastMCP("MobileAgent")

# Global state
adb = AdbController(adb_path=ADB_PATH)
executor = SkillExecutor(adb)

@mcp.tool()
def get_adb_path() -> str:
    """
    Returns the ADB path being used by the server.
    """
    return adb.adb_path

@mcp.tool()
def dump_ui() -> str:
    """
    Dumps the current Android screen UI hierarchy and returns a simplified list of clickable elements.
    Always use this first to "see" the screen before tapping.
    The returned list contains elements in format: [id] desc='...' text='...' center=(x,y).
    """
    try:
        xml_path = dump_ui_hierarchy(adb)
        if not xml_path:
            return "ERROR: Failed to dump UI."
        elements = parse_ui_xml(xml_path)
        ui_str, final_elements = format_ui_elements_for_llm(elements)
        executor.set_last_elements(final_elements)
        return ui_str if ui_str.strip() else "Screen is empty or no clickable elements found."
    except Exception as e:
        logger.error(f"Error in dump_ui: {e}")
        return f"ERROR: {e}"

@mcp.tool()
def tap(id: Optional[int] = None, x: Optional[int] = None, y: Optional[int] = None, text: Optional[str] = None) -> str:
    """
    Taps on the screen. Provide ONE of: 
    - `id` (the numeric ID from dump_ui)
    - `x` and `y` coordinates
    - `text` (exact text or content description to tap).
    """
    args = {}
    if id is not None: args["id"] = id
    if x is not None: args["x"] = x
    if y is not None: args["y"] = y
    if text is not None: args["text"] = text
    return str(executor.execute_skill("tap", args))

@mcp.tool()
def type_text(text: str) -> str:
    """
    Types text into the currently focused input field. Ensure you have tapped a text field first.
    """
    return str(executor.execute_skill("type_text", {"text": text}))

@mcp.tool()
def open_app(package_name: str, query: Optional[str] = None) -> str:
    """
    Opens an app by name or package (e.g. 'youtube', 'com.whatsapp').
    If 'query' is provided, it attempts to launch directly into the app's search results for that query.
    """
    args = {"package_name": package_name}
    if query:
        args["query"] = query
    return str(executor.execute_skill("open_app", args))

@mcp.tool()
def press_key(key: str) -> str:
    """
    Presses an Android system key. Valid keys: 'HOME', 'BACK', 'ENTER', 'RECENT', 'POWER', 'VOLUME_UP', 'VOLUME_DOWN'.
    """
    return str(executor.execute_skill("press_key", {"key": key}))

@mcp.tool()
def scroll(direction: str) -> str:
    """
    Scrolls the screen. Valid directions: 'up', 'down', 'left', 'right'.
    Note: 'down' means scrolling content downwards (swiping up).
    """
    return str(executor.execute_skill("scroll", {"direction": direction}))

@mcp.tool()
def save_memory(key: str, value: str) -> str:
    """
    Saves text data to persistent memory.
    """
    return str(executor.execute_skill("save_memory", {"key": key, "value": value}))

@mcp.tool()
def extract_text() -> str:
    """
    Extracts all text visible on the current screen.
    """
    return str(executor.execute_skill("extract_text", {}))

@mcp.tool()
def set_wifi(state: str) -> str:
    """
    Turns WiFi 'on' or 'off'.
    """
    return str(executor.execute_skill("set_wifi", {"state": state}))

@mcp.tool()
def set_bluetooth(state: str) -> str:
    """
    Turns Bluetooth 'on' or 'off'.
    """
    return str(executor.execute_skill("set_bluetooth", {"state": state}))

@mcp.tool()
def open_url(url: str) -> str:
    """
    Opens a URL directly in the device's default browser.
    """
    return str(executor.execute_skill("open_url", {"url": url}))

@mcp.tool()
def delete_memory(key: str) -> str:
    """
    Deletes a previously saved value from memory.
    """
    return str(executor.execute_skill("delete_memory", {"key": key}))

@mcp.tool()
def set_airplane_mode(state: str) -> str:
    """
    Turns Airplane Mode 'on' or 'off'.
    """
    return str(executor.execute_skill("set_airplane_mode", {"state": state}))

@mcp.tool()
def set_brightness(level: int) -> str:
    """
    Sets the screen brightness (0-255).
    """
    return str(executor.execute_skill("set_brightness", {"level": level}))

@mcp.tool()
def set_flashlight(state: str) -> str:
    """
    Turns the flashlight 'on' or 'off'.
    """
    return str(executor.execute_skill("set_flashlight", {"state": state}))

@mcp.tool()
def set_mobile_data(state: str) -> str:
    """
    Turns Mobile Data 'on' or 'off'.
    """
    return str(executor.execute_skill("set_mobile_data", {"state": state}))

@mcp.tool()
def set_volume(level: int) -> str:
    """
    Sets the media volume (0-15).
    """
    return str(executor.execute_skill("set_volume", {"level": level}))

@mcp.tool()
def take_screenshot() -> list:
    """
    Takes a screenshot of the current Android screen and returns it as an image
    so you can visually analyze what is on the phone screen.
    Use this when dump_ui fails, when dealing with games/videos, or when you need
    to visually verify the screen state.
    """
    try:
        from config import settings
        screenshot_path = os.path.join(
            settings.SCREENSHOTS_DIR,
            f"mcp_screenshot_{int(time.time())}.png"
        )
        success = adb.take_screenshot(screenshot_path)
        if not success or not os.path.exists(screenshot_path):
            return [{"type": "text", "text": "ERROR: Failed to take screenshot."}]

        with open(screenshot_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")

        return [
            {"type": "text", "text": "Screenshot taken. Analyze the image to understand the current phone screen state."},
            {"type": "image", "data": b64, "mimeType": "image/png"}
        ]
    except Exception as e:
        logger.error(f"take_screenshot error: {e}")
        return [{"type": "text", "text": f"ERROR: {e}"}]

# ── Task Tracker ──────────────────────────────────────────────────────────────
_TASK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "task_progress.json")

def _load_task() -> dict:
    if os.path.exists(_TASK_FILE):
        try:
            with open(_TASK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"task": "", "steps": []}

def _save_task(data: dict):
    os.makedirs(os.path.dirname(_TASK_FILE), exist_ok=True)
    with open(_TASK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

@mcp.tool()
def start_task(task_description: str) -> str:
    """
    Call this FIRST before starting any multi-step task.
    Records the task description and clears previous step history.
    This allows you to resume progress if context gets compressed.
    Example: start_task("Open Gmail and find emails from Internshala")
    """
    data = {"task": task_description, "steps": [], "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    _save_task(data)
    logger.info(f"Task started: {task_description}")
    return f"Task started: '{task_description}'. Use track_step() after each completed step."

@mcp.tool()
def track_step(step_name: str, status: str, result: str = "") -> str:
    """
    Call this after EVERY completed action to record progress.
    - step_name: short description of what was done (e.g. "Opened Gmail", "Tapped search bar")
    - status: "done", "failed", or "skipped"
    - result: optional — any useful output or finding from this step
    This ensures progress is saved even if context gets compressed on long tasks.
    """
    data = _load_task()
    data["steps"].append({
        "step": step_name,
        "status": status,
        "result": result,
        "timestamp": time.strftime("%H:%M:%S")
    })
    _save_task(data)
    done = sum(1 for s in data["steps"] if s["status"] == "done")
    logger.info(f"Step tracked: {step_name} [{status}]")
    return f"Step recorded ({done} steps done so far). Continue with the next step."

@mcp.tool()
def get_task_progress() -> str:
    """
    Returns the full progress of the current task including all completed steps.
    Call this if you lose context or need to remember what has already been done.
    Also useful to check before starting to avoid repeating completed steps.
    """
    data = _load_task()
    if not data.get("task"):
        return "No task in progress. Call start_task() to begin."
    lines = [f"Task: {data['task']}", f"Started: {data.get('started_at', 'unknown')}", ""]
    if not data["steps"]:
        lines.append("No steps recorded yet.")
    else:
        for i, s in enumerate(data["steps"], 1):
            icon = "✅" if s["status"] == "done" else ("❌" if s["status"] == "failed" else "⏭️")
            line = f"{icon} Step {i}: {s['step']} [{s['timestamp']}]"
            if s.get("result"):
                line += f"\n   → {s['result']}"
            lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":
    with open("mcp_debug.log", "a") as f:
        f.write(f"Starting MCP Server with ADB_PATH: {ADB_PATH}\n")
    logger.info("Starting Mobile Agent MCP Server via stdio...")
    mcp.run()
