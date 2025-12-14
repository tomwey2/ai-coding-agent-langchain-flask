import asyncio
import json
import logging
import os
import sys
from contextlib import AsyncExitStack

from cryptography.fernet import Fernet
from flask import Flask
from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from agent.llm_setup import get_llm_model
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
from agent.nodes.analyst import create_analyst_node
from agent.nodes.bugfixer import create_bugfixer_node
from agent.nodes.coder import create_coder_node
from agent.nodes.correction import create_correction_node
from agent.nodes.router import create_router_node
from agent.nodes.trello_fetch_node import create_trello_fetch_node
from agent.nodes.trello_update_node import create_trello_update_node
from agent.state import AgentState
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

        repo_url = (
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

            all_mcp_tools = git_tools + task_tools
            # --- Tool Sets Definition ---
            read_tools = [list_files, read_file]
            write_tools = [
                git_create_branch,
                write_to_file,
                git_push_origin,
                create_github_pr,
            ]
            base_tools = [log_thought, finish_task]

            analyst_tools = all_mcp_tools + read_tools + base_tools
            coder_tools = all_mcp_tools + read_tools + write_tools + base_tools

            llm = get_llm_model(config)

            # --- Node Creation ---
            router_node = create_router_node(llm)
            coder_node = create_coder_node(llm, coder_tools, repo_url)
            bugfixer_node = create_bugfixer_node(llm, coder_tools, repo_url)
            analyst_node = create_analyst_node(llm, analyst_tools, repo_url)
            correction_node = create_correction_node()
            tool_node = ToolNode(coder_tools)
            trello_fetch_node = create_trello_fetch_node(sys_config)
            trello_update_node = create_trello_update_node(task_mcp)

            # --- Graph Wiring ---
            workflow = StateGraph(AgentState)
            workflow.add_node("trello_fetch", trello_fetch_node)
            workflow.add_node("router", router_node)
            workflow.add_node("coder", coder_node)
            workflow.add_node("bugfixer", bugfixer_node)
            workflow.add_node("analyst", analyst_node)
            workflow.add_node("tools", tool_node)
            workflow.add_node("correction", correction_node)
            workflow.add_node("trello_update", trello_update_node)

            workflow.set_entry_point("trello_fetch")

            def after_trello_fetch(state: AgentState) -> str:
                return "trello_update" if state.get("trello_card_id") else END

            workflow.add_conditional_edges(
                "trello_fetch",
                after_trello_fetch,
                {END: END, "trello_update": "trello_update"},
            )

            def route_after_router(state: AgentState) -> str:
                step = state.get("next_step", "coder").lower()
                if step in ["coder", "bugfixer", "analyst"]:
                    return step
                return "coder"

            workflow.add_conditional_edges(
                "router",
                route_after_router,
                {"coder": "coder", "bugfixer": "bugfixer", "analyst": "analyst"},
            )

            def check_exit(state: AgentState) -> str:
                last_msg = state["messages"][-1]
                if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
                    return "correction"
                if any(call["name"] == "finish_task" for call in last_msg.tool_calls):
                    return "trello_update"
                return "tools"

            workflow.add_conditional_edges(
                "coder",
                check_exit,
                {
                    "tools": "tools",
                    "correction": "correction",
                    "trello_update": "trello_update",
                },
            )
            workflow.add_conditional_edges(
                "bugfixer",
                check_exit,
                {
                    "tools": "tools",
                    "correction": "correction",
                    "trello_update": "trello_update",
                },
            )
            workflow.add_conditional_edges(
                "analyst",
                check_exit,
                {
                    "tools": "tools",
                    "correction": "correction",
                    "trello_update": "trello_update",
                },
            )
            workflow.add_edge("trello_update", END)

            def route_back(state: AgentState) -> str:
                return state.get("next_step", "CODER").lower()

            workflow.add_conditional_edges(
                "correction",
                route_back,
                {"coder": "coder", "bugfixer": "bugfixer", "analyst": "analyst"},
            )
            workflow.add_conditional_edges(
                "tools",
                route_back,
                {"coder": "coder", "bugfixer": "bugfixer", "analyst": "analyst"},
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
