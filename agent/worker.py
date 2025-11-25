import asyncio
import logging
import os
import shutil
import subprocess
import time

# LangChain Imports
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool

from agent.llm_setup import get_llm_model
from agent.mcp_adapter import McpGitAdapter
from agent.task_connector import TaskAppConnector

# Unsere Module
from extensions import db
from models import AgentConfig

logger = logging.getLogger(__name__)

# --- LOKALE TOOLS ---


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

        # 2. Aktuelle URL holen (z.B. https://github.com/user/repo.git)
        current_url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], cwd=work_dir, text=True
        ).strip()

        # 3. URL mit Token bauen (falls noch nicht drin)
        # Wir machen aus "https://github.com..." -> "https://TOKEN@github.com..."
        if "https://" in current_url and "@" not in current_url:
            # Wir nutzen das Token als User (GitHub akzeptiert das)
            auth_url = current_url.replace("https://", f"https://{token}@")

            # Konfiguration updaten (nur lokal im Container)
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
        # Sensible Daten aus Log entfernen (Token maskieren)
        safe_stderr = e.stderr.replace(token, "***") if token else e.stderr
        return f"Push FAILED:\n{safe_stderr}"
    except Exception as e:
        return f"ERROR during push: {str(e)}"


# --- BOOTSTRAPPING ---
def ensure_repository_exists(repo_url, work_dir):
    if not os.path.exists(work_dir):
        os.makedirs(work_dir)

    git_dir = os.path.join(work_dir, ".git")
    if os.path.isdir(git_dir):
        logger.info("Repository already exists. Skipping clone.")
        return

    logger.info(f"Bootstrapping repository from {repo_url}...")
    try:
        # Hier ist es wichtig, dass repo_url das Token enthält!
        subprocess.run(
            ["git", "clone", repo_url, "."],
            cwd=work_dir,
            check=True,
            capture_output=True,
        )
        logger.info("Clone successful.")
    except subprocess.CalledProcessError as e:
        logger.warning(f"Git Clone failed: {e}")
        logger.warning(
            "Falling back to 'git init' (Warning: Push will fail later if remote is missing)."
        )
        subprocess.run(["git", "init"], cwd=work_dir, check=True)


# ------------------------------------------------------------------------


async def process_task_with_agent(task, config):
    repo_url = (
        config.github_repo_url or "https://github.com/tom-test-user/test-repo.git"
    )
    work_dir = "/app/work_dir"

    ensure_repository_exists(repo_url, work_dir)

    async with McpGitAdapter() as mcp_adapter:
        logger.info("MCP Git Server connected.")

        mcp_tools = await mcp_adapter.get_langchain_tools()

        # HIER fügen wir das fehlende Push-Tool hinzu
        local_tools = [write_to_file, git_push_origin]

        all_tools = mcp_tools + local_tools

        llm = get_llm_model(config)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a Git Automation Bot.\n"
                    "Repo: {repo_url}\n"
                    "\n"
                    "AVAILABLE TOOLS:\n"
                    "- write_to_file: Save code.\n"
                    "- git_add: Stage files (pass as list: ['filename']).\n"
                    "- git_commit: Commit changes.\n"
                    "- git_push_origin: Push to GitHub (MANDATORY step!).\n"
                    "\n"
                    "CHECKLIST (Execute sequentially):\n"
                    "1. [ ] 'write_to_file' (Save code).\n"
                    "2. [ ] 'git_add' (Stage it).\n"
                    "3. [ ] 'git_commit' (Message: 'Update code').\n"
                    "4. [ ] 'git_push_origin' (Push to remote).\n"
                    "5. [ ] Reply with 'DONE'.\n",
                ),
                ("human", "Task: {title}\nDescription: {description}"),
                ("placeholder", "{agent_scratchpad}"),
            ]
        )

        agent = create_tool_calling_agent(llm, all_tools, prompt)

        agent_executor = AgentExecutor(
            agent=agent,
            tools=all_tools,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=15,
        )

        logger.info(f"Agent starts working on Task {task['id']}...")
        result = await agent_executor.ainvoke(
            {
                "work_dir": work_dir,
                "repo_url": repo_url,
                "task_id": task["id"],
                "title": task.get("title", ""),
                "description": task.get("description", "No description provided."),
            }
        )

        return result["output"]


def run_agent_cycle(app):
    # from main import app

    with app.app_context():
        try:
            config = AgentConfig.query.first()
            if not config or not config.is_active:
                return

            logger.info("Agent cycle starting...")

            connector = TaskAppConnector(
                base_url=config.task_app_base_url,
                username=config.agent_username,
                password=config.agent_password,
                project_id=config.target_project_id,
            )

            tasks = connector.get_open_tasks()
            if not tasks:
                logger.info("No open tasks found.")
                return

            task = tasks[0]
            logger.info(f"Processing Task ID: {task['id']}")

            connector.post_comment(
                task["id"], "🤖 Agent V2 (MCP & Mistral) started working..."
            )

            try:
                output = asyncio.run(process_task_with_agent(task, config))

                limit = 4000
                if len(output) > limit:
                    short_output = output[:limit] + f"\n\n... (truncated)"
                else:
                    short_output = output

                final_comment = (
                    f"🤖 Job Done. I updated the code.\n\nSummary:\n{short_output}"
                )
                new_status = "In Review"

            except Exception as e:
                logger.error(f"Agent failed: {e}", exc_info=True)
                final_comment = f"💥 Agent crashed: {str(e)}"
                new_status = "Open"

            connector.post_comment(task["id"], final_comment)
            if new_status == "In Review":
                connector.update_status(task["id"], new_status)

            logger.info("Agent cycle finished.")

        except Exception as e:
            logger.error(f"Unexpected error in agent cycle: {e}", exc_info=True)
