from device.adb_controller import AdbController
import json
import os
import logging

logger = logging.getLogger(__name__)


def execute(
    adb: AdbController,
    device_id: str = None,
    save_as: str = "",
    _last_elements: list = None,
) -> bool:
    """
    Summarizes the visible screen content using the LLM.

    Steps:
      1. Extract all text/content-desc from the latest UI elements.
      2. Send that text to the LLM with a summarization prompt.
      3. Print the summary and optionally save it to agent memory.

    ARGS:
      save_as=<key>   — memory key to store the summary (optional)
    """
    # ── 1. Extract text from UI elements ────────────────────────────────────────
    if not _last_elements:
        logger.warning("summarize_text: no UI elements available. Run after a UI dump step.")
        return False

    texts = []
    for el in _last_elements:
        t = el.get("text", "").strip()
        d = el.get("content_desc", "").strip()
        if t and t not in texts:
            texts.append(t)
        if d and d not in texts and d != t:
            texts.append(d)

    if not texts:
        logger.warning("summarize_text: no text found on screen.")
        print("\n[summarize_text] No text found on screen.\n")
        return False

    screen_text = "\n".join(texts)
    logger.info(f"summarize_text: extracted {len(texts)} text items from screen.")

    # ── 2. Call LLM to summarize ─────────────────────────────────────────────────
    summary = _call_llm_summarize(screen_text)
    if not summary:
        logger.error("summarize_text: LLM returned empty summary.")
        return False

    print(f"\n[summarize_text]\n{summary}\n")
    logger.info(f"Summary: {summary}")

    # ── 3. Optionally save to memory ─────────────────────────────────────────────
    if save_as:
        memory_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "storage", "memory.json"
        )
        try:
            mem = {}
            if os.path.exists(memory_path):
                with open(memory_path, "r", encoding="utf-8") as f:
                    mem = json.load(f)
            mem[save_as] = summary
            with open(memory_path, "w", encoding="utf-8") as f:
                json.dump(mem, f, ensure_ascii=False, indent=2)
            logger.info(f"summarize_text: saved summary to memory key '{save_as}'")
        except Exception as e:
            logger.error(f"summarize_text: failed to save to memory: {e}")

    return True


def _call_llm_summarize(screen_text: str) -> str:
    """Calls the configured LLM to produce a concise summary of screen_text."""
    try:
        import openai
        from config import settings

        client = openai.OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.LLM_BASE_URL if settings.LLM_BASE_URL else None,
        )

        prompt = (
            "You are a helpful assistant. Below is the raw text currently visible on an "
            "Android device screen. Produce a clear, concise summary (3–5 sentences) of "
            "what is shown — the app, key information, and any actions visible.\n\n"
            f"Screen text:\n{screen_text}\n\n"
            "Summary:"
        )

        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"summarize_text: LLM call failed: {e}")
        return ""
