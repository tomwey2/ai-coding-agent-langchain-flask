import logging
import os
import re
import subprocess

import docker
import requests
from docker.errors import APIError, NotFound
from langchain_core.tools import tool

from agent.constants import WORK_DIR

logger = logging.getLogger(__name__)


# Initialisiert die Verbindung zur "Fernbedienung" (docker.sock)
# Das funktioniert automatisch, wenn der Socket gemountet ist.
try:
    client = docker.from_env()
except Exception as e:
    logger.warning(f"No docker connection! {e}")
    client = None

# Der Name muss exakt mit 'container_name' in der docker-compose.yml übereinstimmen
TARGET_CONTAINER = "agent-java-env"


@tool
def run_java_command(command: str):
    """
    Führt einen Shell-Befehl im Java-Container aus.
    Nutze dies für: 'mvn clean install', 'mvn test', 'java -jar ...'.
    Gib NUR den Befehl als String an.
    """
    if not client:
        return "Error: Docker client not initialized. Is the socket mounted?"

    try:
        container = client.containers.get(TARGET_CONTAINER)

        if container.status != "running":
            return f"Error: Container {TARGET_CONTAINER} is not running (Status: {container.status})."

        logger.info(f"Executing in Java-Box: {command}")

        exec_result = container.exec_run(command, workdir=WORK_DIR)

        output = exec_result.output.decode("utf-8")
        exit_code = exec_result.exit_code

        if exit_code == 0:
            return f"✅ SUCCESS:\n{output}"
        else:
            return f"❌ FAILED (Exit Code {exit_code}):\n{output}"

    except NotFound:
        return f"Error: Container '{TARGET_CONTAINER}' not found. Please start the docker-compose setup."
    except APIError as e:
        return f"Docker API Error: {str(e)}"
    except Exception as e:
        return f"System Error: {str(e)}"


# --- GIT & FILE TOOLS ---
@tool
def log_thought(thought: str):
    """
    Logs a thought or observation.
    Use this tool to 'think out loud' or plan your next step without breaking the workflow.
    """
    # Wir loggen es nur, damit wir es sehen. Für den Agenten ist es ein erfolgreicher Schritt.
    logger.info(f"🤔 AGENT THOUGHT: {thought}")
    return "Thought recorded. Proceed with the next tool."


@tool
def finish_task(summary: str):
    """
    Call this tool when you have completed the task.
    Provide a detailed summary of the changes you made.
    """
    return "Task marked as finished."


@tool
def read_file(filepath: str):
    """
    Reads the content of a file.
    """
    try:
        # FIX: Führende Slashes entfernen, um absolute Pfade zu verhindern
        clean_path = filepath.lstrip("/")
        full_path = os.path.join(WORK_DIR, clean_path)

        # Security
        if not os.path.abspath(full_path).startswith(WORK_DIR):
            return "ERROR: Access denied."

        if not os.path.exists(full_path):
            return f"ERROR: File {clean_path} does not exist. (Current dir: {os.listdir(WORK_DIR)})"

        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
            if not content:
                return "(File is empty)"
            return content
    except Exception as e:
        return f"ERROR reading file: {str(e)}"


@tool
def list_files(directory: str = "."):
    """
    Lists files in a directory (recursive).
    """
    try:
        clean_dir = directory.lstrip("/")
        target_dir = os.path.join(WORK_DIR, clean_dir)
        if not os.path.abspath(target_dir).startswith(WORK_DIR):
            return "Access denied"

        file_list = []
        for root, dirs, files in os.walk(target_dir):
            if ".git" in root:
                continue
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), WORK_DIR)
                file_list.append(rel_path)
        return "\n".join(file_list) if file_list else "No files found."
    except Exception as e:
        return str(e)


@tool
def write_to_file(filepath: str, content: str):
    """
    Writes content to a file.
    """
    try:
        # FIX: Führende Slashes entfernen
        clean_path = filepath.lstrip("/")
        full_path = os.path.join(WORK_DIR, clean_path)

        if not os.path.abspath(full_path).startswith(WORK_DIR):
            return "ERROR: Access denied."

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {clean_path}"
    except Exception as e:
        return f"ERROR writing file: {str(e)}"


@tool
def git_create_branch(branch_name: str):
    """
    Creates a new git branch and switches to it immediately.
    Example: 'feature/login-page' or 'fix/bug-123'.
    """
    try:
        # 'checkout -b' erstellt und wechselt in einem Schritt
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=WORK_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
        return f"Successfully created and switched to branch '{branch_name}'."
    except subprocess.CalledProcessError as e:
        return f"ERROR creating branch: {e.stderr}"


@tool
def git_push_origin():
    """
    Pushes the current branch to the remote repository.
    Sets the upstream automatically.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return "ERROR: GITHUB_TOKEN missing."

    try:
        # URL Auth Logic (wie vorher)
        current_url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], cwd=WORK_DIR, text=True
        ).strip()
        if "https://" in current_url and "@" not in current_url:
            auth_url = current_url.replace("https://", f"https://{token}@")
            subprocess.run(
                ["git", "remote", "set-url", "origin", auth_url],
                cwd=WORK_DIR,
                check=True,
            )

        # WICHTIG: 'git push -u origin HEAD' pusht den aktuellen Branch (egal wie er heißt)
        result = subprocess.run(
            ["git", "push", "-u", "origin", "HEAD"],
            cwd=WORK_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
        return f"Push successful:\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        safe_stderr = e.stderr.replace(token, "***") if token else e.stderr
        return f"Push FAILED:\n{safe_stderr}"
    except Exception as e:
        return f"ERROR: {str(e)}"


@tool
def create_github_pr(title: str, body: str):
    """
    Creates a Pull Request on GitHub for the current branch.
    Target is usually 'main' or 'master'.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return "ERROR: GITHUB_TOKEN missing."

    try:
        # 1. Repo-Infos aus der Remote-URL parsen
        # URL Formate: https://github.com/OWNER/REPO.git oder mit Token
        remote_url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], cwd=WORK_DIR, text=True
        ).strip()

        # Regex um Owner und Repo zu finden (ignoriert Token und .git am Ende)
        match = re.search(r"github\.com[:/](.+)/(.+?)(\.git)?$", remote_url)
        if not match:
            return f"ERROR: Could not parse Owner/Repo from URL: {remote_url}"

        owner, repo = match.group(1), match.group(2)

        # 2. Aktuellen Branch Namen holen
        current_branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=WORK_DIR, text=True
        ).strip()

        if current_branch in ["main", "master"]:
            return "ERROR: You are on main/master. Create a feature branch first!"

        # 3. API Request an GitHub senden
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        # Wir versuchen erst 'main', wenn das nicht geht 'master' als Ziel
        payload = {"title": title, "body": body, "head": current_branch, "base": "main"}

        response = requests.post(url, json=payload, headers=headers)

        # Fallback: Wenn 'main' nicht existiert (422 Error), probiere 'master'
        if response.status_code == 422:
            logger.info("Target 'main' not found, trying 'master'...")
            payload["base"] = "master"
            response = requests.post(url, json=payload, headers=headers)

        if response.status_code == 201:
            pr_url = response.json().get("html_url")
            return f"SUCCESS: Pull Request created: {pr_url}"
        else:
            return f"ERROR creating PR: {response.status_code} - {response.text}"

    except Exception as e:
        return f"ERROR: {str(e)}"
