<div align="center">

# 🤖 Mobile Agent

### An AI-powered Android automation agent that controls your phone with natural language

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://python.org)
[![ADB](https://img.shields.io/badge/ADB-Android%20Debug%20Bridge-green?logo=android)](https://developer.android.com/tools/adb)
[![Gemini](https://img.shields.io/badge/LLM-Gemini%202.0%20Flash-orange?logo=google)](https://ai.google.dev/)

</div>

---

## 📖 Overview

**Mobile Agent** is a Python automation framework that lets an LLM control a real Android device via ADB. Give it a task in plain English — it reads the UI, plans each action, executes it, learns from the outcome, and keeps going until the task is done.

```
"Open YouTube, search for Believer, and play the first video"
"Turn off WiFi"
"Set brightness to 50 percent"
"Extract the text on the screen"
```

The agent handles it all — reading the screen, planning each step, and executing ADB actions entirely autonomously.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🗣️ **Natural language tasks** | Give any instruction in plain English |
| 📱 **Real device control** | Works on physical Android phones via USB or WiFi (ADB) |
| 🧠 **LLM action planning** | Powered by **Gemini 2.0 Flash** (OpenAI-compatible API) |
| 👁️ **Vision recovery** | When UI can't be read (ads/video), takes a screenshot and asks Gemini what to tap |
| 📋 **Outcome tracking** | Every action is tracked as `SUCCESS`, `FAILED`, or `NO_CHANGE` — fed back to the LLM |
| 🔁 **Loop detection** | Detects repeated identical actions and presses BACK to escape |
| 🎯 **Smart element resolution** | Resolves elements by numeric index, resource ID, or text label |
| ✅ **Task completion detection** | After a vision tap, confirms task is done via screenshot analysis |
| 🔌 **System control skills** | Toggle WiFi, Bluetooth, airplane mode, flashlight, mobile data, brightness, and volume |
| 📝 **Text extraction** | Extract all visible text from the current screen and save to agent memory |
| 🔌 **Pluggable skill system** | Add new skills by dropping a `.py` file in `skills/` |
| 🧪 **Unit tested** | 10 tests covering all core behaviours, all passing |

---

## 🏗️ Architecture

```
User Task (natural language)
        │
        ▼
┌─────────────────────┐
│    Agent Loop       │  agent/agent_loop.py
│  (orchestrator)     │  — step counter, history, loop detector, vision recovery
└────────┬────────────┘
         │
    ┌────▼────┐      ┌──────────────────┐
    │ UI Dump │ ───► │  UI Parser       │  ui/dump_ui.py + ui_parser.py
    └─────────┘      │  (XML → elements)│
                     └────────┬─────────┘
                              │
                     ┌────────▼─────────┐
                     │  LLM Planner     │  planner/llm_planner.py
                     │  (decides action)│  — text + vision planning (Gemini 2.0 Flash)
                     └────────┬─────────┘
                              │
                     ┌────────▼─────────┐
                     │ Skill Executor   │  executor/skill_executor.py
                     │ (maps → ADB cmd) │
                     └────────┬─────────┘
                              │
       ┌──────────────────────┼──────────────────────┐
       ▼              ▼              ▼                ▼
   open_app         tap          type_text       set_wifi
   scroll        press_key     set_brightness  extract_text
                               (& 8 more...)
```

---

## 📁 Project Structure

```
mobile_agent/
├── main.py                     # Entry point
├── config/
│   └── settings.py             # API keys, model selection, ADB path
├── agent/
│   └── agent_loop.py           # Core agent loop + recovery logic
├── planner/
│   └── llm_planner.py          # LLM + vision model calls (task refiner + action planner)
├── executor/
│   └── skill_executor.py       # Action dispatcher + element resolver
├── device/
│   └── adb_controller.py       # Raw ADB command runner
├── ui/
│   ├── dump_ui.py              # uiautomator dump with scroll-retry recovery
│   └── ui_parser.py            # XML → element list parser
├── skills/
│   ├── open_app.py
│   ├── tap.py
│   ├── type_text.py
│   ├── scroll.py
│   ├── press_key.py
│   ├── save_memory.py
│   ├── delete_memory.py
│   ├── set_wifi.py             # NEW — Toggle WiFi
│   ├── set_bluetooth.py        # NEW — Toggle Bluetooth
│   ├── set_brightness.py       # NEW — Set screen brightness
│   ├── set_volume.py           # NEW — Set audio volume
│   ├── set_airplane_mode.py    # NEW — Toggle airplane mode
│   ├── set_flashlight.py       # NEW — Toggle flashlight/torch
│   ├── set_mobile_data.py      # NEW — Toggle mobile data
│   └── extract_text.py         # NEW — Extract all visible screen text
└── tests/
    └── test_agent_fixes.py     # 10 unit tests (all passing)
```

---

## ⚙️ Setup

### 1. Prerequisites

- Python 3.10+
- ADB installed (or available at `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`)
- Android device with **USB Debugging** or **Wireless Debugging** enabled

### 2. Install dependencies

```bash
pip install openai
```

### 3. Configure your LLM backend

Edit `config/settings.py`:

**Option A — Gemini 2.0 Flash (default, recommended)**
```python
OPENAI_API_KEY   = "AIzaSy..."                                    # Your Gemini API key
LLM_BASE_URL     = "https://generativelanguage.googleapis.com/v1beta/openai/"
LLM_MODEL        = "gemini-2.0-flash"
LLM_VISION_MODEL = "gemini-2.0-flash"
ENABLE_VISION_FALLBACK = False  # Gemini handles vision natively
```

**Option B — OpenRouter / OpenAI**
```python
OPENAI_API_KEY   = "sk-or-v1-..."
LLM_BASE_URL     = "https://openrouter.ai/api/v1"
LLM_MODEL        = "openai/gpt-4o-mini"
LLM_VISION_MODEL = "openai/gpt-4o-mini"
```

**Option C — Local Ollama (free, offline)**
```python
OPENAI_API_KEY   = "dummy_key"
LLM_BASE_URL     = "http://localhost:11434/v1"
LLM_MODEL        = "llama3.2:latest"
LLM_VISION_MODEL = "moondream:latest"
ENABLE_VISION_FALLBACK = True
```

---

## 📲 Connecting Your Device

### USB (classic)
Enable **USB Debugging** in Developer Options and plug in your phone.

### WiFi — Android 11+ (Wireless Debugging)
1. **Settings → Developer Options → Wireless Debugging → ON**
2. Tap **"Pair device with pairing code"** — note the IP, port, and code
3. Run:
```bash
adb pair <IP>:<PAIRING_PORT>   # enter the 6-digit code when prompted
adb connect <IP>:<PORT>        # use the main port shown under Wireless Debugging
adb devices                    # confirm it shows up
```

### WiFi — Android 10 and below
```bash
adb tcpip 5555
adb connect <PHONE_IP>:5555
```

> ⚠️ **Don't run `set_wifi off` while connected over WiFi** — it will kill your ADB connection!

---

## 🚀 Usage

```bash
# Basic task
python main.py "Open Settings"

# With device ID and step limit
python main.py "Open YouTube and search for Believer" --device 10BF5P1PNN0010T --steps 20

# System control tasks (no need to open Settings manually)
python main.py "Turn off WiFi" --steps 3
python main.py "Set brightness to 50 percent" --steps 3
python main.py "Set media volume to 8" --steps 3
python main.py "Turn on flashlight" --steps 3
python main.py "Enable airplane mode" --steps 3

# Text extraction
python main.py "Read the text on screen and save it as page_content" --steps 3

# Messaging
python main.py "Open Telegram and send hi to bujji" --device 10BF5P1PNN0010T --steps 20
```

---

## 🧩 Supported Skills

| Skill | Arguments | Description |
|---|---|---|
| `open_app` | `package_name` | Launch app via intent |
| `tap` | `id` or `x, y` | Tap UI element or coordinates |
| `type_text` | `text` | Type into focused field |
| `scroll` | `x1, y1, x2, y2` | Swipe/scroll gesture |
| `press_key` | `key` | HOME, BACK, ENTER, VOLUME_UP, VOLUME_DOWN |
| `save_memory` | `key, value` | Store coordinates or notes for later steps |
| `delete_memory` | `key` | Remove a saved memory entry |
| `set_wifi` | `state=on\|off` | Toggle WiFi |
| `set_bluetooth` | `state=on\|off` | Toggle Bluetooth |
| `set_brightness` | `level, mode=manual\|auto` | Set brightness (0-255 or `50%`) |
| `set_volume` | `level, stream` | Set volume (0-15) for media/ring/alarm/etc. |
| `set_airplane_mode` | `state=on\|off` | Toggle airplane mode |
| `set_flashlight` | `state=on\|off` | Toggle camera torch (Android 13+) |
| `set_mobile_data` | `state=on\|off` | Toggle mobile data |
| `extract_text` | `save_as` | Extract all visible text; optionally save to memory |
| `done` | — | Signal task is complete |

---

## 🧩 Adding a New Skill

1. Create `skills/my_skill.py`:
```python
from device.adb_controller import AdbController

def execute(adb: AdbController, device_id: str = None, my_param: str = "") -> bool:
    adb.run_cmd("-s", device_id, "shell", "...")
    return True
```

2. Register it in `executor/skill_executor.py`:
```python
from skills import my_skill
self.skills["my_skill"] = my_skill.execute
```

3. Describe it in the system prompt in `planner/llm_planner.py`.

---

## 🧪 Running Tests

```bash
pytest tests/test_agent_fixes.py -v
# 10 tests, all passing
```
