import os

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
LOGS_DIR = os.path.join(STORAGE_DIR, "logs")
SCREENSHOTS_DIR = os.path.join(STORAGE_DIR, "screenshots")

# Create storage directories if they don't exist
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

# ADB Settings
local_app_data = os.environ.get("LOCALAPPDATA", "")
default_adb = os.path.join(local_app_data, "Android", "Sdk", "platform-tools", "adb.exe") if local_app_data else "adb"
ADB_PATH = default_adb if os.path.exists(default_adb) else "adb"

# LLM Settings
OPENAI_API_KEY = "dummy_key"
LLM_BASE_URL = "http://localhost:11434/v1"
LLM_MODEL = "llama3.2:latest"
