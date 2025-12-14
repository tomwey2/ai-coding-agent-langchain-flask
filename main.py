import os

from cryptography.fernet import Fernet

from agent.worker import run_agent_cycle
from extensions import db, scheduler
from models import AgentConfig
from webapp import create_app

# Main entry point
if __name__ == "__main__":
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
