import json
import os

from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, flash, redirect, render_template, request, url_for

from extensions import db, scheduler
from models import AgentConfig


def create_app(encryption_key: Fernet) -> Flask:
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

            # Create JSON from the specific fields for the selected system
            new_config_data = {}
            system_type = config.task_system_type

            if system_type == "TRELLO":
                new_config_data = {
                    "env": {
                        "TRELLO_API_KEY": request.form.get("trello_api_key"),
                        "TRELLO_TOKEN": request.form.get("trello_api_token"),
                        "TRELLO_BASE_URL": request.form.get(
                            "trello_base_url", "https://api.trello.com"
                        ),
                    },
                    "trello_todo_list_id": request.form.get("trello_board_id"),
                    "trello_readfrom_list_id": request.form.get(
                        "trello_readfrom_list_id"
                    ),
                    "trello_review_list_id": request.form.get("trello_moveto_list_id"),
                }
            elif system_type == "JIRA":
                new_config_data = {
                    "env": {
                        "JIRA_URL": os.environ.get(
                            "JIRA_URL"
                        ),  # Assuming this is set elsewhere
                        "JIRA_USERNAME": request.form.get("jira_username"),
                        "JIRA_API_TOKEN": request.form.get("jira_api_token"),
                    },
                    "jql": request.form.get("jira_jql_query"),
                }
            elif system_type == "CUSTOM":
                new_config_data = {
                    "agent_username": request.form.get("custom_username"),
                    "agent_password": request.form.get("custom_password"),
                    "target_project_id": request.form.get("custom_project_id"),
                }

            # Encrypt the JSON configuration
            json_config_str = json.dumps(new_config_data, indent=2)
            encrypted_config = encryption_key.encrypt(json_config_str.encode()).decode()
            config.system_config_json = encrypted_config

            if not config.id:
                db.session.add(config)
            db.session.commit()

            # Reschedule job
            if scheduler.get_job("agent_job"):
                scheduler.scheduler.reschedule_job(
                    "agent_job", trigger="interval", seconds=polling_interval
                )

            flash("Configuration saved successfully!", "success")
            return redirect(url_for("index"))

        # GET Request: Decrypt and parse JSON to populate form
        form_data = {}
        if config.system_config_json:
            try:
                decrypted_json = encryption_key.decrypt(
                    config.system_config_json.encode()
                ).decode()
                saved_data = json.loads(decrypted_json or "{}")

                # Populate form_data with prefixed keys for the template
                # Trello data
                form_data["trello_api_key"] = saved_data.get("env", {}).get(
                    "TRELLO_API_KEY"
                )
                form_data["trello_api_token"] = saved_data.get("env", {}).get(
                    "TRELLO_TOKEN"
                )
                form_data["trello_board_id"] = saved_data.get("trello_todo_list_id")
                form_data["trello_readfrom_list_id"] = saved_data.get(
                    "trello_readfrom_list_id"
                )
                form_data["trello_moveto_list_id"] = saved_data.get(
                    "trello_review_list_id"
                )
                form_data["trello_base_url"] = saved_data.get("env", {}).get(
                    "TRELLO_BASE_URL", "https://api.trello.com"
                )

                # Jira data
                form_data["jira_username"] = saved_data.get("env", {}).get(
                    "JIRA_USERNAME"
                )
                form_data["jira_api_token"] = saved_data.get("env", {}).get(
                    "JIRA_API_TOKEN"
                )
                form_data["jira_jql_query"] = saved_data.get("jql")

                # Custom data
                form_data["custom_username"] = saved_data.get("agent_username")
                form_data["custom_password"] = saved_data.get("agent_password")
                form_data["custom_project_id"] = saved_data.get("target_project_id")

            except (InvalidToken, TypeError, AttributeError, json.JSONDecodeError):
                flash(
                    "Could not parse or decrypt existing configuration. It may be legacy data. Re-saving will fix it.",
                    "warning",
                )

        return render_template("index.html", config=config, form_data=form_data)

    return app
