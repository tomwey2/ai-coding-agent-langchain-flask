import os

from cryptography.fernet import Fernet
from dotenv import load_dotenv

from agent.worker import run_agent_cycle
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

    if not (
        os.environ.get("MISTRAL_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    ):
        raise ValueError(
            "MISTRAL|OPENAI|GOOGLE_API key is not set. Application cannot start."
        )

    if not os.environ.get("GITHUB_TOKEN"):
        raise ValueError("GITHUB_TOKEN is not set. Application cannot start.")

    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise ValueError("ENCRYPTION_KEY is not set. Application cannot start.")
    encryption_key = Fernet(key.encode())

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
