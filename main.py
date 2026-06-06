"""
main.py — AI Mobile Agent entry point

Usage:
  python main.py                     — Start API server + terminal chat UI (default)
  python main.py --task "..."        — Run a single task headlessly (script mode)
  python main.py --server-only       — Run only the Flask API server (for HTTP Shortcuts)
  python main.py --task "..." --steps 25 --skip-check
"""

import logging
import argparse
import sys
import threading
import time
import socket
import httpx
from config import settings


# ── Logging setup ─────────────────────────────────────────────────────────────

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(f"{settings.LOGS_DIR}/agent.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


# ── LLM connection check ──────────────────────────────────────────────────────

def validate_llm_connection() -> bool:
    """Quick sanity check that the LLM is reachable and outputs valid format."""
    logger = logging.getLogger(__name__)
    try:
        import openai
        client = openai.OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.LLM_BASE_URL if settings.LLM_BASE_URL else None,
            timeout=httpx.Timeout(15.0, connect=5.0),
        )
        logger.info(f"Testing LLM connection: {settings.LLM_BASE_URL} / model: {settings.LLM_MODEL}")
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": "Output ONLY two lines:\nSKILL: <name>\nARGS: <key=val>"},
                {"role": "user",   "content": "Task: Open YouTube.\nReply with the action:"},
            ],
            temperature=0.0,
        )
        output = response.choices[0].message.content.strip()
        logger.info(f"LLM test response: {output}")
        if not output:
            logger.warning("⚠ LLM returned empty response. Agent may struggle with this model.")
        else:
            logger.info("✓ LLM connection OK")
        return True
    except Exception as e:
        logger.error(f"✗ LLM connection FAILED: {e}")
        logger.error(f"  Check that your LLM is running at: {settings.LLM_BASE_URL}")
        logger.error(f"  Model: {settings.LLM_MODEL}")
        return False


# ── API server helpers ────────────────────────────────────────────────────────

def _get_local_ip() -> str:
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


def start_api_server(port: int = 5000) -> threading.Thread:
    """
    Start the Flask API server in a daemon background thread.
    Returns the thread so the caller can join it if needed.
    """
    import api_server as _api
    import logging as _logging
    # Suppress Flask's startup noise (we'll print our own banner)
    _logging.getLogger("werkzeug").setLevel(_logging.ERROR)

    def _serve():
        _api.app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

    t = threading.Thread(target=_serve, daemon=True, name="api-server")
    t.start()
    return t


def _wait_for_server(port: int = 5000, timeout: float = 6.0) -> bool:
    """Poll localhost until the server is accepting connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=0.5)
            s.close()
            return True
        except OSError:
            time.sleep(0.3)
    return False


# ── Headless single-task mode ─────────────────────────────────────────────────

def run_headless(task: str, device: str, steps: int, skip_check: bool):
    """Original CLI behaviour: run one task and exit."""
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Initializing Mobile Agent (headless mode)…")

    if not skip_check:
        if not validate_llm_connection():
            logger.error("Aborting: LLM is not reachable. Fix connection or use --skip-check to bypass.")
            sys.exit(1)

    from agent.agent_loop import AgentLoop
    agent = AgentLoop(device_id=device)
    agent.run(task=task, max_steps=steps)


# ── Interactive terminal chat mode (default) ──────────────────────────────────

def run_chat(skip_check: bool, port: int = 5000):
    """Start the API server + rich terminal chat UI."""
    # Suppress verbose logging to keep the terminal clean for the chat UI
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(f"{settings.LOGS_DIR}/agent.log", encoding="utf-8"),
        ],
    )

    from rich.console import Console
    from rich.panel import Panel
    c = Console()

    local_ip = _get_local_ip()

    c.print(Panel(
        f"[bold cyan]AI Mobile Agent[/bold cyan]\n\n"
        f"[dim]Starting API server on port {port}…[/dim]",
        border_style="cyan",
    ))

    # LLM check (non-fatal in chat mode — just warn)
    if not skip_check:
        if not validate_llm_connection():
            c.print("[bold yellow]⚠ Warning:[/bold yellow] LLM check failed. The agent may not work correctly.")
            c.print("[dim]Press Enter to continue anyway, or Ctrl+C to quit.[/dim]")
            try:
                input()
            except (KeyboardInterrupt, EOFError):
                sys.exit(0)

    # Start the API server in the background
    start_api_server(port=port)
    if _wait_for_server(port=port):
        c.print(f"[green]✓[/green] API server running at [bold]http://localhost:{port}[/bold]  |  Phone: [bold]http://{local_ip}:{port}[/bold]")
    else:
        c.print(f"[yellow]⚠[/yellow] API server may not be ready yet. Proceeding anyway…")

    time.sleep(0.5)

    # Launch the terminal chat UI
    from chat.terminal_ui import run as run_terminal
    run_terminal()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AI Android Automation Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py                          # Terminal chat UI (default)\n"
            "  python main.py --task 'Open YouTube'   # Run one task headlessly\n"
            "  python main.py --server-only            # API server only (for HTTP Shortcuts)\n"
        ),
    )
    parser.add_argument("--task",        type=str,  help="Run a single task headlessly and exit", default=None)
    parser.add_argument("--device",      type=str,  help="ADB device ID (optional)", default=None)
    parser.add_argument("--steps",       type=int,  help="Max steps for headless task", default=15)
    parser.add_argument("--skip-check",  action="store_true", help="Skip LLM connection check")
    parser.add_argument("--server-only", action="store_true", help="Start only the API server (no chat UI)")
    parser.add_argument("--port",        type=int,  help="API server port (default 5000)", default=5000)
    args = parser.parse_args()

    if args.task:
        # Headless single-task mode (original behaviour, keeps full logging)
        run_headless(
            task=args.task,
            device=args.device,
            steps=args.steps,
            skip_check=args.skip_check,
        )

    elif args.server_only:
        # Server-only mode: start Flask and block
        setup_logging()
        local_ip = _get_local_ip()
        print(f"\n{'='*55}")
        print("  [API] Mobile Agent API Server")
        print(f"{'='*55}")
        print(f"  Local URL : http://localhost:{args.port}")
        print(f"  Phone URL : http://{local_ip}:{args.port}")
        print(f"{'='*55}\n")
        import api_server as _api
        _api.app.run(host="0.0.0.0", port=args.port, debug=False)

    else:
        # Default: terminal chat UI + auto-start API server
        run_chat(skip_check=args.skip_check, port=args.port)


if __name__ == "__main__":
    main()
