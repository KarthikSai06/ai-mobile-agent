"""
chat/terminal_ui.py — Rich-powered terminal chat interface for the AI Mobile Agent.

Starts automatically when you run: python main.py

Changes vs v1:
  - Uses Rich Live for REAL-TIME step updates while agent is running.
    The screen refreshes every 0.8 s automatically — no need to press Enter.
  - Completed steps are announced as chat messages as they happen.
  - Typing "stop" + Enter cancels the running task mid-flight.

Commands (at the prompt):
  <anything>   — Run a task on the Android device
  stop         — Cancel the currently running task
  history      — Show the last task's action history
  memory       — Show stored memory keys
  clear        — Clear the chat log
  quit / exit  — Exit the program
"""

import time
import threading
import sys
import requests
from rich.console import Console
from rich.panel import Panel
from rich.columns import Columns
from rich.table import Table
from rich.text import Text
from rich.live import Live
from rich.spinner import Spinner
from rich.rule import Rule
from rich import box

API_BASE = "http://localhost:5000"
LIVE_REFRESH_RATE = 0.8   # seconds between screen refreshes while agent runs
POLL_INTERVAL = 0.8       # seconds between API polls during live display

console = Console()

# ── Message log (in-memory) ───────────────────────────────────────────────────
_messages: list[dict] = []
_messages_lock = threading.Lock()


def _add_msg(role: str, text: str):
    with _messages_lock:
        _messages.append({"role": role, "text": text, "time": time.strftime("%H:%M:%S")})


# ── Rendering helpers ─────────────────────────────────────────────────────────

def _render_messages() -> str:
    """Return a Rich-markup string of the last 30 messages."""
    lines = []
    with _messages_lock:
        for m in _messages[-30:]:
            t = m["time"]
            role = m["role"]
            txt = m["text"]
            if role == "user":
                lines.append(f"[dim]{t}[/dim]  [bold cyan]You ›[/bold cyan] {txt}")
            elif role == "agent":
                lines.append(f"[dim]{t}[/dim]  [bold green]Agent ›[/bold green] {txt}")
            elif role == "system":
                lines.append(f"[dim]{t}[/dim]  [dim yellow]System ›[/dim yellow] {txt}")
            elif role == "error":
                lines.append(f"[dim]{t}[/dim]  [bold red]Error ›[/bold red] {txt}")
    return "\n".join(lines) if lines else "[dim]No messages yet. Type a task below.[/dim]"


def _render_task_steps(steps: list, agent_status: str) -> Table:
    """Build a Rich Table showing task steps with live status icons."""
    STATUS_ICON = {
        "pending": "[dim]○[/dim]",
        "current": "[bold yellow]▶[/bold yellow]",
        "done":    "[bold green]✓[/bold green]",
        "failed":  "[bold red]✗[/bold red]",
    }
    STATUS_COLOR = {
        "pending": "dim",
        "current": "yellow",
        "done":    "green",
        "failed":  "red",
    }

    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 1), expand=True)
    tbl.add_column("Icon", width=3, no_wrap=True)
    tbl.add_column("Step", ratio=1)

    if not steps:
        if agent_status == "running":
            tbl.add_row("[bold yellow]…[/bold yellow]", "[dim]Refining task…[/dim]")
        elif agent_status == "idle":
            tbl.add_row("[dim]○[/dim]", "[dim]No active task[/dim]")
        else:
            tbl.add_row("[dim]○[/dim]", "[dim]Waiting for task…[/dim]")
        return tbl

    for step in steps:
        st = step.get("status", "pending")
        icon = STATUS_ICON.get(st, "○")
        color = STATUS_COLOR.get(st, "dim")
        label = step.get("label", "")
        tbl.add_row(icon, f"[{color}]{label}[/{color}]")

    return tbl


def _agent_status_badge(status: str) -> str:
    """Return a Rich-markup colored badge for the agent status."""
    BADGE = {
        "idle":    ("[IDLE]",    "dim"),
        "running": ("[RUNNING]", "bold yellow"),
        "done":    ("[DONE]",    "bold green"),
        "error":   ("[ERROR]",   "bold red"),
    }
    label, style = BADGE.get(status, ("[UNKNOWN]", "dim"))
    return f"[{style}]{label}[/{style}]"


def _build_panels(agent_status: str, steps: list) -> Columns:
    """Build the two-column panel: chat history | task steps."""
    chat_panel = Panel(
        _render_messages(),
        title="[bold]Chat[/bold]",
        border_style="blue",
        padding=(0, 1),
    )
    if agent_status == "done":
        step_border = "green"
    elif agent_status == "running":
        step_border = "yellow"
    else:
        step_border = "dim"

    steps_panel = Panel(
        _render_task_steps(steps, agent_status),
        title=f"[bold]Task Steps[/bold]  {_agent_status_badge(agent_status)}",
        border_style=step_border,
        padding=(0, 1),
        width=44,
    )
    return Columns([chat_panel, steps_panel], expand=True)


# ── API helpers ───────────────────────────────────────────────────────────────

def _post_task(task: str, steps: int = 20) -> dict:
    try:
        r = requests.post(f"{API_BASE}/run-task", json={"task": task, "steps": steps}, timeout=5)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _get_status() -> dict:
    try:
        r = requests.get(f"{API_BASE}/status", timeout=3)
        return r.json()
    except Exception:
        return {"agent": "unreachable"}


def _get_task_steps() -> dict:
    try:
        r = requests.get(f"{API_BASE}/task-steps", timeout=3)
        return r.json()
    except Exception:
        return {"steps": [], "status": "unreachable"}


def _get_history() -> dict:
    try:
        r = requests.get(f"{API_BASE}/history", timeout=3)
        return r.json()
    except Exception:
        return {"action_history": []}

def _get_chat_replies() -> dict:
    try:
        r = requests.get(f"{API_BASE}/chat-replies", timeout=3)
        return r.json()
    except Exception:
        return {"chat_replies": []}


def _get_memory() -> dict:
    try:
        r = requests.get(f"{API_BASE}/memory", timeout=3)
        return r.json()
    except Exception:
        return {}


def _post_stop() -> dict:
    try:
        r = requests.post(f"{API_BASE}/stop", timeout=3)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


# ── Header ────────────────────────────────────────────────────────────────────

def _print_header():
    console.print(Panel(
        "[bold cyan]AI Mobile Agent[/bold cyan]  [dim]— Terminal Chat[/dim]\n"
        "[dim]Type a task to run on your Android device.\n"
        "Commands: [bold]stop[/bold]  [bold]history[/bold]  [bold]memory[/bold]  [bold]clear[/bold]  [bold]quit[/bold][/dim]",
        border_style="cyan",
        padding=(0, 2),
    ))


# ── Live display while agent is running ───────────────────────────────────────

def _live_run_display():
    """
    Uses Rich Live to auto-refresh the chat + step panels every POLL_INTERVAL
    seconds while the agent is running.

    A background thread watches stdin so the user can type 'stop' + Enter
    to cancel the task mid-flight without breaking the live display.

    Returns when the agent status leaves 'running' (done, error, or idle).
    """
    stop_flag = threading.Event()      # set when user types 'stop'
    stdin_done = threading.Event()     # set when stdin thread exits

    def _stdin_watcher():
        """Background thread: reads one line from stdin."""
        try:
            # sys.stdin.readline() is blocking — that's fine here
            line = sys.stdin.readline().strip().lower()
            if line in ("stop", "s", "q", "quit", "exit"):
                stop_flag.set()
        except Exception:
            pass
        finally:
            stdin_done.set()

    watcher = threading.Thread(target=_stdin_watcher, daemon=True)
    watcher.start()

    prev_done_count = 0
    prev_replies_count = 0
    announced_final = False

    console.print(
        "\n[dim]Live updates active. Type [bold]stop[/bold] + Enter to cancel.[/dim]\n"
    )

    with Live(
        console=console,
        refresh_per_second=int(1 / LIVE_REFRESH_RATE),
        screen=False,
        transient=False,
    ) as live:

        while True:
            # ── 1. Poll API ───────────────────────────────────────────────
            st = _get_status()
            agent_status = st.get("agent", "idle")
            steps_data = _get_task_steps()
            steps = steps_data.get("steps", [])

            # ── 2. Announce newly-completed steps and chat replies ────────
            done_count = sum(1 for s in steps if s["status"] == "done")
            if done_count > prev_done_count:
                for i in range(prev_done_count, done_count):
                    if i < len(steps):
                        _add_msg("agent", f"✓ {steps[i]['label']}")
                prev_done_count = done_count

            replies_data = _get_chat_replies()
            replies = replies_data.get("chat_replies", [])
            if len(replies) > prev_replies_count:
                for i in range(prev_replies_count, len(replies)):
                    _add_msg("agent", f"💬 {replies[i]['text']}")
                prev_replies_count = len(replies)

            # ── 3. Handle stop request from stdin ─────────────────────────
            if stop_flag.is_set():
                resp = _post_stop()
                _add_msg("system", resp.get("message", str(resp)))
                stop_flag.clear()

            # ── 4. Build subtitle hint based on status ────────────────────
            if agent_status == "running":
                subtitle = "[dim]Type [bold]stop[/bold] + Enter to cancel[/dim]"
            elif agent_status == "done":
                subtitle = "[bold green]✅ Task complete![/bold green]"
            elif agent_status == "error":
                subtitle = f"[bold red]❌ Error: {st.get('error', '?')}[/bold red]"
            else:
                subtitle = ""

            border = (
                "green" if agent_status == "done"
                else "red" if agent_status == "error"
                else "cyan"
            )

            live.update(Panel(
                _build_panels(agent_status, steps),
                title="[bold cyan]AI Mobile Agent[/bold cyan]",
                border_style=border,
                subtitle=subtitle,
                padding=0,
            ))

            # ── 5. Detect terminal state ───────────────────────────────────
            if agent_status != "running" and not announced_final:
                announced_final = True
                if agent_status == "done":
                    _add_msg("agent", "✅ Task completed successfully!")
                elif agent_status == "error":
                    _add_msg("error", f"Task failed: {st.get('error', 'unknown error')}")
                # Wait a moment so the user can see the final state
                time.sleep(1.5)
                break

            # If agent already non-running from the start (race condition):
            if agent_status not in ("running",) and announced_final:
                break

            time.sleep(POLL_INTERVAL)

    # stdin watcher may still be blocking on readline — we can't kill it,
    # but it's a daemon thread so it will be cleaned up when the program exits.


# ── Main chat loop ────────────────────────────────────────────────────────────

def run():
    """Entry point — runs the interactive terminal chat loop."""
    _print_header()

    # Initial server check
    st = _get_status()
    if st.get("agent") == "unreachable":
        _add_msg("error", "API server not reachable at localhost:5000. Starting should fix this.")
    else:
        _add_msg("system", f"Connected to API server. Agent is {st.get('agent', '?')}.")

    while True:
        # ── Check if agent is already running (e.g. resumed session) ──────
        st = _get_status()
        agent_status = st.get("agent", "idle")

        if agent_status == "running":
            # Jump straight into the live display
            _live_run_display()
            continue   # loop back, refresh state after live display exits

        # ── Idle/done/error — show static panels and prompt ──────────────
        steps_data = _get_task_steps()
        steps = steps_data.get("steps", [])

        console.clear()
        _print_header()
        console.print(_build_panels(agent_status, steps))

        try:
            user_input = console.input("\n[bold cyan]You ›[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            sys.exit(0)

        if not user_input:
            continue

        # ── Built-in commands ─────────────────────────────────────────────

        low = user_input.lower()

        if low in ("quit", "exit", "q"):
            console.print("[dim]Goodbye![/dim]")
            sys.exit(0)

        if low == "clear":
            with _messages_lock:
                _messages.clear()
            continue

        if low == "stop":
            resp = _post_stop()
            _add_msg("system", resp.get("message", str(resp)))
            continue

        if low == "history":
            h = _get_history()
            rows = h.get("action_history", [])
            if not rows:
                _add_msg("system", "No action history for the last task.")
            else:
                tbl = Table(title="Action History", box=box.SIMPLE_HEAVY, show_lines=False)
                tbl.add_column("#", width=4)
                tbl.add_column("Action", ratio=3)
                tbl.add_column("Outcome", width=12)
                for i, r in enumerate(rows, 1):
                    col = "green" if r["outcome"] == "SUCCESS" else "red" if r["outcome"] == "FAILED" else "yellow"
                    tbl.add_row(str(i), r["action"], f"[{col}]{r['outcome']}[/{col}]")
                console.print(tbl)
                console.input("[dim]Press Enter to continue…[/dim]")
            continue

        if low == "memory":
            mem = _get_memory()
            if not mem:
                _add_msg("system", "Memory is empty.")
            else:
                tbl = Table(title="Stored Memory", box=box.SIMPLE_HEAVY)
                tbl.add_column("Key", style="cyan")
                tbl.add_column("Value")
                for k, v in mem.items():
                    tbl.add_row(k, str(v)[:120])
                console.print(tbl)
                console.input("[dim]Press Enter to continue…[/dim]")
            continue

        # ── Send as a new task ────────────────────────────────────────────

        if agent_status == "running":
            _add_msg("error", "Agent is already running a task. Type 'stop' to cancel it first.")
            continue

        _add_msg("user", user_input)
        resp = _post_task(user_input)

        if "error" in resp:
            _add_msg("error", resp["error"])
        else:
            _add_msg("agent", "Task started! Watching live progress…")
            # Next loop iteration detects "running" and enters live display
