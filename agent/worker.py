import asyncio
import logging
import os

# LangGraph
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from agent.llm_setup import get_llm_model

# Tools
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
from agent.mcp_adapter import McpGitAdapter
from agent.nodes.analyst import create_analyst_node
from agent.nodes.bugfixer import create_bugfixer_node
from agent.nodes.coder import create_coder_node
from agent.nodes.correction import create_correction_node

# --- IMPORTS DER NODE FACTORIES ---
from agent.nodes.router import create_router_node

# State
from agent.state import AgentState
from agent.task_connector import TaskAppConnector

# Constants
from constants import TASK_STATE_IN_REVIEW, TASK_STATE_OPEN
from extensions import db
from models import AgentConfig

logger = logging.getLogger(__name__)


async def process_task_with_langgraph(task, config):
    repo_url = (
        config.github_repo_url or "https://github.com/tom-test-user/test-repo.git"
    )
    work_dir = "/app/work_dir"

    ensure_repository_exists(repo_url, work_dir)

    async with McpGitAdapter() as mcp_adapter:
        logger.info("MCP Git Server connected.")
        mcp_tools = await mcp_adapter.get_langchain_tools()

        # 1. Tool-Sets definieren
        read_tools = [list_files, read_file]
        write_tools = [
            git_create_branch,
            write_to_file,
            git_push_origin,
            create_github_pr,
        ]
        base_tools = [log_thought, finish_task]

        analyst_tools = mcp_tools + read_tools + base_tools
        coder_tools = mcp_tools + read_tools + write_tools + base_tools

        llm = get_llm_model(config)

        # 2. Nodes erstellen (Factories aufrufen)
        # Hier übergeben wir LLM, Tools und Repo-URL an die externen Dateien
        router_node = create_router_node(llm)
        coder_node = create_coder_node(llm, coder_tools, repo_url)
        bugfixer_node = create_bugfixer_node(llm, coder_tools, repo_url)
        analyst_node = create_analyst_node(llm, analyst_tools, repo_url)
        correction_node = create_correction_node()

        # Tool Node ist generisch und braucht keine Factory
        tool_node = ToolNode(coder_tools)

        # 3. Graph Wiring
        workflow = StateGraph(AgentState)
        workflow.add_node("router", router_node)
        workflow.add_node("coder", coder_node)
        workflow.add_node("bugfixer", bugfixer_node)
        workflow.add_node("analyst", analyst_node)
        workflow.add_node("tools", tool_node)
        workflow.add_node("correction", correction_node)

        workflow.set_entry_point("router")

        # 4. Edges & Routing

        # Nach dem Router
        def route_after_router(state):
            step = state["next_step"]
            if step == "BUGFIXER":
                return "bugfixer"
            elif step == "ANALYST":
                return "analyst"
            return "coder"

        workflow.add_conditional_edges("router", route_after_router)

        # Exit-Logik für Coder/Bugfixer (Tools oder Correction)
        def check_exit(state):
            last_msg = state["messages"][-1]
            if not isinstance(last_msg, AIMessage):
                return "correction"

            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                for tool_call in last_msg.tool_calls:
                    if tool_call["name"] == "finish_task":
                        return END
                return "tools"
            return "correction"

        workflow.add_conditional_edges("coder", check_exit)
        workflow.add_conditional_edges("bugfixer", check_exit)

        # Exit-Logik für Analyst (Tools oder Ende)
        def check_exit_analyst(state):
            last_msg = state["messages"][-1]
            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                for tool_call in last_msg.tool_calls:
                    if tool_call["name"] == "finish_task":
                        return END
                return "tools"
            # Wenn Analyst Text schickt (ohne Tool), ist das OK, aber wir beenden hier sicherheitshalber,
            # damit er nicht loopt. Besser wäre, er nutzt finish_task.
            return END

        workflow.add_conditional_edges("analyst", check_exit_analyst)

        # Routing zurück zum jeweiligen Agenten
        def route_back(state):
            step = state.get("next_step", "CODER")
            if step == "BUGFIXER":
                return "bugfixer"
            elif step == "ANALYST":
                return "analyst"
            return "coder"

        workflow.add_conditional_edges("correction", route_back)
        workflow.add_conditional_edges("tools", route_back)

        # 5. Compile & Run
        app_graph = workflow.compile()
        print(app_graph.get_graph().draw_ascii())
        logger.info(f"Task starts (Multi-Agent Modular) for Task {task['id']}...")

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

        # 6. Result Extraction (Die "Smart Extraction" Logik)
        final_output = "Agent finished (No summary found)."

        # Rückwärts suchen, um den letzten 'finish_task' Aufruf zu finden
        for msg in reversed(final_state["messages"]):
            if isinstance(msg, AIMessage):
                # Fall A: Tool Call (finish_task)
                if msg.tool_calls:
                    found = False
                    for tool_call in msg.tool_calls:
                        if tool_call["name"] == "finish_task":
                            final_output = tool_call["args"].get("summary", "Done.")
                            found = True
                            break
                    if found:
                        break

                # Fall B: Reiner Text (Fallback für Analyst)
                # Wir nehmen den Text nur, wenn wir noch kein finish_task gefunden haben
                elif (
                    msg.content and final_output == "Agent finished (No summary found)."
                ):
                    final_output = str(msg.content)
                    # Wir brechen hier NICHT ab, sondern suchen weiter nach einem echten finish_task,
                    # falls der Text nur ein "Thinking" war. Aber es ist ein guter Fallback.
                    break

        return final_output


def run_agent_cycle(app):
    with app.app_context():
        try:
            config = AgentConfig.query.first()
            if not config or not config.is_active:
                return

            logger.info("Agent cycle starting...")
            connector = TaskAppConnector(
                config.task_app_base_url,
                config.agent_username,
                config.agent_password,
                config.target_project_id,
            )
            tasks = connector.get_open_tasks()
            if not tasks:
                logger.info("No open tasks found.")
                return

            task = tasks[0]
            logger.info(f"Processing Task ID: {task['id']}")
            connector.post_comment(
                task["id"], "🤖 Agent V16 (Modular & Smart) started..."
            )

            try:
                output = asyncio.run(process_task_with_langgraph(task, config))
                limit = 4000
                short_output = output[:limit] + "..." if len(output) > limit else output
                final_comment = f"🤖 Job Done.\n\nSummary:\n{short_output}"
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
            logger.error(f"Unexpected error: {e}", exc_info=True)
