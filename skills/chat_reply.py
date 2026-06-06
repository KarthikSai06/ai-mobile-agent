import logging

logger = logging.getLogger(__name__)

def execute(adb, device_id: str, message: str) -> str:
    """
    A non-action skill that allows the agent to reply to the user.
    The message will be displayed in the chat interface.
    """
    logger.info(f"chat_reply: {message}")
    return "SUCCESS"
