import logging
import argparse
import sys
import httpx
from config import settings
from agent.agent_loop import AgentLoop

def setup_logging():
    """Sets up logging to both console and a log file."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(f"{settings.LOGS_DIR}/agent.log", encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

def validate_llm_connection():
    """Quick sanity check that the LLM is reachable and outputs valid format."""
    logger = logging.getLogger(__name__)
    
    try:
        import openai
        client = openai.OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.LLM_BASE_URL if settings.LLM_BASE_URL else None,
            timeout=httpx.Timeout(15.0, connect=5.0)
        )
        
        logger.info(f"Testing LLM connection: {settings.LLM_BASE_URL} / model: {settings.LLM_MODEL}")
        
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": "Output ONLY two lines:\nSKILL: <name>\nARGS: <key=val>"},
                {"role": "user", "content": "Task: Open YouTube.\nReply with the action:"}
            ],
            temperature=0.0,
        )
        output = response.choices[0].message.content.strip()
        logger.info(f"LLM test response: {output}")
        
        # Check if the response is parseable (don't need to be strict here)
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

def main():
    parser = argparse.ArgumentParser(description="AI Android Automation Agent")
    parser.add_argument("task", type=str, help="The task to perform (e.g., 'Open YouTube and search believer')")
    parser.add_argument("--device", type=str, help="ADB device ID (optional)", default=None)
    parser.add_argument("--steps", type=int, help="Maximum number of steps", default=15)
    parser.add_argument("--skip-check", action="store_true", help="Skip LLM connection check")
    
    args = parser.parse_args()
    
    setup_logging()
    
    logger = logging.getLogger(__name__)
    logger.info("Initializing Mobile Agent...")
    
    # Validate LLM before starting
    if not args.skip_check:
        if not validate_llm_connection():
            logger.error("Aborting: LLM is not reachable. Fix connection or use --skip-check to bypass.")
            sys.exit(1)
    
                              
    agent = AgentLoop(device_id=args.device)
    agent.run(task=args.task, max_steps=args.steps)

if __name__ == "__main__":
    main()
