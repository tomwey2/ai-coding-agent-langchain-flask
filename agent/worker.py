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


# --- Lokale Tools (Robust gemacht) ---
@tool
def write_to_file(filepath: str, content: str):
    """
    Writes content to a file.
    Use this to create new files or overwrite existing ones with code.
    The filepath should be relative to the current working directory.
    """
    try:
        base_dir = "/app/work_dir"
        full_path = os.path.join(base_dir, filepath)

        # Sicherheits-Check (Directory Traversal verhindern)
        if not os.path.abspath(full_path).startswith(base_dir):
            return f"ERROR: Access denied. Cannot write outside of {base_dir}"

        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Successfully wrote to {filepath}"
    except Exception as e:
        return f"ERROR writing file: {str(e)}"


# --- BOOTSTRAPPING FUNKTION ---
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
        subprocess.run(
            ["git", "clone", repo_url, "."],
            cwd=work_dir,
            check=True,
            capture_output=True,
        )
        logger.info("Clone successful.")
    except subprocess.CalledProcessError as e:
        logger.warning(f"Git Clone failed: {e}")
        logger.warning("Falling back to 'git init' so the Agent can at least start.")
        subprocess.run(["git", "init"], cwd=work_dir, check=True)


# ------------------------------------------------------------------------


async def process_task_with_agent(task, config):
    repo_url = (
        config.github_repo_url or "https://github.com/tom-test-user/test-repo.git"
    )
    work_dir = "/app/work_dir"

    # 0. Bootstrapping
    ensure_repository_exists(repo_url, work_dir)

    # 1. MCP Adapter starten
    async with McpGitAdapter() as mcp_adapter:
        logger.info("MCP Git Server connected.")

        mcp_tools = await mcp_adapter.get_langchain_tools()
        local_tools = [write_to_file]
        all_tools = mcp_tools + local_tools

        llm = get_llm_model(config)

        # WICHTIG: Prompt Anpassung gegen Fehler 3230
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an expert autonomous coding agent.\n"
                    "The repository is ALREADY CLONED in: {work_dir}\n"
                    "Target Repository URL: {repo_url}\n"
                    "\n"
                    "TOOLS AVAILABLE:\n"
                    "- write_to_file: Create/Update files.\n"
                    "- git_add, git_commit, git_push: Version control.\n"
                    "\n"
                    "CRITICAL RULE: NO PARALLEL EXECUTION!\n"
                    "You MUST execute tools ONE BY ONE.\n"
                    "Do NOT call `git_add` and `git_commit` in the same turn.\n"
                    "Wait for the result of one tool before calling the next.\n"
                    "\n"
                    "WORKFLOW:\n"
                    "1. Analyze files.\n"
                    "2. Use 'write_to_file' to create/change code.\n"
                    "3. STOP and wait for result.\n"
                    "4. Use 'git_add'.\n"
                    "5. STOP and wait for result.\n"
                    "6. Use 'git_commit'.\n"
                    "7. Use 'git_push'.\n"
                    "8. Reply with 'DONE'.",
                ),
                (
                    "human",
                    "Task ID: {task_id}\nTitle: {title}\nDescription: {description}",
                ),
                ("placeholder", "{agent_scratchpad}"),
            ]
        )

        agent = create_tool_calling_agent(llm, all_tools, prompt)

        agent_executor = AgentExecutor(
            agent=agent,
            tools=all_tools,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=15,  # Schutz gegen Endlos-Schleifen
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
    # from main import app  # Local import to avoid circular dependency

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

                # Großzügiges Limit für TEXT Feld
                limit = 4000
                if len(output) > limit:
                    short_output = output[:limit] + f"\n\n... (truncated)"
                else:
                    short_output = output

                final_comment = (
                    f"🤖 Job Done. I updated the code.\n\nSummary:\n{short_output}"
                )
                new_status = "IN_REVIEW"

            except Exception as e:
                logger.error(f"Agent failed: {e}", exc_info=True)
                final_comment = f"💥 Agent crashed: {str(e)}"
                new_status = "OPEN"

            connector.post_comment(task["id"], final_comment)
            if new_status == "IN_REVIEW":
                connector.update_status(task["id"], new_status)

            logger.info("Agent cycle finished.")

        except Exception as e:
            logger.error(f"Unexpected error in agent cycle: {e}", exc_info=True)
