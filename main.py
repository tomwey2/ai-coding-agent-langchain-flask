import os

from flask import Flask, flash, redirect, render_template, request, url_for

from agent.worker import run_agent_cycle
from extensions import db, scheduler
from models import AgentConfig


def create_app():
    """Create and configure an instance of the Flask application."""
    app = Flask(__name__, instance_relative_config=True)

    # Load configuration from config.py
    app.config.from_object("config")

    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # Initialize extensions
    db.init_app(app)
    scheduler.init_app(app)

    @app.route("/", methods=["GET", "POST"])
    def index():
        if request.method == "POST":
            config = AgentConfig.query.first()
            if not config:
                config = AgentConfig()
                db.session.add(config)

            config.task_app_base_url = request.form.get("task_app_base_url")
            config.agent_username = request.form.get("agent_username")
            config.agent_password = request.form.get("agent_password")
            config.target_project_id = request.form.get("target_project_id")
            polling_interval = int(request.form.get("polling_interval_seconds", 60))
            config.polling_interval_seconds = polling_interval
            config.is_active = "is_active" in request.form

            db.session.commit()

            # Reschedule job if interval changed
            if scheduler.get_job("agent_job"):
                scheduler.reschedule_job(
                    "agent_job", trigger="interval", seconds=polling_interval
                )

            flash("Configuration saved successfully!", "success")
            return redirect(url_for("index"))

        config = AgentConfig.query.first()
        if not config:
            # Create a default, temporary config for the form if none exists
            config = AgentConfig(
                task_app_base_url="http://127.0.0.1:8000/api",
                agent_username="",
                agent_password="",
                target_project_id="",
                polling_interval_seconds=60,
                is_active=False,
            )

        return render_template("index.html", config=config)

    return app


# Main entry point
if __name__ == "__main__":
    app = create_app()

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
                args=[app],
            )

        # Start the scheduler
        if not scheduler.running:
            scheduler.start()

    # Note: Setting debug=True can cause the scheduler to run jobs twice.
    # Use debug=False or app.run(debug=True, use_reloader=False) in development.
    # WICHTIG: host='0.0.0.0' ist für Docker zwingend nötig
    app.run(debug=True, use_reloader=False, host="0.0.0.0", port=5000)
