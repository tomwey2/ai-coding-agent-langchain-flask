import os

from flask import Flask, flash, redirect, render_template, request, url_for

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
            config.api_token = request.form.get("api_token")
            config.polling_interval_seconds = int(
                request.form.get("polling_interval_seconds", 60)
            )
            config.is_active = "is_active" in request.form

            db.session.commit()
            flash("Configuration saved successfully!", "success")
            return redirect(url_for("index"))

        config = AgentConfig.query.first()
        if not config:
            # Create a default, temporary config for the form if none exists
            config = AgentConfig(
                task_app_base_url="http://127.0.0.1:8000/api",
                api_token="",
                polling_interval_seconds=60,
                is_active=False,
            )

        return render_template("index.html", config=config)

    # Placeholder for the actual agent worker job
    def dummy_job():
        print("Scheduler is running... (This is a dummy job)")

    with app.app_context():
        db.create_all()

        # Add the job to the scheduler if it doesn't exist
        if not scheduler.get_job("dummy_job_id"):
            # The actual job will be added later, using the config from the DB.
            # For now, we use a dummy job that runs every 10 seconds.
            scheduler.add_job(
                id="dummy_job_id",
                func=dummy_job,
                trigger="interval",
                seconds=10,
                replace_existing=True,
            )

    # Start the scheduler
    if not scheduler.running:
        scheduler.start()

    return app


# Main entry point
if __name__ == "__main__":
    app = create_app()
    # Note: Setting debug=True can cause the scheduler to run jobs twice.
    # Use debug=False or app.run(debug=True, use_reloader=False) in development.
    app.run(debug=True, use_reloader=False)
