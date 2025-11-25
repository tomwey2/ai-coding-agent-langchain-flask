import logging

import requests

from constants import TASK_STATE_OPEN

# Configure basic logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class TaskAppConnectorError(Exception):
    """Custom exception for the TaskAppConnector."""

    pass


class TaskAppConnector:
    """
    A connector class to interact with the external TaskApp API,
    handling authentication and task management.
    """

    def __init__(self, base_url, username, password, project_id):
        if not all([base_url, username, password, project_id]):
            raise ValueError(
                "base_url, username, password, and project_id are required."
            )
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.project_id = project_id

        self.access_token = None
        self.user_id = None

        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get_url(self, path):
        return f"{self.base_url}{path}"

    def authenticate(self):
        """Authenticates with the TaskApp and retrieves user_id."""
        logging.info("Authenticating with TaskApp...")
        try:
            # Login to get the access token
            login_url = self._get_url("/api/auth/login")
            login_payload = {"username": self.username, "password": self.password}
            response = requests.post(login_url, json=login_payload, timeout=10)
            response.raise_for_status()

            response_data = response.json()
            logging.info(f"Login response from server: {response_data}")

            self.access_token = response_data.get("token")
            if not self.access_token:
                raise TaskAppConnectorError(
                    f"Login failed: 'token' not found in response. Server sent: {response_data}"
                )

            logging.info("Login successful. Token received.")
            self.headers["Authorization"] = f"Bearer {self.access_token}"

            # Get user info to retrieve user ID
            me_url = self._get_url("/api/auth/me")
            response = requests.get(me_url, headers=self.headers, timeout=10)
            response.raise_for_status()

            self.user_id = response.json().get("id")
            if not self.user_id:
                raise TaskAppConnectorError("Failed to get user_id from /api/auth/me.")

            logging.info(f"Authentication successful. User ID: {self.user_id}")
            return True

        except requests.exceptions.RequestException as e:
            logging.error(f"Authentication failed: {e}")
            raise TaskAppConnectorError(f"Authentication failed: {e}") from e

    def _ensure_authenticated(self):
        """Ensures that the connector is authenticated before making a request."""
        if not self.access_token or not self.user_id:
            self.authenticate()

    def get_open_tasks(self):
        """
        Fetches tasks from a specific project assigned to the authenticated user.
        Filters for 'open' status client-side.
        """
        try:
            self._ensure_authenticated()
            url = self._get_url(
                f"/api/projects/{self.project_id}/tasks?assignedToUserId={self.user_id}"
            )
            logging.info(f"Fetching tasks from {url}")
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            # DEBUG: Um die Struktur zu sehen, falls es wieder kracht
            logging.debug(f"Raw API Response: {data}")

            # HAL-JSON Parsing Logik
            all_tasks = []
            if isinstance(data, dict):
                # Prüfen auf _embedded (HAL Standard)
                if "_embedded" in data:
                    # Hier musst man ggf. schauen, ob der Key "tasks", "taskList" oder anders heißt
                    # Wir versuchen es generisch oder nehmen 'tasks' als Default
                    embedded = data["_embedded"]
                    all_tasks = embedded.get("tasks", [])
                    if not all_tasks and embedded:
                        # Fallback: Nimm den ersten Key, den wir finden, falls es nicht 'tasks' ist
                        first_key = next(iter(embedded))
                        all_tasks = embedded[first_key]
                else:
                    # Vielleicht ist es kein HAL, sondern direktes Dict? Unwahrscheinlich bei der Fehlermeldung,
                    # aber wir fangen es ab.
                    logging.warning(
                        "No '_embedded' key found in response. Checking if root is list..."
                    )
                    all_tasks = []
            elif isinstance(data, list):
                # Falls die API doch direkt eine Liste zurückgibt
                all_tasks = data

            # Filtern
            open_tasks = [
                task
                for task in all_tasks
                if isinstance(task, dict) and task.get("state", "") == TASK_STATE_OPEN
            ]

            logging.info(
                f"Found {len(open_tasks)} tasks with status '{TASK_STATE_OPEN}' (from {len(all_tasks)} total)."
            )
            return open_tasks

        except Exception as e:
            logging.error(f"Error fetching tasks: {e}")
            return []

    def post_comment(self, task_id, comment):
        """Posts a comment to a specific task."""
        if not task_id or not comment:
            logging.warning("task_id and comment cannot be empty for post_comment.")
            return False
        try:
            self._ensure_authenticated()
            url = self._get_url(f"/api/tasks/{task_id}/comments")
            payload = {"content": comment}
            logging.info(f"Posting comment to {url}: '{comment}'")
            response = requests.post(
                url, headers=self.headers, json=payload, timeout=10
            )
            response.raise_for_status()
            return True
        except (requests.exceptions.RequestException, TaskAppConnectorError) as e:
            logging.error(f"API request failed for post_comment on task {task_id}: {e}")
            return False

    def update_status(self, task_id, status):
        """Updates the status of a specific task using PATCH."""
        if not task_id or not status:
            logging.warning("task_id and status cannot be empty for update_status.")
            return False
        try:
            self._ensure_authenticated()
            url = self._get_url(f"/api/tasks/{task_id}")
            payload = {"state": status}
            logging.info(f"Updating status of task {task_id} to '{status}' at {url}")
            response = requests.put(url, headers=self.headers, json=payload, timeout=10)
            response.raise_for_status()
            return True
        except (requests.exceptions.RequestException, TaskAppConnectorError) as e:
            logging.error(
                f"API request failed for update_status on task {task_id}: {e}"
            )
            return False
