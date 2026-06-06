import os
import dotenv

# Load local environment variables from .env file if present
dotenv.load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
LOGS_DIR = os.path.join(STORAGE_DIR, "logs")
SCREENSHOTS_DIR = os.path.join(STORAGE_DIR, "screenshots")

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

local_app_data = os.environ.get("LOCALAPPDATA", "")
default_adb = os.path.join(local_app_data, "Android", "Sdk", "platform-tools", "adb.exe") if local_app_data else "adb"
ADB_PATH = default_adb if os.path.exists(default_adb) else "adb"

# ── LLM Settings ────────────────────────────────────────────────────────────
# Minimum recommended model size for reliable output: 7B+ parameters
# Models under 7B (e.g. qwen2.5:3b) often fail to follow the SKILL:/ARGS: format.

# ── Option A: Groq Cloud API (RATE LIMITED) ──────────────────────────────
#OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY")
#LLM_BASE_URL     = "https://api.groq.com/openai/v1"
#LLM_MODEL        = "llama-3.3-70b-versatile"
#LLM_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
#ENABLE_VISION_FALLBACK = True

# ── Option B: Local Ollama (Active) ─────────────────────────────────────────
OPENAI_API_KEY   = "dummy_key"
LLM_BASE_URL     = "http://localhost:11434/v1"
LLM_MODEL        = "qwen2.5:3b"
LLM_VISION_MODEL = "qwen2.5:3b"
ENABLE_VISION_FALLBACK = True

# ── Option C: Nvidia ──────────────────────────────────────────────────────
#OPENAI_API_KEY   = os.environ.get("NVIDIA_API_KEY")
#LLM_BASE_URL     = "https://integrate.api.nvidia.com/v1"
#LLM_MODEL        = "meta/llama-3.1-8b-instruct"
#LLM_VISION_MODEL = "meta/llama-3.2-11b-vision-instruct"
#ENABLE_VISION_FALLBACK = False

# ── Option D: Gemini (disabled) ──────────────────────────────────────────
#OPENAI_API_KEY   = os.environ.get("GEMINI_API_KEY")
#LLM_BASE_URL     = "https://generativelanguage.googleapis.com/v1beta/openai/"
#LLM_MODEL        = "gemini-2.5-flash"
#LLM_VISION_MODEL = "gemini-2.5-flash"
#ENABLE_VISION_FALLBACK = False

# ── Option E: Nvidia Nemotron ─────────────────────────────────────────────
#OPENAI_API_KEY   = os.environ.get("NVIDIA_API_KEY")
#LLM_BASE_URL     = "https://integrate.api.nvidia.com/v1"
#LLM_MODEL        = "nvidia/nemotron-3-super-120b-a12b"
#LLM_VISION_MODEL = "nvidia/nemotron-3-super-120b-a12b"
#ENABLE_VISION_FALLBACK = False

# ── Option F: Gemini 2.5 Flash (OpenRouter) (disabled) ───────────────────
#OPENAI_API_KEY   = os.environ.get("OPENROUTER_API_KEY")
#LLM_BASE_URL     = "https://openrouter.ai/api/v1"
#LLM_MODEL        = "google/gemini-2.5-flash:free"
#LLM_VISION_MODEL = "google/gemini-2.5-flash:free"
#ENABLE_VISION_FALLBACK = False
