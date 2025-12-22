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
from models import AgentConfig

from agent.graph import create_workflow
from agent.llm_factory import get_llm
from agent.mcp_adapter import McpServerClient
from agent.system_mappings import SYSTEM_DEFINITIONS
from agent.utils import (
    ensure_repository_exists,
    save_graph_as_mermaid,
    save_graph_as_png,
)

logger = logging.getLogger(__name__)


async def run_agent_cycle_async(app: Flask, encryption_key: Fernet) -> None:
    with app.app_context():
        WORKSPACE = os.environ.get("WORKSPACE", "")
        logger.info(f"WORK_DIR: {WORKSPACE}")

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
        ensure_repository_exists(repo_url, WORKSPACE)

        async with AsyncExitStack() as stack:
            # --- Start ALL MCP Servers ---
            git_mcp = McpServerClient(
                command=sys.executable,
                args=["-m", "mcp_server_git", "--repository", WORKSPACE],
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

            # --- LLM and Graph Creation ---
            llm_large: BaseChatModel = get_llm(sys_config, True)
            llm_small: BaseChatModel = get_llm(sys_config, True)
            workflow: StateGraph = create_workflow(
                llm_large,
                llm_small,
                git_tools,
                task_tools,
                repo_url,
                sys_config,
            )

            # --- Graph Execution ---
            app_graph = workflow.compile()
            save_graph_as_png(app_graph)
            save_graph_as_mermaid(app_graph)
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
