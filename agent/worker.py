import asyncio
import json
import logging
import os
import sys
from contextlib import AsyncExitStack
from typing import Any, Dict, List

from cryptography.fernet import Fernet
from flask import Flask
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool
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
from agent.state import AgentState
from agent.system_mappings import SYSTEM_DEFINITIONS
from models import AgentConfig

logger = logging.getLogger(__name__)


async def process_task_with_langgraph(
    task: Dict[str, Any],
    config: AgentConfig,
    git_tools: List[BaseTool],
    task_tools: List[BaseTool],
) -> str:
    repo_url = (
        config.github_repo_url or "https://github.com/tom-test-user/test-repo.git"
    )
    work_dir = "/app/work_dir"
    ensure_repository_exists(repo_url, work_dir)

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

    # --- Graph Wiring ---
    workflow = StateGraph(AgentState)
    workflow.add_node("router", router_node)
    workflow.add_node("coder", coder_node)
    workflow.add_node("bugfixer", bugfixer_node)
    workflow.add_node("analyst", analyst_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("correction", correction_node)
    workflow.set_entry_point("router")

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
            return END
        return "tools"

    workflow.add_conditional_edges(
        "coder", check_exit, {"tools": "tools", "correction": "correction", END: END}
    )
    workflow.add_conditional_edges(
        "bugfixer",
        check_exit,
        {"tools": "tools", "correction": "correction", END: END},
    )
    workflow.add_conditional_edges("analyst", check_exit, {"tools": "tools", END: END})

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
    logger.info(f"Executing graph for task: {task['id']}...")
    final_state = await app_graph.ainvoke(
        {
            "messages": [
                HumanMessage(
                    content=f"Task: {task.get('title')}\nDescription: {task.get('description')}"
                )
            ],
            "next_step": "",
        },
        {"recursion_limit": 50},
    )

    for msg in reversed(final_state["messages"]):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                if call["name"] == "finish_task":
                    return call["args"].get("summary", "Task completed.")
    return "Agent finished without a summary."


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

        work_dir = "/app/work_dir"
        ensure_repository_exists(config.github_repo_url, work_dir)

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

            # --- Poll for Tasks ---
            polling_tool_name = system_def["polling_tool"]
            polling_args = {
                k: v.format(**sys_config) for k, v in system_def["polling_args"].items()
            }
            task = None
            try:
                raw_board = await task_mcp.call_tool(polling_tool_name, **polling_args)
                if not raw_board:
                    logger.info("No open tasks found.")
                    return

                tasks = system_def["response_parser"](raw_board)
                if not tasks:
                    logger.info("No open tasks found in board.")
                    return

                task = tasks[0]
                logger.info(f"Processing Task ID: {task['id']}")

                await task_mcp.call_tool(
                    "add_comment",
                    cardId=task["id"],
                    text="🤖 Agent processing started...",
                )

                output = await process_task_with_langgraph(
                    task, config, git_tools, task_tools
                )
                final_comment = f"🤖 Job Done.\n\nSummary:\n{output}"

                trello_moveto_list_id = sys_config.get("trello_moveto_list_id")
                if trello_moveto_list_id:
                    await task_mcp.call_tool(
                        "move_card_",
                        cardId=task["id"],
                        listId=trello_moveto_list_id,
                    )
            except Exception as e:
                logger.error(
                    f"Agent failed on task {task.get('id', 'N/A') if task else 'N/A'}: {e}",
                    exc_info=True,
                )
                final_comment = f"💥 Agent crashed: {e}"
                # Try to comment on failure
                if task and task.get("id"):
                    await task_mcp.call_tool(
                        "add_comment", cardId=task["id"], text=final_comment
                    )

            else:
                if task and task.get("id"):
                    await task_mcp.call_tool(
                        "add_comment", cardId=task["id"], text=final_comment
                    )


def run_agent_cycle(app: Flask, encryption_key: Fernet) -> None:
    try:
        asyncio.run(run_agent_cycle_async(app, encryption_key))
    except Exception as e:
        logger.error(f"Critical error in agent cycle: {e}", exc_info=True)
