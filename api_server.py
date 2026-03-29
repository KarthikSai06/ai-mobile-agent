"""
api_server.py — Flask REST API for Mobile Agent
Allows the agent to be triggered remotely (e.g. from HTTP Shortcuts on Android).

Usage:
    python api_server.py

Endpoints:
    POST /run-task      { "task": "...", "steps": 20 }  — run a task
    GET  /status        — check if server is alive
    GET  /history       — last task result
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
    "started_at": None,
    "finished_at": None,
    "error": None,
}
_lock = threading.Lock()
_stop_requested = False


def _run_agent(task: str, steps: int):
    """Runs the agent in a background thread so the HTTP response returns immediately."""
    from agent.agent_loop import AgentLoop
    with _lock:
        _state["status"] = "running"
        _state["task"] = task
        _state["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _state["finished_at"] = None
        _state["error"] = None

    try:
        logger.info(f"Starting agent task: {task!r} (max_steps={steps})")
        agent = AgentLoop()
        agent.run(task=task, max_steps=steps)
        with _lock:
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
    """Health check — lets the phone confirm the server is reachable."""
    return jsonify({"server": "online", "agent": _state["status"]})


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
        "poll": "/status"
    }), 202


@app.route("/history", methods=["GET"])
def history():
    """Returns the last task result."""
    with _lock:
        return jsonify(dict(_state))


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
    print("  📡 Mobile Agent API Server")
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
