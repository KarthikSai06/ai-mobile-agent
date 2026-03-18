# Mobile Agent — Project Documentation

## What It Does

An Android automation agent that controls a real phone via ADB.
You give it a natural-language task (e.g. `"Open YouTube and search for Believer"`),
and it autonomously taps, types, scrolls, and opens apps to complete it.

---

## Project Structure

```
mobile_agent/
│
├── main.py                     # Entry point — parses args, starts AgentLoop
│
├── config/
│   └── settings.py             # API keys, model names, ADB path, storage dirs
│                               # Toggle between OpenRouter (cloud) and Ollama (local)
│
├── agent/
│   └── agent_loop.py           # Core loop: dump UI → plan → execute → track outcome
│                               # Loop detector, NO_CHANGE tracker, vision recovery
│
├── planner/
│   └── llm_planner.py          # LLM calls for action planning
│                               # Vision helpers: analyze_with_vision,
│                               # get_action_from_screenshot,
│                               # check_task_done_from_screenshot
│
├── executor/
│   └── skill_executor.py       # Dispatches planned actions to skill modules
│                               # Resolves element IDs/text to x,y coordinates
│
├── device/
│   └── adb_controller.py       # Raw ADB command runner + screenshot capture
│
├── ui/
│   ├── dump_ui.py              # uiautomator dump → XML; scroll recovery on failure
│   └── ui_parser.py           # Parses XML → list of elements with text/id/center
│
├── skills/
│   ├── __init__.py
│   ├── open_app.py             # Launch app by package name via monkey intent
│   ├── tap.py                  # ADB input tap x y
│   ├── type_text.py            # ADB input text (clears field first)
│   ├── scroll.py               # ADB input swipe
│   └── press_key.py            # ADB input keyevent (BACK, HOME, ENTER, etc.)
│
├── tests/
│   ├── test_agent_fixes.py     # 14 unit tests covering all 5 original bug fixes
│   ├── test_open_app_robustness.py
│   └── _run_diag.py            # Manual diagnostic runner
│
└── storage/                    # Auto-created at runtime
    ├── logs/agent.log
    ├── screenshots/            # Vision recovery + verification screenshots
    └── ui_dump_*.xml           # Per-step UI dumps
```

---

## Features

| Feature | Where |
|---|---|
| Natural-language task input | `main.py --steps N` |
| UI hierarchy parsing (XML) | [ui/dump_ui.py](file:///d:/projects/mobile_agent/ui/dump_ui.py) + `ui/ui_parser.py` |
| LLM action planning (OpenAI-compatible) | [planner/llm_planner.py](file:///d:/projects/mobile_agent/planner/llm_planner.py) |
| App launch by package name | [skills/open_app.py](file:///d:/projects/mobile_agent/skills/open_app.py) |
| Tap, type, scroll, key press | `skills/` |
| Element resolution: index ID → x,y | [executor/skill_executor.py](file:///d:/projects/mobile_agent/executor/skill_executor.py) |
| Element resolution: resource ID → x,y | [executor/skill_executor.py](file:///d:/projects/mobile_agent/executor/skill_executor.py) |
| Element resolution: text label → x,y | [executor/skill_executor.py](file:///d:/projects/mobile_agent/executor/skill_executor.py) |
| Outcome tracking per action (SUCCESS/FAILED/NO_CHANGE) | [agent/agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py) |
| Loop detection → BACK recovery | [agent/agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py) |
| Malformed LLM output → retry once, then [done](file:///d:/projects/mobile_agent/planner/llm_planner.py#180-220) | [planner/llm_planner.py](file:///d:/projects/mobile_agent/planner/llm_planner.py) |
| Vision soft hint (full UI + quadrant suggestion) | [planner/llm_planner.py](file:///d:/projects/mobile_agent/planner/llm_planner.py) |
| UI dump failure → scroll × 3 → vision tap | [ui/dump_ui.py](file:///d:/projects/mobile_agent/ui/dump_ui.py) + [agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py) |
| Vision completion check from screenshot | [planner/llm_planner.py](file:///d:/projects/mobile_agent/planner/llm_planner.py) + [agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py) |
| OpenRouter / Ollama switchable via config | [config/settings.py](file:///d:/projects/mobile_agent/config/settings.py) |
| `ENABLE_VISION_FALLBACK` per backend | [config/settings.py](file:///d:/projects/mobile_agent/config/settings.py) |
| 14 unit tests (all passing) | [tests/test_agent_fixes.py](file:///d:/projects/mobile_agent/tests/test_agent_fixes.py) |

---

## Bugs Encountered & Fixes

### Bug 1 — Vision Quadrant Was a Hard Filter (Silent Miss)
**Problem:** Moondream returned a quadrant (`"top-right"`). The agent hard-filtered all UI
elements outside that quadrant. If moondream was slightly off, the correct element was
completely invisible to the LLM.  
**Fix:** Made it a **soft hint** — full UI always sent to LLM, quadrant mentioned as a
text hint: `"Vision hint: element likely in top-right area"`. LLM uses its own judgment.  
**File:** [planner/llm_planner.py](file:///d:/projects/mobile_agent/planner/llm_planner.py)

---

### Bug 2 — Action History Had No Outcome (Repeated Mistakes)
**Problem:** History was a flat list of strings like `["tap({'id':5})"]`. The LLM had
no idea whether previous actions succeeded or failed, so it kept repeating mistakes.  
**Fix:** History now stores structured dicts:
```python
{"action": "tap({'id': 5})", "outcome": "SUCCESS"}  # or FAILED / NO_CHANGE
```
Outcome determined by comparing UI dump before/after each action.  
**File:** [agent/agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py)

---

### Bug 3 — Malformed LLM Output Silently Defaulted to Scroll
**Problem:** If the LLM returned garbage (no `SKILL:` line), the parser returned a
[scroll](file:///d:/projects/mobile_agent/tests/test_agent_fixes.py#138-147) as a default. This caused **infinite scroll loops** silently.  
**Fix:** [_parse_llm_output](file:///d:/projects/mobile_agent/planner/llm_planner.py#274-315) now returns `None` on parse failure.
Agent retries once with a shorter prompt. If retry also fails → returns [done](file:///d:/projects/mobile_agent/planner/llm_planner.py#180-220). No silent scroll.  
**File:** [planner/llm_planner.py](file:///d:/projects/mobile_agent/planner/llm_planner.py)

---

### Bug 4 — System Prompt Too Complex for Small Local Models
**Problem:** The original 12-rule prompt caused the local model (llama3.2) to mix skill
arguments, add extra text before `SKILL:`, or ignore format rules entirely.  
**Fix:** Rewrote system prompt: 3 clean rules, compact skills table, one worked example
placed immediately before the `UI Elements:` block so the model sees format→task adjacently.  
**File:** [planner/llm_planner.py](file:///d:/projects/mobile_agent/planner/llm_planner.py)

---

### Bug 5 — Loop Detector Blindly Pressed BACK
**Problem:** When the same action repeated 3×, the agent pressed BACK.
This worked for scroll loops but was wrong when the agent was on the right screen
(e.g. Telegram chat list) and needed to scroll, not navigate away.  
**Current state:** Still presses BACK. **Planned fix (approved):** Vision first — take
screenshot, ask model what to do, only press BACK if vision fails.  
**Files:** [agent/agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py)

---

### Bug 6 — `tap(text='X')` Crashed with "Missing x and y"
**Problem:** The LLM sometimes sent `tap({'text': 'Telegram'})` instead of `tap({'id': N})`.
The [tap.py](file:///d:/projects/mobile_agent/skills/tap.py) skill only accepts `x, y`. The arg filter stripped [text](file:///d:/projects/mobile_agent/executor/skill_executor.py#57-80), leaving no coords,
and Python threw `TypeError: missing positional arguments`.  
**Fix:**
- Added [_resolve_text_to_coords()](file:///d:/projects/mobile_agent/executor/skill_executor.py#57-80) to [skill_executor.py](file:///d:/projects/mobile_agent/executor/skill_executor.py) — searches [last_elements](file:///d:/projects/mobile_agent/executor/skill_executor.py#22-25)
  by text/content-desc and maps to center coordinates.
- Added guard: if tap still has no `x`/`y` after all resolution → `return False` cleanly.  
**File:** [executor/skill_executor.py](file:///d:/projects/mobile_agent/executor/skill_executor.py)

---

### Bug 7 — UI Dump Fails When Video/Ad is Playing (SurfaceView Block)
**Problem:** When YouTube plays a video or ad, the screen is a `SurfaceView`.
`uiautomator dump` cannot traverse it → always returns empty → agent aborted.  
**Fix (3-layer):**
1. [dump_ui.py](file:///d:/projects/mobile_agent/ui/dump_ui.py): On each failure, scroll screen slightly (nudge view hierarchy), retry up to 3 times.
2. [agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py): If all 3 scrolls fail → take screenshot → [get_action_from_screenshot()](file:///d:/projects/mobile_agent/planner/llm_planner.py#130-179) → execute vision-suggested tap → retry step.
3. [agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py): After vision tap → take verification screenshot → [check_task_done_from_screenshot()](file:///d:/projects/mobile_agent/planner/llm_planner.py#180-220) → if YES, break cleanly (task done).  
**Files:** [ui/dump_ui.py](file:///d:/projects/mobile_agent/ui/dump_ui.py), [agent/agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py), [planner/llm_planner.py](file:///d:/projects/mobile_agent/planner/llm_planner.py)

---

### Bug 8 — Moondream Vision Fallback Triggered on Cloud API
**Problem:** `ENABLE_VISION_FALLBACK = True` globally caused the agent to call
moondream even when using gpt-4o-mini (cloud), which doesn't need vision assist
and adds unnecessary API cost/latency.  
**Fix:** `ENABLE_VISION_FALLBACK` is now per-backend in [config/settings.py](file:///d:/projects/mobile_agent/config/settings.py):
- OpenRouter → `False` (cloud model handles reasoning on its own)
- Ollama → `True` (small local model needs vision help when stuck)  
**File:** [config/settings.py](file:///d:/projects/mobile_agent/config/settings.py)

---

### Bug 9 — Agent Doesn't Know When Task Is Complete (Video Case)
**Problem:** When a video starts playing, `uiautomator` fails. The agent enters the
scroll-then-vision recovery loop indefinitely — it tapped the video successfully but
had no way to verify and declare [done](file:///d:/projects/mobile_agent/planner/llm_planner.py#180-220).  
**Fix:** After every vision-based tap, agent takes a verification screenshot and calls
[check_task_done_from_screenshot(task, screenshot)](file:///d:/projects/mobile_agent/planner/llm_planner.py#180-220) — asks vision model `YES/NO` whether
the task is complete. If `YES`, loop breaks cleanly.  
**File:** [planner/llm_planner.py](file:///d:/projects/mobile_agent/planner/llm_planner.py) + [agent/agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py)

---

## Known Limitations / Planned Fixes

| Limitation | Planned Fix |
|---|---|
| Agent can't find off-screen elements (e.g. bujji chat needs scroll) | Trigger vision when `tap(text=X)` fails to resolve |
| Loop detector presses BACK even on correct screen | Vision first, BACK only as last resort |
| 3× NO_CHANGE not handled (scroll with no new content) | Track `no_change_streak`, trigger vision after 3 |
| [done](file:///d:/projects/mobile_agent/planner/llm_planner.py#180-220) skill needs LLM to self-declare; agent overshoots max steps | Completion check runs after vision taps; LLM prompt reinforcement |

---

## Config Reference

```python
# config/settings.py

# OpenRouter (cloud) — recommended
OPENAI_API_KEY   = "sk-or-v1-..."
LLM_BASE_URL     = "https://openrouter.ai/api/v1"
LLM_MODEL        = "openai/gpt-4o-mini"
LLM_VISION_MODEL = "openai/gpt-4o-mini"
ENABLE_VISION_FALLBACK = False

# Local Ollama — for offline use
# OPENAI_API_KEY   = "dummy_key"
# LLM_BASE_URL     = "http://localhost:11434/v1"
# LLM_MODEL        = "llama3.2:latest"
# LLM_VISION_MODEL = "moondream:latest"
# ENABLE_VISION_FALLBACK = True
```

## Running a Task

```powershell
cd d:\projects\mobile_agent
python main.py "Open YouTube and search for Believer" --device 10BF5P1PNN0010T --steps 20
```

## Running Tests

```powershell
pytest tests/test_agent_fixes.py -v   # 14 tests, all passing
```
