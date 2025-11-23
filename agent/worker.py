import logging
import time

from agent.task_connector import TaskAppConnector, TaskAppConnectorError
from extensions import db
from models import AgentConfig

# Configure basic logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def run_agent_cycle(app):
    """
    This function is executed by the scheduler.
    It fetches the configuration, connects to the TaskApp, authenticates, and processes tasks.
    It requires the app context to be passed in to access the database.
    """
    with app.app_context():
        logging.info("Agent cycle starting...")

        config = AgentConfig.query.first()

        if not config:
            logging.warning(
                "Agent configuration not found in database. Skipping cycle."
            )
            return

        if not config.is_active:
            logging.info("Agent is not active. Skipping cycle.")
            return

        if not all(
            [
                config.agent_username,
                config.agent_password,
                config.target_project_id,
                config.task_app_base_url,
            ]
        ):
            logging.warning(
                "Agent configuration is incomplete (username, password, project ID, or URL is missing). Skipping cycle."
            )
            return

        logging.info(
            f"Agent is active. Polling target project {config.target_project_id}..."
        )

        try:
            connector = TaskAppConnector(
                base_url=config.task_app_base_url,
                username=config.agent_username,
                password=config.agent_password,
                project_id=config.target_project_id,
            )

            tasks = connector.get_open_tasks()

            if tasks is None:
                logging.error("Could not retrieve tasks from the API. Ending cycle.")
                return

            if not tasks:
                logging.info("No open tasks found for the configured user/project.")
                return

            # Process the first task found
            task_to_process = tasks[0]
            task_id = task_to_process.get("id")

            if not task_id:
                logging.error("Found a task without an 'id'. Skipping.")
                return

            logging.info(f"Processing task ID: {task_id}")

            # --- Simulation Step ---
            connector.post_comment(task_id, "Agent simulation started.")

            logging.info("Simulating work for 2 seconds...")
            time.sleep(2)

            connector.post_comment(task_id, "Agent simulation finished.")
            status_updated = connector.update_status(task_id, "In Review")

            if status_updated:
                logging.info(
                    f"Successfully updated task {task_id} status to 'In Review'."
                )
            else:
                logging.error(f"Failed to update status for task {task_id}.")

        except TaskAppConnectorError as e:
            logging.error(f"A critical connector error occurred: {e}. Aborting cycle.")
        except Exception as e:
            logging.error(
                f"An unexpected error occurred during the agent cycle: {e}",
                exc_info=True,
            )

        logging.info("Agent cycle finished.")
