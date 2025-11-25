import asyncio
import logging
import os
import time

# LangChain Imports
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate

from agent.llm_setup import get_llm_model

# NEU: Import der ausgelagerten Tools
from agent.local_tools import ensure_repository_exists, git_push_origin, write_to_file
from agent.mcp_adapter import McpGitAdapter
from agent.task_connector import TaskAppConnector
from constants import TASK_STATE_IN_REVIEW, TASK_STATE_OPEN

# Unsere Module
from extensions import db
from models import AgentConfig

logger = logging.getLogger(__name__)


async def process_task_with_agent(task, config):
    repo_url = (
        config.github_repo_url or "https://github.com/tom-test-user/test-repo.git"
    )
    work_dir = "/app/work_dir"

    # Helper aus local_tools aufrufen
    ensure_repository_exists(repo_url, work_dir)

    async with McpGitAdapter() as mcp_adapter:
        logger.info("MCP Git Server connected.")

        mcp_tools = await mcp_adapter.get_langchain_tools()

        # Tools aus local_tools nutzen
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
                    "2. [ ] 'git_add' (Use ['.'] to stage everything).\n"
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
                new_status = TASK_STATE_IN_REVIEW

            except Exception as e:
                logger.error(f"Agent failed: {e}", exc_info=True)
                final_comment = f"💥 Agent crashed: {str(e)}"
                new_status = TASK_STATE_OPEN

            connector.post_comment(task["id"], final_comment)
            if new_status == TASK_STATE_IN_REVIEW:
                connector.update_status(task["id"], new_status)

            logger.info("Agent cycle finished.")

        except Exception as e:
            logger.error(f"Unexpected error in agent cycle: {e}", exc_info=True)
