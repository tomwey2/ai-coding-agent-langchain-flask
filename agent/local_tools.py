import logging
import os
import subprocess

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


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
    Use this to analyze existing code or config files.
    """
    try:
        base_dir = "/app/work_dir"
        full_path = os.path.join(base_dir, filepath)

        if not os.path.abspath(full_path).startswith(base_dir):
            return f"ERROR: Access denied."

        if not os.path.exists(full_path):
            return f"ERROR: File {filepath} does not exist."

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
    Useful to understand the project structure.
    """
    try:
        base_dir = "/app/work_dir"
        target_dir = os.path.join(base_dir, directory)

        if not os.path.abspath(target_dir).startswith(base_dir):
            return f"ERROR: Access denied."

        file_list = []
        for root, dirs, files in os.walk(target_dir):
            # .git ignorieren
            if ".git" in root:
                continue
            for file in files:
                # Relativen Pfad berechnen
                rel_path = os.path.relpath(os.path.join(root, file), base_dir)
                file_list.append(rel_path)

        return "\n".join(file_list) if file_list else "No files found."
    except Exception as e:
        return f"ERROR listing files: {str(e)}"


@tool
def write_to_file(filepath: str, content: str):
    """
    Writes content to a file.
    Use this to create new files or overwrite existing ones.
    """
    try:
        base_dir = "/app/work_dir"
        full_path = os.path.join(base_dir, filepath)

        # Security Check
        if not os.path.abspath(full_path).startswith(base_dir):
            return f"ERROR: Access denied. Cannot write outside of {base_dir}"

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {filepath}"
    except Exception as e:
        return f"ERROR writing file: {str(e)}"


@tool
def git_push_origin():
    """
    Pushes the current commits to the remote repository (origin).
    REQUIRED: Use this tool to finalize the task.
    """
    try:
        work_dir = "/app/work_dir"

        # 1. Token aus Environment holen
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            return "ERROR: GITHUB_TOKEN env variable is not set. Cannot push."

        # 2. Aktuelle URL holen
        current_url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], cwd=work_dir, text=True
        ).strip()

        # 3. URL mit Token bauen (falls noch nicht drin)
        if "https://" in current_url and "@" not in current_url:
            auth_url = current_url.replace("https://", f"https://{token}@")
            subprocess.run(
                ["git", "remote", "set-url", "origin", auth_url],
                cwd=work_dir,
                check=True,
            )

        # 4. Push ausführen
        result = subprocess.run(
            ["git", "push", "origin", "HEAD"],
            cwd=work_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return f"Push successful:\n{result.stdout}"

    except subprocess.CalledProcessError as e:
        safe_stderr = e.stderr.replace(token, "***") if token else e.stderr
        return f"Push FAILED:\n{safe_stderr}"
    except Exception as e:
        return f"ERROR during push: {str(e)}"


# --- HELPER FUNCTIONS (Nicht als @tool markiert, da für internes Setup) ---


def ensure_repository_exists(repo_url, work_dir):
    """
    Stellt sicher, dass work_dir ein valides Git-Repo ist.
    """
    if not os.path.exists(work_dir):
        os.makedirs(work_dir)

    git_dir = os.path.join(work_dir, ".git")
    if os.path.isdir(git_dir):
        logger.info("Repository already exists. Skipping clone.")
        return

    logger.info(f"Bootstrapping repository from {repo_url}...")
    try:
        # Hier ist es wichtig, dass repo_url KEIN Token enthält (fürs Logging sicherer),
        # oder wir vertrauen darauf, dass der User es sicher handhabt.
        subprocess.run(
            ["git", "clone", repo_url, "."],
            cwd=work_dir,
            check=True,
            capture_output=True,
        )
        logger.info("Clone successful.")
    except subprocess.CalledProcessError as e:
        logger.warning(f"Git Clone failed: {e}")
        logger.warning("Falling back to 'git init'.")
        subprocess.run(["git", "init"], cwd=work_dir, check=True)
