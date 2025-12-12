import json
import os

from flask import Flask, flash, redirect, render_template, request, url_for

from extensions import db, scheduler
from models import AgentConfig


def create_app():
    """Create and configure an instance of the Flask application."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object("config")

    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    db.init_app(app)
    scheduler.init_app(app)

    @app.route("/", methods=["GET", "POST"])
    def index():
        config = AgentConfig.query.first()
        if not config:
            config = AgentConfig(task_system_type="TRELLO", system_config_json="{}")

        if request.method == "POST":
            # Update generic fields
            config.task_system_type = request.form.get("task_system_type")
            config.repo_type = request.form.get("repo_type")
            config.github_repo_url = request.form.get("github_repo_url")
            config.is_active = "is_active" in request.form
            try:
                polling_interval = int(request.form.get("polling_interval_seconds", 60))
                config.polling_interval_seconds = polling_interval
            except (ValueError, TypeError):
                flash("Invalid polling interval. Please enter a number.", "danger")
                polling_interval = 60  # Fallback

            # Create system_config_json from individual fields
            api_key = request.form.get("api_key")
            api_token = request.form.get("api_token")
            project_id = request.form.get("project_id")

            new_config_data = {}
            system_type = config.task_system_type

            if system_type == "TRELLO":
                new_config_data = {
                    "env": {
                        "TRELLO_API_KEY": api_key,
                        "TRELLO_TOKEN": api_token,
                    },
                    "trello_todo_list_id": project_id,
                    "trello_review_list_id": "",  # Placeholder for future extension
                }
            elif system_type == "CUSTOM":
                new_config_data = {
                    "agent_username": api_key,
                    "agent_password": api_token,
                    "target_project_id": project_id,
                }
            # Add other mappings here for JIRA etc.

            config.system_config_json = json.dumps(new_config_data, indent=2)

            if not config.id:
                db.session.add(config)
            db.session.commit()

            if scheduler.get_job("agent_job"):
                scheduler.scheduler.reschedule_job(
                    "agent_job", trigger="interval", seconds=polling_interval
                )

            flash("Configuration saved successfully!", "success")
            return redirect(url_for("index"))

        # GET Request: Parse JSON to populate form
        form_data = {}
        try:
            if config.system_config_json:
                saved_data = json.loads(config.system_config_json)
                if config.task_system_type == "TRELLO":
                    form_data["api_key"] = saved_data.get("env", {}).get(
                        "TRELLO_API_KEY"
                    )
                    form_data["api_token"] = saved_data.get("env", {}).get(
                        "TRELLO_TOKEN"
                    )
                    form_data["project_id"] = saved_data.get("trello_todo_list_id")
                elif config.task_system_type == "CUSTOM":
                    form_data["api_key"] = saved_data.get("agent_username")
                    form_data["api_token"] = saved_data.get("agent_password")
                    form_data["project_id"] = saved_data.get("target_project_id")

        except json.JSONDecodeError:
            flash("Could not parse system configuration JSON.", "warning")

        return render_template("index.html", config=config, form_data=form_data)

    return app
