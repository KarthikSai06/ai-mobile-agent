<div align="center">

# Mobile Agent

### An AI-powered Android automation agent that controls your phone with natural language

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://python.org)
[![ADB](https://img.shields.io/badge/ADB-Android%20Debug%20Bridge-green?logo=android)](https://developer.android.com/tools/adb)
[![Topic](https://img.shields.io/badge/topic-llm--agent-blueviolet)](https://github.com/topics/llm-agent)
[![Topic](https://img.shields.io/badge/topic-android--automation-orange)](https://github.com/topics/android-automation)
[![Topic](https://img.shields.io/badge/topic-agentic--ai-red)](https://github.com/topics/agentic-ai)
[![Topic](https://img.shields.io/badge/topic-mcp-teal)](https://github.com/topics/mcp)
[![Topic](https://img.shields.io/badge/topic-gemini-blue)](https://github.com/topics/gemini)

</div>

---

## Demo

| Demo 1 | Demo 2 | Demo 3 |
|:---:|:---:|:---:|
| [![Watch Demo 1](https://img.youtube.com/vi/T9zF86opMik/0.jpg)](https://youtu.be/T9zF86opMik) | [![Watch Demo 2](https://img.youtube.com/vi/WAjywZKRklM/0.jpg)](https://youtu.be/WAjywZKRklM) | [![Watch Demo 3](https://img.youtube.com/vi/VRrSq7tNWKM/0.jpg)](https://youtu.be/VRrSq7tNWKM?si=Dx2I8XhLeUIopICT) |

---

## Overview

**Mobile Agent** is a Python automation framework that lets an LLM control a real Android device via ADB. Give it a task in plain English — it reads the UI, plans each action, executes it, learns from the outcome, and keeps going until the task is done.

```
"Open YouTube, search for Believer, and play the first video"
"Open Telegram and send hi to bujji"
"Open Amazon, search for football, and add one to cart"
"Turn off WiFi"
"Set brightness to 50 percent"
```

The agent handles it all — reading the screen, planning each step, and executing ADB actions entirely autonomously.

---

## Features

| Feature | Description |
|---|---|
| **Model Context Protocol (MCP)** | Run as an MCP Server to expose Android control to other LLMs and tools |
| **Voice Assistant Integration** | Turn your phone into a system-level assistant triggerable by the Android Home button |
| **Remote Triggering** | Flask API server `api_server.py` with dynamic endpoints like `/stop` |
| **Task Refinement** | Automatically expands raw instructions into step-by-step UI plans |
| **Natural language tasks** | Give any instruction in plain English |
| **Real device control** | Works on physical Android phones via USB or WiFi (ADB) |
| **LLM action planning** | Powered by **Gemini 2.5**, **OpenRouter**, or local **Ollama** models |
| **Persistent Memory** | Store elements or text and reference them via `@key` in future tasks |
| **Optimized execution** | Auto-selects `LocalLLMPlanner` for speed or `LLMPlanner` for complex tasks |
| **Vision Recovery** | Smart escalation to VLM models on loop, no-change, or element-not-found |
| **Smart task completion** | Checks if task is already done via vision **before** recovery attempts |
| **Outcome tracking** | Every action is tracked as `SUCCESS`, `FAILED`, or `NO_CHANGE` |
| **Smart element resolution** | Resolves elements by numeric index, text label, or resource ID |
| **System control skills** | Toggles for WiFi, BT, Airplane mode, Flashlight, Data, Volume, Brightness |
| **Screenshot skill** | Capture the device screen and save as PNG on demand |

---

## Architecture

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
                     │  (decides action)│  — text + vision planning (Gemini 2.5 Flash)
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

## Performance

Each agent step was optimized to minimize dead time between actions. Key improvements:

| Optimization | Saving per step |
|---|---|
| **Removed redundant post-action UI re-dump** | ~3–4s |
| **Trimmed pre-dump sleep** (1.5s → 0.4s) | ~1.1s |
| **Trimmed end-of-step sleep** (2.0s → 1.0s) | ~1.0s |
| **Trimmed vision action sleeps** (2.5s → 1.0s) | ~1.5s |

**Net result: ~2x faster per task** on real-world benchmarks:

| Task | Before | After |
|---|---|---|
| Open YouTube + search | ~3–4 min | ~2 min 18s |
| Open Telegram + send message | ~3 min | ~1 min 13s |
| Open Amazon + search + add to cart | ~3–4 min | ~1 min 37s |

---

## Findings & Limitations (Based on Recent Architecture Tests)

Through extensive testing with local offline models (like `gemma4` or `qwen2.5:3b`) versus cloud models (like OpenRouter or Gemini), we discovered several key limitations and built mitigations for them:

### 1. Hardware & VRAM Bottlenecks 
LLMs need to run organically in your GPU's VRAM to achieve fast execution without stuttering.
*   **Limitation:** If you have **4GB of VRAM** (e.g., RTX 3050), larger models (7B or 11B parameter models like `llama3.2-vision:11b`) will spill over into slow system RAM, causing severe latency in the agent loop.
*   **Mitigation:** We highly advise using `qwen2.5:3b` for the core text planner and `moondream:latest` for the vision fallback on 4GB systems. This combination fits almost entirely inside the GPU and runs the agent loop blazingly fast.

### 2. Local Model "Instruction Drift" (Hallucinations)
Small local models (under 8B parameters) struggle to follow dense, rule-based system prompts, routinely making up non-existent skill names (e.g., outputting `SKILL: browser` instead of `SKILL: open_app`).
*   **Mitigation:** We built a dedicated `LocalLLMPlanner`. Instead of long rules, it uses "Few-shot Examples". It also aggressively truncates the total UI element array to a maximum of 80 clickable-priority elements to prevent context-window overflow. Finally, it uses a built-in `_SKILL_ALIASES` dictionary to silently autocorrect hallucinated intents into valid internal skills.

### 3. Cloud API Rate Limits
During heavy automation sessions, free-tier endpoints on platforms like OpenRouter (e.g., `qwen3.6-plus:free`) will frequently hit `429 Too Many Requests` or `404 Not Found` limits. 
*   **Mitigation:** The agent dynamically auto-selects its planner based on your `LLM_BASE_URL`. Simply swapping your settings to point to `localhost` instantly switches the framework to the robust, offline `LocalLLMPlanner` format without requiring code changes.

---

## Project Structure

```
mobile_agent/
├── main.py                     # CLI entry point
├── api_server.py               # Flask REST API (for remote triggering)
├── mcp_server.py               # MCP Server for exposing tools to other LLMs
├── mcp.json                    # MCP Server configuration mapping
├── config/
│   └── settings.py             # API keys, model selection, ADB path
├── agent/
│   └── agent_loop.py           # Core loop + vision recovery logic
├── planner/
│   └── llm_planner.py          # Task Refiner + Action Planner
├── executor/
│   └── skill_executor.py       # Action dispatcher + @memory resolver
├── device/
│   └── adb_controller.py       # Raw ADB command runner
├── ui/
│   ├── dump_ui.py              # uiautomator dump with recovery
│   └── ui_parser.py            # XML → element list parser
├── skills/
│   ├── open_app.py
│   ├── tap.py / type_text.py
│   ├── scroll.py / press_key.py
│   ├── save_memory.py / delete_memory.py
│   ├── summarize_text.py       # LLM content summary
│   ├── set_wifi.py / set_bluetooth.py
│   ├── set_brightness.py / set_volume.py
│   ├── set_airplane_mode.py / set_flashlight.py
│   ├── set_mobile_data.py
│   ├── extract_text.py / take_screenshot.py
│   └── done.py
└── tests/
    └── test_agent_fixes.py     # Unit tests (all passing)
```

---

## Setup

### 1. Prerequisites

- Python 3.10+
- ADB installed (or available at `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`)
- Android device with **USB Debugging** or **Wireless Debugging** enabled

### 2. Install dependencies

```bash
pip install openai mcp
```

### 3. Configure your LLM backend

Edit `config/settings.py`:

**Option A — OpenRouter / Claude (Recommended)**
```python
OPENAI_API_KEY   = "sk-or-v1-..."                                 # Your OpenRouter API key
LLM_BASE_URL     = "https://openrouter.ai/api/v1"
LLM_MODEL        = "anthropic/claude-3.5-sonnet"
LLM_VISION_MODEL = "anthropic/claude-3.5-sonnet"
```

**Option B — Gemini 2.5 Flash**
```python
OPENAI_API_KEY   = "AIzaSy..."                                    # Your Gemini API key
LLM_BASE_URL     = "https://generativelanguage.googleapis.com/v1beta/openai/"
LLM_MODEL        = "gemini-2.5-flash"
LLM_VISION_MODEL = "gemini-2.5-flash"
```

**Option C — Local Ollama (free, offline)**
```bash
# moondream is excellent for local vision fallback
LLM_BASE_URL     = "http://localhost:11434/v1"
LLM_MODEL        = "llama3.2:latest"
LLM_VISION_MODEL = "moondream:latest"
ENABLE_VISION_FALLBACK = True
```

---

## Connecting Your Device

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

> **Warning:** Don't run `set_wifi off` while connected over WiFi — it will kill your ADB connection!

---

## Usage

### MCP Server Integration (New)
You can now use Mobile Agent as an MCP Server, allowing agents like Claude Desktop to directly interact with your Android phone.

1. Start the MCP server using `mcp.json` mapping.
2. The exposed MCP tools directly map to the Android automation skills.
3. Once running, you can ask your host LLM to:
   - "Get a dump of my Android phone UI"
   - "Tap the element with ID 3"
   - "Type 'hello world' into the current text field"

### Remote Triggering (Android Assistant)
Start the server:
```bash
python api_server.py
```
Trigger tasks via `curl` or **HTTP Shortcuts** on Android:
```bash
POST /run-task  {"task": "open youtube and search believer"}
```

### CLI Usage
```bash
# Basic task
python main.py "Open Settings"

# Using persistent memory (store current page content then use it)
python main.py "Read the screen and save as my_notes"
python main.py "Open Telegram and send @my_notes to bujji"

# System Control
python main.py "Turn on flashlight"
python main.py "Set media volume to 10"
python main.py "Disable WiFi"

# Messaging
python main.py "Open WhatsApp and send hi to Thanu Sree"
```

---

## Supported Skills

| Skill | Arguments | Description |
|---|---|---|
| `open_app` | `package_name` | Launch app via intent |
| `tap` | `id`, `x,y`, or `text` | Tap element by ID, coords, or text label |
| `type_text` | `text` | Type text (supports `@memory_key` refs) |
| `scroll` | `x1,y1,x2,y2` | Swipe/scroll gesture |
| `press_key` | `key` | HOME, BACK, ENTER, VOLUME_UP, VOLUME_DOWN |
| `save_memory` | `key, value` | Store coordinates or text for later |
| `delete_memory` | `key` | Remove a saved memory entry |
| `summarize_text`| `save_as` | Summarize screen content via LLM |
| `set_wifi` | `state=on\|off` | Toggle WiFi |
| `set_bluetooth` | `state=on\|off` | Toggle Bluetooth |
| `set_brightness` | `level, mode` | Set brightness (0-255 or `50%`) |
| `set_volume` | `level, stream` | Set volume (0-15) for media/ring/etc |
| `set_airplane_mode`| `state=on\|off` | Toggle airplane mode |
| `set_flashlight` | `state=on\|off` | Toggle camera torch |
| `set_mobile_data` | `state=on\|off` | Toggle mobile data |
| `extract_text` | `save_as` | Extract all visible text |
| `take_screenshot`| `filename` | Save PNG to `storage/screenshots/` |
| `done` | — | Signal task completion |

---

## Adding a New Skill

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

## Related Research

This project draws inspiration from and builds upon the following academic works in LLM-based GUI agents:

| Paper | What It Does | Relevance |
|---|---|---|
| [**AppAgent**](https://arxiv.org/abs/2312.13771) (2023) | LLM agent that learns to operate Android apps via exploration | Core inspiration for UI-dump → LLM → action loop |
| [**DroidBot-GPT**](https://arxiv.org/abs/2304.07061) (2023) | GPT-4 powered Android testing agent using DroidBot events | Demonstrates LLM-driven UI traversal on real devices |
| [**AndroidWorld**](https://arxiv.org/abs/2405.14573) (2024, Google DeepMind) | Benchmark of 116 programmatic Android tasks for agent evaluation | Benchmark methodology used to design our task suite |
| [**UFO**](https://arxiv.org/abs/2402.07939) (2024, Microsoft) | GUI agent framework using vision + control for Windows/Android | Multi-modal vision recovery pattern reference |

> **Note:** Unlike AppAgent (which relies on exploration/annotation phases), this agent operates **zero-shot** on any app using live UI hierarchy dumps and vision fallback.

---

## Running Tests

```bash
pytest tests/test_agent_fixes.py -v
```
