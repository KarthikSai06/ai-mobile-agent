import logging
import time
from device.adb_controller import AdbController

logger = logging.getLogger(__name__)

# Deep-link rewrites: convert common web URLs into native app deep links
# so the app opens directly instead of Chrome.
_DEEP_LINK_REWRITES = {
    "youtube.com/watch":     "vnd.youtube:",          # YouTube videos
    "youtu.be/":             "vnd.youtube:",          # Short YouTube URLs
    "maps.google.com":       "geo:",                  # Google Maps
    "google.com/maps":       "geo:",                  # Google Maps (alt)
    "wa.me/":                "https://wa.me/",        # WhatsApp (no rewrite, works as-is)
    "play.google.com/store": "market://",             # Play Store
}


def _rewrite_to_deep_link(url: str) -> str:
    """
    Optionally rewrite a web URL into a native deep-link URI so the
    correct app opens instead of Chrome.
    Returns the (possibly rewritten) URL.
    """
    for pattern, deep_prefix in _DEEP_LINK_REWRITES.items():
        if pattern in url:
            if deep_prefix == "vnd.youtube:":
                # Extract video ID and build vnd.youtube URI
                import re
                vid_match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
                if vid_match:
                    new_url = f"vnd.youtube:{vid_match.group(1)}"
                    logger.info(f"Rewrote YouTube URL → {new_url}")
                    return new_url
            elif deep_prefix == "geo:":
                # Keep original URL — Chrome / Maps will handle geo: URIs too
                return url
            elif deep_prefix == "market://":
                # Rewrite play store URL to market:// deep link
                import re
                pkg_match = re.search(r"id=([A-Za-z0-9_.]+)", url)
                if pkg_match:
                    new_url = f"market://details?id={pkg_match.group(1)}"
                    logger.info(f"Rewrote Play Store URL → {new_url}")
                    return new_url
    return url


def execute(adb: AdbController, url: str = None, device_id: str = None) -> bool:
    """
    Opens a URL or deep link on the Android device using an ACTION_VIEW intent.

    Works for:
      - Any HTTPS / HTTP web URL  (opens in Chrome)
      - YouTube videos            (opens in YouTube app via vnd.youtube: deep link)
      - Google Maps links         (opens in Maps app)
      - WhatsApp links            (opens WhatsApp chat)
      - Play Store app pages      (opens Play Store)
      - Any custom deep link      (e.g. instagram://user?username=...)

    Args:
        adb:        AdbController instance
        url:        The URL or deep link to open
        device_id:  ADB device serial (optional)

    Returns:
        True on success, False on failure.
    """
    if not url:
        logger.error("open_url: No URL provided.")
        return False

    # Strip surrounding quotes if the LLM included them
    url = url.strip().strip("'\"")

    # Optionally rewrite to native deep link
    url = _rewrite_to_deep_link(url)

    logger.info(f"Opening URL on device: {url}")

    cmd = []
    if device_id:
        cmd.extend(["-s", device_id])
    cmd.extend([
        "shell", "am", "start",
        "-a", "android.intent.action.VIEW",
        "-d", url
    ])

    try:
        result = adb.run_cmd(*cmd)
        time.sleep(1.5)   # give the app time to open

        # Verify something changed (a new activity launched)
        focus = adb.get_current_focus(device_id)
        if focus:
            logger.info(f"open_url succeeded. Current focus: {focus}")
            return True

        logger.warning("open_url: No focus change detected after launching URL.")
        return True   # Still return True — the intent was fired

    except Exception as e:
        logger.error(f"open_url failed: {e}")
        return False
