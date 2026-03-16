# Local AI-Powered Android Automation Agent

This is a complete Python system for a local AI-powered Android automation agent. It controls an Android phone using ADB and observes the screen using `adb shell uiautomator dump`.

## Features
- **Skill System:** Reusable skills instead of dynamically generated code: `tap`, `type_text`, `open_app`, `press_key`, `scroll`.
- **UI Parsing:** Dumps and parses the XML UI hierarchy into a clean representation (center coordinates, text, content descriptions) for the AI planner.
- **LLM Planner:** Leverages a Large Language Model to decide the next action based on the task, UI state, and action history.

## Architecture

The project follows a modular design:
```text
User Task
↓
Agent Loop (agent/agent_loop.py)
↓
Dump Android UI (ui/dump_ui.py)
↓
Parse UI XML (ui/ui_parser.py)
↓
AI Planner decides next action (planner/llm_planner.py)
↓
Action Executor maps and runs ADB command (executor/skill_executor.py -> skills/*.py)
↓
Repeat until DONE
```

## Requirements
- Python 3.10+
- ADB (Android Debug Bridge) installed and added to your system `PATH`.
- An Android device connected via USB with "USB Debugging" enabled.
- (Optional) `openai` Python package for the real LLM planner.

## Setup Instructions

1. **Install dependencies:**
   ```bash
   pip install openai
   ```
   *(Note: The system uses built-in Python modules for XML parsing and OS interactions. Only the LLM client needs `openai`.)*

2. **Configure API Key / Local LLM:**
   
   **Option A: Cloud Providers (OpenAI, Groq, DeepSeek, etc.)**
   Set your API key and base URL in your environment, or edit `config/settings.py` directly:
   - On Windows (Command Prompt): `set OPENAI_API_KEY=your_api_key`
   - On Windows (PowerShell): `$env:OPENAI_API_KEY="your_api_key"`
   - On Linux/macOS: `export OPENAI_API_KEY="your_api_key"`
   
   **Option B: Running a Local LLM (Free & Private)**
   You can easily run the AI on your own computer using tools like [Ollama](https://ollama.com/) or [LM Studio](https://lmstudio.ai/).
   1. Download and start a local model (e.g., `ollama run llama3`).
   2. Edit `config/settings.py` so it points to your local server instead of a cloud provider:
      ```python
      OPENAI_API_KEY = "dummy_key" # Local servers don't need real keys
      LLM_BASE_URL = "http://localhost:11434/v1" # This is the default Ollama API address
      LLM_MODEL = "llama3" # Or whatever model you downloaded
      ```

## Usage

Ensure your Android device is unlocked and connected. Run the agent by providing a task:

```bash
python main.py "Open YouTube and search believer"
```

You can also specify a device ID and maximum allowed steps:
```bash
python main.py "Turn on Do Not Disturb" --device "emulator-5554" --steps 10
```

## Creating new skills
To create a new skill, add a new `.py` file into the `skills/` folder containing an `execute(adb, ...)` function. Then, map it in `executor/skill_executor.py` and describe it in the system prompt inside `planner/llm_planner.py`.
