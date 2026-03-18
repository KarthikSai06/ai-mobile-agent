<div align="center">

# 🤖 Mobile Agent

### An AI-powered Android automation agent that controls your phone with natural language

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://python.org)
[![ADB](https://img.shields.io/badge/ADB-Android%20Debug%20Bridge-green?logo=android)](https://developer.android.com/tools/adb)
[![OpenAI Compatible](https://img.shields.io/badge/LLM-OpenAI%20Compatible-orange?logo=openai)](https://openai.com)

</div>

---

## 📖 Overview

**Mobile Agent** is a Python automation framework that lets an LLM control a real Android device via ADB. Give it a task in plain English — it reads the UI, plans each action, executes it, learns from the outcome, and keeps going until the task is done.

```
"Open YouTube, search for Believer, and play the first video"
```
↓ The agent opens YouTube, taps the search bar, types "Believer", taps a result, and confirms playback — entirely autonomously.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🗣️ **Natural language tasks** | Give any instruction in plain English |
| 📱 **Real device control** | Works on physical Android phones via USB + ADB |
| 🧠 **LLM action planning** | OpenAI-compatible — works with GPT-4o, OpenRouter, or local Ollama models |
| 👁️ **Vision recovery** | When UI can't be read (ads/video), takes a screenshot and asks the vision model what to tap |
| 📋 **Outcome tracking** | Every action is tracked as `SUCCESS`, `FAILED`, or `NO_CHANGE` — fed back to the LLM |
| 🔁 **Loop detection** | Detects repeated identical actions and presses BACK to escape |
| 🎯 **Smart element resolution** | Resolves element by numeric index, resource ID, or text label |
| ✅ **Task completion detection** | After a vision tap, takes a screenshot and confirms task completion via the vision model |
| 🔌 **Pluggable skill system** | Add new skills by dropping a `.py` file in `skills/` |
| 🧪 **Unit tested** | 14 tests covering all core behaviours |

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
                     │  (decides action)│  — text + vision planning
                     └────────┬─────────┘
                              │
                     ┌────────▼─────────┐
                     │ Skill Executor   │  executor/skill_executor.py
                     │ (maps → ADB cmd) │
                     └────────┬─────────┘
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
           open_app         tap          type_text
           scroll        press_key       (skills/)
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
│   └── llm_planner.py          # LLM + vision model calls
├── executor/
│   └── skill_executor.py       # Action dispatcher + element resolver
├── device/
│   └── adb_controller.py       # Raw ADB command runner
├── ui/
│   ├── dump_ui.py              # uiautomator dump with scroll-retry recovery
│   └── ui_parser.py           # XML → element list parser
├── skills/
│   ├── open_app.py
│   ├── tap.py
│   ├── type_text.py
│   ├── scroll.py
│   └── press_key.py
└── tests/
    └── test_agent_fixes.py     # 14 unit tests
```

---

## ⚙️ Setup

### 1. Prerequisites

- Python 3.10+
- ADB installed and in `PATH` (or in `%LOCALAPPDATA%\Android\Sdk\platform-tools\`)
- Android device with **USB Debugging** enabled

### 2. Install dependencies

```bash
pip install openai
```

### 3. Configure your LLM backend

Edit `config/settings.py` — choose **one** option:

**Option A — OpenRouter or OpenAI (recommended)**
```python
OPENAI_API_KEY   = "sk-or-v1-..."               # Your API key
LLM_BASE_URL     = "https://openrouter.ai/api/v1"
LLM_MODEL        = "openai/gpt-4o-mini"
LLM_VISION_MODEL = "openai/gpt-4o-mini"
ENABLE_VISION_FALLBACK = False                   # Not needed with cloud models
```

**Option B — Local Ollama (free, offline)**
```python
OPENAI_API_KEY   = "dummy_key"
LLM_BASE_URL     = "http://localhost:11434/v1"
LLM_MODEL        = "llama3.2:latest"
LLM_VISION_MODEL = "moondream:latest"
ENABLE_VISION_FALLBACK = True                    # Helps small models when stuck
```

---

## 🚀 Usage

```bash
# Basic task
python main.py "Open Settings"

# With device ID and step limit
python main.py "Open YouTube and search for Believer" --device 10BF5P1PNN0010T --steps 20

# Send a message
python main.py "Open Telegram and send hi to bujji" --device 10BF5P1PNN0010T --steps 20
```

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
# 14 tests, all passing
```

---

## 📋 Supported Skills

| Skill | Arguments | Description |
|---|---|---|
| `open_app` | `package_name` | Launch app via intent |
| `tap` | `id` or `x, y` | Tap UI element or coordinates |
| `type_text` | `text` | Type into focused field |
| `scroll` | `direction`, `x, y` | Scroll up/down/left/right |
| `press_key` | `key` | Press BACK, HOME, ENTER, etc. |
| `done` | — | Signal task complete |
