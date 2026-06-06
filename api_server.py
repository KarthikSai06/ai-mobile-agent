"""
api_server.py — Flask REST API for Mobile Agent
Allows the agent to be triggered remotely (e.g. from HTTP Shortcuts on Android).

Usage:
    python api_server.py

Endpoints:
    POST /run-task      { "task": "...", "steps": 20 }  — run a task
    GET  /status        — check if server is alive + agent status
    GET  /history       — last task result (with action history)
    GET  /task-steps    — live refined step list with statuses
    GET  /memory        — stored memory.json contents
    POST /stop          — signal agent to stop
"""

import logging
import threading
import time
from flask import Flask, request, jsonify
from config import settings

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(f"{settings.LOGS_DIR}/api_server.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ── Shared state ────────────────────────────────────────────────────────────
_state = {
    "status": "idle",       # idle | running | done | error
    "task": "",
    "refined_task": "",
    "started_at": None,
    "finished_at": None,
    "error": None,
    # Live step tracker (list of {label, status})
    # status: pending | current | done | failed
    "steps": [],
    # Full action history (list of {action, outcome})
    "action_history": [],
    # Conversational replies from the agent
    "chat_replies": [],
}
_lock = threading.Lock()
_stop_requested = False


# ── Step update callback (injected into AgentLoop) ──────────────────────────

def _on_step_update(action: str, outcome: str):
    """
    Called by AgentLoop after every executed step.
    Appends to action_history and advances step statuses.
    """
    with _lock:
        _state["action_history"].append({"action": action, "outcome": outcome})

        steps = _state["steps"]
        if not steps:
            return

        # Find the first non-done step and mark it appropriately
        for i, step in enumerate(steps):
            if step["status"] in ("current", "pending"):
                if outcome == "SUCCESS":
                    step["status"] = "done"
                    # Mark next step as current
                    if i + 1 < len(steps):
                        steps[i + 1]["status"] = "current"
                    else:
                        # ── Last step just completed ──────────────────────
                        # Signal the agent loop so it can check completion
                        _state["all_steps_done"] = True
                elif outcome == "FAILED":
                    step["status"] = "failed"
                # NO_CHANGE keeps the step as current
                break


def _on_refined_task(refined: str):
    """
    Called once the planner has refined the task into numbered steps.
    Parses numbered lines and populates _state['steps'].
    """
    import re
    matches = re.findall(r"^\s*\d+\.\s+(.+)", refined, re.MULTILINE)
    with _lock:
        _state["refined_task"] = refined
        _state["steps"] = [
            {"label": m.strip(), "status": "pending"} for m in matches
        ]
        # Mark first step as current
        if _state["steps"]:
            _state["steps"][0]["status"] = "current"


# ── Agent runner ─────────────────────────────────────────────────────────────

def _run_agent(task: str, steps: int):
    """Runs the agent in a background thread so the HTTP response returns immediately."""
    global _stop_requested
    from agent.agent_loop import AgentLoop

    with _lock:
        _state["status"] = "running"
        _state["task"] = task
        _state["refined_task"] = ""
        _state["steps"] = []
        _state["action_history"] = []
        _state["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _state["finished_at"] = None
        _state["error"] = None
        _state["all_steps_done"] = False
        _state["chat_replies"] = []
        _stop_requested = False

    try:
        logger.info(f"Starting agent task: {task!r} (max_steps={steps})")
        def _on_chat_reply(msg: str):
            with _lock:
                _state["chat_replies"].append({
                    "time": time.strftime("%H:%M:%S"),
                    "text": msg
                })

        agent = AgentLoop(
            on_refined_task=_on_refined_task,
            on_chat_reply=_on_chat_reply,
        )

        # ── Wire step update + all_steps_done flag into the agent ─────────────
        # We build a patched step-update closure that calls the normal handler AND
        # immediately forwards the all_steps_done signal into agent._all_steps_done_flag
        # so the run() loop can detect it on the very next iteration.
        def _patched_step_update(action: str, outcome: str):
            _on_step_update(action, outcome)
            with _lock:
                if _state.get("all_steps_done"):
                    _state["all_steps_done"] = False
                    agent._all_steps_done_flag = True

        agent._on_step_update = _patched_step_update

        agent.run(task=task, max_steps=steps)
        with _lock:
            # Mark any remaining pending/current steps as done on clean exit
            for step in _state["steps"]:
                if step["status"] in ("pending", "current"):
                    step["status"] = "done"
            _state["status"] = "done"
    except Exception as e:
        logger.error(f"Agent error: {e}")
        with _lock:
            _state["status"] = "error"
            _state["error"] = str(e)
    finally:
        with _lock:
            _state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/status", methods=["GET"])
def status():
    """Health check — lets the phone/terminal confirm the server is reachable."""
    with _lock:
        return jsonify({
            "server": "online",
            "agent": _state["status"],
            "task": _state["task"],
            "started_at": _state["started_at"],
            "finished_at": _state["finished_at"],
            "error": _state["error"],
        })


@app.route("/run-task", methods=["POST"])
def run_task():
    """
    Trigger a task. Body: { "task": "...", "steps": 20 }
    Returns immediately — use GET /status to poll progress.
    """
    data = request.get_json(force=True, silent=True) or {}
    task = data.get("task", "").strip()
    steps = int(data.get("steps", 20))

    if not task:
        return jsonify({"error": "Missing 'task' field in request body."}), 400

    with _lock:
        if _state["status"] == "running":
            return jsonify({"error": "Agent is already running a task.", "current_task": _state["task"]}), 409

    thread = threading.Thread(target=_run_agent, args=(task, steps), daemon=True)
    thread.start()

    return jsonify({
        "message": "Task started.",
        "task": task,
        "steps": steps,
        "poll": "/status",
    }), 202


@app.route("/history", methods=["GET"])
def history():
    """Returns the last task result including full action history."""
    with _lock:
        return jsonify(dict(_state))


@app.route("/task-steps", methods=["GET"])
def task_steps():
    """
    Returns the live refined step list with per-step statuses.
    Each entry: { "label": str, "status": "pending"|"current"|"done"|"failed" }
    """
    with _lock:
        return jsonify({
            "task": _state["task"],
            "status": _state["status"],
            "steps": list(_state["steps"]),
        })


@app.route("/task-history", methods=["GET"])
def task_history():
    """Returns the raw action-level history for the current/last task."""
    with _lock:
        return jsonify({
            "task": _state["task"],
            "action_history": list(_state["action_history"]),
        })


@app.route("/chat-replies", methods=["GET"])
def chat_replies():
    """Returns conversational messages sent by the agent."""
    with _lock:
        return jsonify({
            "chat_replies": _state["chat_replies"]
        })


@app.route("/memory", methods=["GET"])
def memory():
    """Returns the contents of storage/memory.json for the companion app."""
    import json, os
    memory_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "memory.json")
    try:
        if os.path.exists(memory_path):
            with open(memory_path, "r", encoding="utf-8") as f:
                mem = json.load(f)
            return jsonify(mem)
        return jsonify({})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/stop", methods=["POST"])
def stop():
    """Signals the running agent to stop after its current step."""
    global _stop_requested
    with _lock:
        if _state["status"] != "running":
            return jsonify({"message": "No task is currently running."}), 200
    _stop_requested = True
    return jsonify({"message": "Stop signal sent. Agent will halt after the current step."})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import socket
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print("\n" + "="*55)
    print("  [API] Mobile Agent API Server")
    print("="*55)
    print(f"  Local URL : http://localhost:5000")
    print(f"  Phone URL : http://{local_ip}:5000")
    print(f"  Status    : http://{local_ip}:5000/status")
    print("="*55)
    print("  On your phone (HTTP Shortcuts):")
    print(f"  POST http://{local_ip}:5000/run-task")
    print('  Body: {"task": "open youtube and search kalki"}')
    print("="*55 + "\n")

    app.run(host="0.0.0.0", port=5000, debug=False)
