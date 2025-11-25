import asyncio
import logging
import os

# LangChain / LangGraph
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from agent.llm_setup import get_llm_model

# Tools
from agent.local_tools import (
    ensure_repository_exists,
    finish_task,
    git_push_origin,
    list_files,
    log_thought,
    read_file,
    write_to_file,
)
from agent.mcp_adapter import McpGitAdapter

# Prompt
from agent.prompts import SINGLE_AGENT_SYSTEM
from agent.task_connector import TaskAppConnector

# Constants
from constants import TASK_STATE_IN_REVIEW, TASK_STATE_OPEN
from extensions import db
from models import AgentConfig

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


async def process_task_with_langgraph(task, config):
    repo_url = (
        config.github_repo_url or "https://github.com/tom-test-user/test-repo.git"
    )
    work_dir = "/app/work_dir"

    ensure_repository_exists(repo_url, work_dir)

    async with McpGitAdapter() as mcp_adapter:
        logger.info("MCP Git Server connected.")
        mcp_tools = await mcp_adapter.get_langchain_tools()

        # Alle Tools
        all_tools = mcp_tools + [
            list_files,
            read_file,
            write_to_file,
            git_push_origin,
            log_thought,
            finish_task,
        ]

        llm = get_llm_model(config)

        # --- NODE: AGENT MIT RETRY LOGIK ---
        async def agent_node(state: AgentState):
            # Basis-Prompt beim ersten Mal oder immer?
            # Wir bauen ihn hier frisch zusammen, falls wir injizieren müssen.
            # Da 'messages' die History ist, hängen wir den System Prompt virtuell davor.

            system_msg = SystemMessage(
                content=SINGLE_AGENT_SYSTEM.format(work_dir=work_dir, repo_url=repo_url)
            )
            current_messages = [system_msg] + state["messages"]

            # Start: Wir lassen ihm Freiheit ("auto")
            current_tool_choice = "auto"

            for attempt in range(3):
                try:
                    # Binden mit aktueller Strategie
                    chain = llm.bind_tools(all_tools, tool_choice=current_tool_choice)

                    # Invoke
                    response = await chain.ainvoke(current_messages)

                    # Analyse des Ergebnisses
                    has_content = bool(response.content)
                    # Bei Mistral kann tool_calls leer sein oder None
                    t_calls = getattr(response, "tool_calls", [])
                    has_tool_calls = bool(t_calls)

                    # 1. GÜLTIG: Inhalt oder Tools
                    if has_content or has_tool_calls:
                        logger.info(
                            f"\n=== AGENT RESPONSE (Attempt {attempt + 1}) ===\nContent: '{response.content}'\nTool Calls: {t_calls}\n=========================="
                        )
                        return {"messages": [response]}

                    # 2. UNGÜLTIG: Leere Antwort (Der Freeze)
                    logger.warning(
                        f"Attempt {attempt + 1}: Empty response detected. Escalating strategy..."
                    )

                    # Strategie-Wechsel: Zwang ("any") + Injection
                    current_tool_choice = "any"

                    # Wir simulieren, dass der Agent "fertig gedacht" hat.
                    current_messages.append(
                        AIMessage(
                            content="I have analyzed the files and planned the changes. I am ready to write the code."
                        )
                    )
                    # Wir geben den Befehl.
                    current_messages.append(
                        HumanMessage(
                            content="Good. STOP THINKING. Call 'write_to_file' NOW with the complete content."
                        )
                    )

                except Exception as e:
                    logger.error(f"LLM Error (Attempt {attempt + 1}): {e}")

            # Fallback nach 3 Versuchen
            logger.error("Agent stuck after 3 attempts. Forcing finish.")
            return {
                "messages": [
                    AIMessage(
                        content="Stuck.",
                        tool_calls=[
                            {
                                "name": "finish_task",
                                "args": {"summary": "Agent stuck in empty loop."},
                                "id": "call_emergency_exit",
                                "type": "tool_call",
                            }
                        ],
                    )
                ]
            }

        # --- NODE: TOOLS ---
        tool_node = ToolNode(all_tools)

        # --- GRAPH ---
        workflow = StateGraph(AgentState)
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", tool_node)

        workflow.set_entry_point("agent")

        # Entscheidung: Tools oder Ende?
        def should_continue(state):
            last_msg = state["messages"][-1]
            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                for tc in last_msg.tool_calls:
                    if tc["name"] == "finish_task":
                        return END
                return "tools"
            return END

        workflow.add_conditional_edges("agent", should_continue)
        workflow.add_edge("tools", "agent")

        app_graph = workflow.compile()

        logger.info(
            f"Task starts (Single Agent V12 - Anti-Freeze) for Task {task['id']}..."
        )

        # Startnachricht (Nur User Task, System Prompt kommt im Node dazu)
        initial_msg = [
            HumanMessage(
                content=f"Task: {task.get('title')}\nDescription: {task.get('description')}"
            )
        ]

        final_state = await app_graph.ainvoke(
            {"messages": initial_msg}, {"recursion_limit": 50}
        )

        # Output
        last_msg = final_state["messages"][-1]
        final_output = "Task finished."
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                if tc["name"] == "finish_task":
                    final_output = tc["args"].get("summary", "Done.")
        elif last_msg.content:
            final_output = str(last_msg.content)

        return final_output


def run_agent_cycle(app):
    from constants import TASK_STATE_IN_REVIEW, TASK_STATE_OPEN

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
            connector.post_comment(task["id"], "🤖 Agent V12 (Anti-Freeze) started...")

            try:
                output = asyncio.run(process_task_with_langgraph(task, config))

                limit = 4000
                if len(output) > limit:
                    short_output = output[:limit] + f"\n\n... (truncated)"
                else:
                    short_output = output

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
