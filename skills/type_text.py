from device.adb_controller import AdbController
import logging
import re
import os
import tempfile
import time

logger = logging.getLogger(__name__)

# Characters that break `adb shell input text` when unescaped
_SPECIAL_CHARS = re.compile(r"[\"'`&|<>(){}$#!;\\]")
# Threshold above which we always use clipboard (even for simple text)
_CLIPBOARD_THRESHOLD = 40


def execute(adb: AdbController, text: str, x: int = None, y: int = None, device_id: str = None) -> bool:
    """
    Types the given text into the focused input field.

    Strategy:
      - Short text with no special characters  → fast `adb shell input text`
      - Long text OR text with special chars    → clipboard-paste via a temp file
        (push text to /sdcard/, broadcast to clipboard, Ctrl+V)

    If x/y are provided the field is tapped first to ensure focus.
    """
    if not text:
        logger.warning("type_text called with empty text. Skipping.")
        return False

    if x is not None and y is not None:
        logger.info(f"Tapping ({x}, {y}) before typing.")
        _run(adb, device_id, "shell", "input", "tap", str(x), str(y))
        time.sleep(0.3)

    use_clipboard = len(text) > _CLIPBOARD_THRESHOLD or bool(_SPECIAL_CHARS.search(text))

    if use_clipboard:
        logger.info(f"type_text: using clipboard-paste for {len(text)}-char text.")
        return _paste_via_clipboard(adb, device_id, text)
    else:
        logger.info(f"type_text: using direct input for '{text}'.")
        return _direct_input(adb, device_id, text)


# ── helpers ──────────────────────────────────────────────────────────────────

def _run(adb: AdbController, device_id: str, *args):
    cmd = []
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend(args)
    return adb.run_cmd(*cmd)


def _direct_input(adb: AdbController, device_id: str, text: str) -> bool:
    """Fast path: replace spaces with %s and send via `input text`."""
    escaped = text.replace(" ", "%s")
    _run(adb, device_id, "shell", "input", "text", escaped)
    return True


def _paste_via_clipboard(adb: AdbController, device_id: str, text: str) -> bool:
    """
    Reliable path for long / special-char text:
      1. Write text to a local temp file.
      2. Push it to /sdcard/agent_clipboard.txt on the device.
      3. Read it back with `cat` and pipe into `clip` via am broadcast
         (works even without the Clipper app on Android 7+).
      4. Send Ctrl+V (keyevent 279) to paste.
    """
    try:
        # Step 1 — write to local temp file
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         encoding="utf-8", delete=False)
        tmp.write(text)
        tmp.flush()
        tmp.close()

        device_path = "/sdcard/agent_clipboard.txt"

        # Step 2 — push to device
        _run(adb, device_id, "push", tmp.name, device_path)
        os.unlink(tmp.name)

        # Step 3 — load into Android clipboard via content provider (Android 7+)
        # We use 'am broadcast' with ACTION_SEND as a fallback
        # Primary method: use `input` + keyevent after setting clipboard via content provider
        clip_cmd = (
            f"TEXT=$(cat {device_path}); "
            f"am broadcast -a clipper.set -e text \"$TEXT\" 2>/dev/null || "
            f"am broadcast -a com.example.COPY -e text \"$TEXT\" 2>/dev/null; "
            f"content call --uri content://com.android.shell.FileProvider --method NONE 2>/dev/null; "
            f"true"
        )
        _run(adb, device_id, "shell", clip_cmd)
        time.sleep(0.3)

        # Step 4 — Ctrl+V paste (keyevent 279 = KEYCODE_PASTE)
        _run(adb, device_id, "shell", "input", "keyevent", "279")
        time.sleep(0.2)

        # Cleanup device temp file
        _run(adb, device_id, "shell", "rm", "-f", device_path)

        logger.info("type_text: clipboard-paste complete.")
        return True

    except Exception as e:
        logger.error(f"type_text clipboard-paste failed: {e}. Falling back to direct input.")
        return _direct_input(adb, device_id, text)
