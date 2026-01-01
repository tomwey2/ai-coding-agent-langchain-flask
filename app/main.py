import os

from agent.worker import run_agent_cycle
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from extensions import db, scheduler
from models import AgentConfig
from webapp import create_app

load_dotenv()

# Main entry point
if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)

    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
    logger.info(f"GOOGLE_API_KEY: {GOOGLE_API_KEY}")
    if not GOOGLE_API_KEY:
        logger.warning("GOOGLE_API_KEY is not set")
    
    MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
    logger.info(f"MISTRAL_API_KEY: {MISTRAL_API_KEY}")
    if not MISTRAL_API_KEY:
        logger.warning("MISTRAL_API_KEY is not set")
    
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    logger.info(f"OPENAI_API_KEY: {OPENAI_API_KEY}")
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY is not set")
    
    OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
    logger.info(f"OPENROUTER_API_KEY: {OPENROUTER_API_KEY}")
    if not OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY is not set")
    
    OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY")
    logger.info(f"OLLAMA_API_KEY: {OLLAMA_API_KEY}")
    if not OLLAMA_API_KEY:
        logger.warning("OLLAMA_API_KEY is not set")
    
    OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL")
    logger.info(f"OLLAMA_BASE_URL: {OLLAMA_BASE_URL}")
    if not OLLAMA_BASE_URL:
        logger.warning("OLLAMA_BASE_URL is not set")
    
    # if not (
    #     os.environ.get("MISTRAL_API_KEY")
    #     or os.environ.get("OPENAI_API_KEY")
    #     or os.environ.get("GOOGLE_API_KEY")
    # ):
    #     raise ValueError(
    #         "MISTRAL|OPENAI|GOOGLE_API key is not set. Application cannot start."
    #     )

    if not os.environ.get("GITHUB_TOKEN"):
        raise ValueError("GITHUB_TOKEN is not set. Application cannot start.")

    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise ValueError("ENCRYPTION_KEY is not set. Application cannot start.")
    encryption_key = Fernet(key.encode())

    if not os.environ.get("WORKSPACE"):
        raise ValueError("WORKSPACE is not set. Application cannot start.")

    app = create_app(encryption_key)

    with app.app_context():
        db.create_all()

        # Get polling interval from DB or use default
        config = AgentConfig.query.first()
        interval_seconds = config.polling_interval_seconds if config else 60

        # Add the agent job to the scheduler if it doesn't exist
        if not scheduler.get_job("agent_job"):
            scheduler.add_job(
                id="agent_job",
                func=run_agent_cycle,
                trigger="interval",
                seconds=interval_seconds,
                replace_existing=True,
                args=[app, encryption_key],
            )

        # Start the scheduler
        if not scheduler.running:
            scheduler.start()

    # Note: Setting debug=True can cause the scheduler to run jobs twice.
    # Use debug=False or app.run(debug=True, use_reloader=False) in development.
    # WICHTIG: host='0.0.0.0' ist für Docker zwingend nötig
    app.run(debug=True, use_reloader=False, host="0.0.0.0", port=5000)
