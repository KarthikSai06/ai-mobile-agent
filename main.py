import logging
import argparse
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

def main():
    parser = argparse.ArgumentParser(description="AI Android Automation Agent")
    parser.add_argument("task", type=str, help="The task to perform (e.g., 'Open YouTube and search believer')")
    parser.add_argument("--device", type=str, help="ADB device ID (optional)", default=None)
    parser.add_argument("--steps", type=int, help="Maximum number of steps", default=15)
    
    args = parser.parse_args()
    
    setup_logging()
    
    logger = logging.getLogger(__name__)
    logger.info("Initializing Mobile Agent...")
    
    # Initialize and run agent
    agent = AgentLoop(device_id=args.device)
    agent.run(task=args.task, max_steps=args.steps)

if __name__ == "__main__":
    main()
