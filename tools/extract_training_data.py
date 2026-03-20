"""
extract_training_data.py
========================
Parses agent.log and produces a JSONL fine-tuning dataset.

Each record = one agent step where the action succeeded, formatted as:
  {
    "messages": [
      {"role": "system", "content": SYSTEM_PROMPT},
      {"role": "user",   "content": "Task: ...\n\nAction History:\n...\n\nUI Elements:\n..."},
      {"role": "assistant", "content": "SKILL: tap\nARGS: id=3"}
    ]
  }

Run:
  python tools/extract_training_data.py
  -> writes storage/training_data.jsonl
"""

import re
import json
import os
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent
LOG_PATH   = BASE_DIR / "storage" / "logs" / "agent.log"
OUT_PATH   = BASE_DIR / "storage" / "training_data.jsonl"

# ── System prompt (same as the live agent) ────────────────────────────────────
SYSTEM_PROMPT = """You are an Android agent. Output ONE action per turn.

Skills:
  tap            ARGS: id=<n>   OR   x=<n> y=<n>
  type_text      ARGS: text=<string>
  open_app       ARGS: package_name=<pkg>
  press_key      ARGS: key=HOME|BACK|ENTER
  scroll         ARGS: x1=500 y1=1500 x2=500 y2=500
  save_memory    ARGS: key=<name> value=<x,y or description>
  delete_memory  ARGS: key=<name>
  done           ARGS: (none)

Rules:
  1. open_app only needs package_name. Never add id/x/y/text to it.
  2. Prefer id over coordinates when available.
  3. If you just tapped a text field/search bar and it succeeded, DO NOT tap it again — proceed to type_text.
  4. After typing a search term do NOT tap the search bar again — tap the result below it.
  5. If you see Message/Mute/Call buttons at y≈738 with NO Emoji/Bot-menu → Profile page. Tap Message to enter chat.
  6. If you see Emoji/Bot-menu at the bottom → Chat window. Tap the Message input box (y>2000) and type. Do NOT tap the header.

Format (copy exactly):
SKILL: <name>
ARGS: <key=val ...>"""

# ── Regex patterns ────────────────────────────────────────────────────────────
RE_SESSION_START = re.compile(r"Starting agent task: (.+)$")
RE_REFINED_END   = re.compile(r"Refined task:\s*$")          # marks start of refined block
RE_STEP          = re.compile(r"=== Step (\d+)/\d+ ===")
RE_UI_HEADER     = re.compile(r"UI Elements sent to LLM:")
RE_UI_ROW        = re.compile(r"^\[(\d+)\] (.+)$")
RE_ACTION        = re.compile(r"Planned Action -> SKILL: (\w+), ARGS: \{(.*?)\}")
RE_HISTORY_ENTRY = re.compile(r"History entry: (.+?) → (SUCCESS|FAILED|SKIPPED)")
RE_SKILL_DONE    = re.compile(r"Task marked as DONE")
RE_LLM_ERR       = re.compile(r"LLM API Error|No LLM client configured")

def parse_args(args_str: str) -> str:
    """Convert Python dict repr back to key=val string."""
    # e.g. "'x': 540, 'y': 1200" -> "x=540 y=1200"
    # e.g. "'package_name': 'org.telegram.messenger'" -> "package_name=org.telegram.messenger"
    pairs = []
    for m in re.finditer(r"'(\w+)':\s*([^\,]+)", args_str):
        k = m.group(1)
        v = m.group(2).strip().strip("'")
        pairs.append(f"{k}={v}")
    return " ".join(pairs) if pairs else "(none)"

def action_to_completion(skill: str, args_str: str) -> str:
    args = parse_args(args_str)
    return f"SKILL: {skill}\nARGS: {args}"

def parse_log(log_path: Path) -> list[dict]:
    examples = []
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    current_task   = None
    refined_task   = None
    collecting_refined = False
    refined_lines  = []

    current_ui     = []
    collecting_ui  = False
    history        = []  # list of "action → outcome" strings

    pending_action = None  # (skill, args_str) waiting for outcome

    i = 0
    while i < len(lines):
        line = lines[i]
        # Strip leading timestamp / log level prefix
        # e.g. "2026-03-21 04:50:36,246 [INFO] agent.agent_loop: Starting agent task: ..."
        content = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ \[\w+\] [\w\.]+: ", "", line).strip()

        # ── New session ───────────────────────────────────────────────────
        m = RE_SESSION_START.search(content)
        if m:
            current_task  = m.group(1).strip()
            refined_task  = None
            history       = []
            current_ui    = []
            collecting_ui = False
            collecting_refined = False
            refined_lines = []
            pending_action = None
            i += 1
            continue

        # ── Refined task block ────────────────────────────────────────────
        if "Refined task:" in content and not collecting_refined:
            collecting_refined = True
            refined_lines = []
            i += 1
            continue
        if collecting_refined:
            # Stop when we hit a new log timestamp line or certain keywords
            if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line) and (
                "agent.agent_loop" in line or "__main__" in line
            ):
                refined_task = (current_task + "\n\nDetailed steps:\n" + "\n".join(refined_lines).strip()
                                if refined_lines else current_task)
                collecting_refined = False
                # Don't increment — reprocess this line
                continue
            else:
                # Strip timestamp prefix if present
                clean = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ \[\w+\] [\w\.]+: ", "", line).strip()
                if clean:
                    refined_lines.append(clean)
                i += 1
                continue

        # ── UI elements block ─────────────────────────────────────────────
        if RE_UI_HEADER.search(content):
            collecting_ui = True
            current_ui    = []
            i += 1
            continue
        if collecting_ui:
            m = RE_UI_ROW.match(content)
            if m:
                current_ui.append(content)
                i += 1
                continue
            else:
                collecting_ui = False  # End of UI block

        # ── Planned action ────────────────────────────────────────────────
        m = RE_ACTION.search(content)
        if m:
            skill     = m.group(1)
            args_str  = m.group(2)
            # Skip done actions and LLM error fallbacks
            if skill != "done":
                pending_action = (skill, args_str, list(current_ui), list(history))
            i += 1
            continue

        # ── History entry = outcome of previous action ────────────────────
        m = RE_HISTORY_ENTRY.search(content)
        if m:
            action_str = m.group(1).strip()
            outcome    = m.group(2)
            history.append(f"{action_str} → {outcome}")

            # Build training example from the pending action if it succeeded
            if pending_action and outcome == "SUCCESS":
                skill, args_str, ui_snap, hist_snap = pending_action
                task_str = refined_task or current_task
                if task_str and ui_snap:
                    history_str = "\n".join(f"  {h}" for h in hist_snap[-5:]) or "  (none)"
                    ui_str      = "\n".join(ui_snap)
                    user_msg    = (
                        f"Task: {task_str}\n\n"
                        f"Action History:\n{history_str}\n\n"
                        f"UI Elements:\n{ui_str}"
                    )
                    completion  = action_to_completion(skill, args_str)
                    examples.append({
                        "messages": [
                            {"role": "system",    "content": SYSTEM_PROMPT},
                            {"role": "user",      "content": user_msg},
                            {"role": "assistant", "content": completion},
                        ]
                    })
            pending_action = None
            i += 1
            continue

        # ── LLM error → discard pending action ───────────────────────────
        if RE_LLM_ERR.search(content):
            pending_action = None

        i += 1

    return examples


def main():
    print(f"Parsing {LOG_PATH} ...")
    examples = parse_log(LOG_PATH)
    print(f"Extracted {len(examples)} training examples")

    # Write JSONL
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"Saved to {OUT_PATH}")

    # Print stats
    skills = {}
    for ex in examples:
        completion = ex["messages"][2]["content"]
        skill = completion.split("\n")[0].replace("SKILL: ", "").strip()
        skills[skill] = skills.get(skill, 0) + 1

    print("\nSkill distribution:")
    for skill, count in sorted(skills.items(), key=lambda x: -x[1]):
        print(f"  {skill:15s} {count:4d} examples")

    # Show a sample
    if examples:
        print("\n── Sample example ──")
        sample = examples[len(examples) // 2]
        print("USER:", sample["messages"][1]["content"][:300], "...")
        print("ASSISTANT:", sample["messages"][2]["content"])


if __name__ == "__main__":
    main()
