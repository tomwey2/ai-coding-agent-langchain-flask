import asyncio
import json
import logging
import os
import sys
from contextlib import AsyncExitStack

from cryptography.fernet import Fernet
from flask import Flask
from langchain.chat_models import BaseChatModel
from langgraph.graph import StateGraph

from agent.graph import create_workflow
from agent.llm_factory import get_llm
from agent.local_tools import (
    create_github_pr,
    ensure_repository_exists,
    finish_task,
    git_create_branch,
    git_push_origin,
    list_files,
    log_thought,
    read_file,
    write_to_file,
)
from agent.mcp_adapter import McpServerClient
from agent.system_mappings import SYSTEM_DEFINITIONS
from models import AgentConfig

logger = logging.getLogger(__name__)


async def run_agent_cycle_async(app: Flask, encryption_key: Fernet) -> None:
    with app.app_context():
        config = AgentConfig.query.first()
        if not config or not config.is_active:
            logger.info("Agent is not active or not configured. Skipping cycle.")
            return

        logger.info(f"Starting agent cycle for system: {config.task_system_type}")
        system_def = SYSTEM_DEFINITIONS.get(config.task_system_type)
        if not system_def:
            logger.error(f"Task system '{config.task_system_type}' not defined.")
            return

        sys_config = ""
        try:
            decrypted_json = encryption_key.decrypt(
                config.system_config_json.encode()
            ).decode()
            sys_config = json.loads(decrypted_json or "{}")
        except (TypeError, AttributeError, json.JSONDecodeError):
            logger.error("Could not parse or decrypt existing configuration.")
            return

        task_env = os.environ.copy()
        task_env.update(sys_config.get("env", {}))

        repo_url: str = (
            config.github_repo_url or "https://github.com/tom-test-user/test-repo.git"
        )
        work_dir = "/app/work_dir"
        ensure_repository_exists(repo_url, work_dir)

        async with AsyncExitStack() as stack:
            # --- Start ALL MCP Servers ---
            git_mcp = McpServerClient(
                command=sys.executable,
                args=["-m", "mcp_server_git", "--repository", work_dir],
                env=os.environ.copy(),
            )
            task_mcp = McpServerClient(
                system_def["command"][0], system_def["command"][1:], env=task_env
            )

            await stack.enter_async_context(git_mcp)
            await stack.enter_async_context(task_mcp)

            git_tools = await git_mcp.get_langchain_tools()
            task_tools = await task_mcp.get_langchain_tools()
            logger.info(
                f"Loaded {len(git_tools)} Git tools and {len(task_tools)} Task tools."
            )

            # --- Tool Sets Definition ---
            read_tools = [list_files, read_file]
            write_tools = [
                git_create_branch,
                write_to_file,
                git_push_origin,
                create_github_pr,
            ]
            base_tools = [log_thought, finish_task]
            analyst_tools = read_tools + base_tools
            coder_tools = git_tools + read_tools + write_tools + base_tools

            # --- LLM and Graph Creation ---
            llm: BaseChatModel = get_llm(sys_config)
            workflow: StateGraph = create_workflow(
                llm, coder_tools, analyst_tools, repo_url, sys_config
            )

            # --- Graph Execution ---
            app_graph = workflow.compile()
            logger.info("Executing graph...")
            final_state = await app_graph.ainvoke(
                {
                    "messages": [],
                    "next_step": "",
                    "trello_card_id": None,
                    "trello_list_id": None,
                },
                {"recursion_limit": 50},
            )


def run_agent_cycle(app: Flask, encryption_key: Fernet) -> None:
    try:
        asyncio.run(run_agent_cycle_async(app, encryption_key))
    except Exception as e:
        logger.error(f"Critical error in agent cycle: {e}", exc_info=True)
