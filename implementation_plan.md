# Smarter Vision Agent Invocation

The agent currently invokes the vision model only when `uiautomator dump` fails (fullscreen video).
The Telegram "find bujji" failure shows we need vision in three additional scenarios
where the agent is stuck but the UI is technically readable.

## Proposed Triggers

### Trigger 1 — Loop Detected (same action × 3) → Vision First, BACK as fallback
**Current**: Loop detector immediately presses BACK.  
**Problem**: BACK navigates away — the agent had the right screen (Telegram chat list) but was tapping the wrong element. It needed to scroll or search, not go back.  
**Fix**: On loop detection, take a screenshot and ask vision "what should I do to progress on this task?" before pressing BACK. Only press BACK if vision fails.

**File**: [agent/agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py) — [run()](file:///d:/projects/mobile_agent/agent/agent_loop.py#33-152) loop detector block

---

### Trigger 2 — NO_CHANGE Streak (3 consecutive NO_CHANGE outcomes) → Vision
**Current**: Not handled at all.  
**Problem**: Agent taps/scrolls but UI doesn't change — it's stuck in a visually different way than a loop. e.g. Telegram search bar isn't being focused, or the scroll isn't hitting new content.  
**Fix**: Count consecutive NO_CHANGE outcomes. After 3 in a row, take a screenshot and ask the vision model what to tap instead.

**File**: [agent/agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py) — add `no_change_streak` counter alongside existing history

---

### Trigger 3 — `tap(text=X)` Fails to Resolve → Vision Locate
**Current**: [_resolve_text_to_coords](file:///d:/projects/mobile_agent/executor/skill_executor.py#57-80) fails silently, tap is skipped (returns False → FAILED in history).  
**Problem**: For "find bujji", the LLM sends `tap(text='bujji')` but the element may be off-screen. The executor can't find it so it fails. The agent then repeats the same tap on the next step.  
**Fix**: When [_resolve_text_to_coords](file:///d:/projects/mobile_agent/executor/skill_executor.py#57-80) matches nothing, instead of silently failing, signal back to [agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py) to take a screenshot and ask the vision model where the element is and what to do (scroll to find it, or tap a search bar).

**File**: [executor/skill_executor.py](file:///d:/projects/mobile_agent/executor/skill_executor.py) + [agent/agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py)

---

## Proposed Changes

### [agent/agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py)

#### [MODIFY] [agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py)

```
# 1. Loop detector — vision first, BACK as fallback
if loop_detected:
    screenshot → get_action_from_screenshot(task) → execute tap
    if tap fails: press BACK (existing fallback)

# 2. NO_CHANGE streak counter
no_change_streak = 0
if outcome == "NO_CHANGE":
    no_change_streak += 1
else:
    no_change_streak = 0

if no_change_streak >= 3:
    screenshot → get_action_from_screenshot(task) → execute tap
    no_change_streak = 0
```

### [executor/skill_executor.py](file:///d:/projects/mobile_agent/executor/skill_executor.py)

#### [MODIFY] [skill_executor.py](file:///d:/projects/mobile_agent/executor/skill_executor.py)

```
# _resolve_text_to_coords: return a special signal when element not found
# so agent_loop knows to escalate to vision
return {"vision_needed": True, "label": label}
```

### [agent/agent_loop.py](file:///d:/projects/mobile_agent/agent/agent_loop.py) (for tap text failure)

```
result = executor.execute_skill("tap", args)
if isinstance(result, dict) and result.get("vision_needed"):
    screenshot → get_action_from_screenshot(task, hint=f"find element '{label}'")
    execute tap at returned coords
```

---

## Cases Covered After Fix

| Scenario | Before | After |
|---|---|---|
| Tapping same chat item 3× (loop) | BACK → leaves Telegram | Vision → "scroll down to find bujji" |
| Scrolling chat list, UI not changing | Nothing | Vision after 3 NO_CHANGE → smarter tap |
| `tap(text='bujji')` not found on screen | Silent FAILED, repeat | Vision → locate bujji or scroll |
| Fullscreen video/ad (dump fails) | Abort | Scroll × 3 → Vision (already done ✅) |

## Verification Plan

- Run `"Open Telegram and send hi to bujji"` and confirm agent:
  1. Opens Telegram chat list ✅
  2. If bujji not visible: vision suggests scrolling → agent scrolls → finds chat
  3. Taps bujji → opens chat → types 'hi' → send → calls [done](file:///d:/projects/mobile_agent/planner/llm_planner.py#180-220)
- Run `"Open Settings"` to confirm existing simple tasks not broken
