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

# Prompts
from agent.prompts import ANALYST_SYSTEM, BUGFIXER_SYSTEM, CODER_SYSTEM, ROUTER_SYSTEM
from agent.task_connector import TaskAppConnector

# Constants
from constants import TASK_STATE_IN_REVIEW, TASK_STATE_OPEN
from extensions import db
from models import AgentConfig

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    next_step: str


async def process_task_with_langgraph(task, config):
    repo_url = (
        config.github_repo_url or "https://github.com/tom-test-user/test-repo.git"
    )
    work_dir = "/app/work_dir"

    ensure_repository_exists(repo_url, work_dir)

    async with McpGitAdapter() as mcp_adapter:
        logger.info("MCP Git Server connected.")
        mcp_tools = await mcp_adapter.get_langchain_tools()

        # Tool-Sets
        read_tools = [list_files, read_file]
        write_tools = [write_to_file, git_push_origin]
        base_tools = [log_thought, finish_task]

        analyst_tools = mcp_tools + read_tools + base_tools
        coder_tools = mcp_tools + read_tools + write_tools + base_tools

        llm = get_llm_model(config)

        # --- HELPER: ROBUST INVOKE ---
        # Wir kapseln den LLM-Aufruf in eine Helper-Funktion mit Retry & Injection,
        # damit wir das nicht 3x kopieren müssen.
        async def robust_llm_invoke(chain, messages, node_name):
            for attempt in range(3):
                try:
                    response = await chain.ainvoke(messages)

                    has_content = bool(response.content)
                    t_calls = getattr(response, "tool_calls", [])
                    has_tool_calls = bool(t_calls)

                    if has_content or has_tool_calls:
                        logger.info(
                            f"\n=== {node_name} RESPONSE (Attempt {attempt + 1}) ===\nContent: '{response.content}'\nTool Calls: {t_calls}\n============================"
                        )
                        return response

                    # Empty Response Handling
                    logger.warning(
                        f"{node_name}: Empty response (Attempt {attempt + 1}). Injecting prompt..."
                    )
                    messages.append(AIMessage(content="Thinking..."))
                    messages.append(
                        HumanMessage(
                            content="ERROR: Empty response. Please USE A TOOL (log_thought, write_to_file, etc.)!"
                        )
                    )

                except Exception as e:
                    logger.error(
                        f"LLM Error in {node_name} (Attempt {attempt + 1}): {e}"
                    )

            # Fallback nach 3 Fehlern
            logger.error(f"{node_name} stuck. Returning fallback.")
            return AIMessage(
                content="Stuck.",
                tool_calls=[
                    {
                        "name": "finish_task",
                        "args": {"summary": "Agent stuck in empty loop."},
                        "id": "call_emergency",
                        "type": "tool_call",
                    }
                ],
            )

        # --- NODES ---

        async def router_node(state: AgentState):
            messages = state["messages"]
            response = await llm.ainvoke(
                [SystemMessage(content=ROUTER_SYSTEM)] + messages
            )

            # Robustes Parsing
            raw = response.content
            if isinstance(raw, list):
                txt = "".join(
                    [x if isinstance(x, str) else x.get("text", "") for x in raw]
                )
            else:
                txt = str(raw)

            decision = txt.strip().upper()
            if "BUG" in decision:
                decision = "BUGFIXER"
            elif "ANALYST" in decision:
                decision = "ANALYST"
            else:
                decision = "CODER"

            logger.info(f"Router decided: {decision}")
            return {"next_step": decision}

        async def coder_node(state: AgentState):
            sys_msg = f"{CODER_SYSTEM}\nRepo: {repo_url}\n\nREMINDER: Use 'log_thought' to plan. Use 'write_to_file' to act."
            messages = [SystemMessage(content=sys_msg)] + state["messages"]
            chain = llm.bind_tools(coder_tools, tool_choice="auto")

            response = await robust_llm_invoke(chain, messages, "CODER")
            return {"messages": [response]}

        async def bugfixer_node(state: AgentState):
            sys_msg = f"{BUGFIXER_SYSTEM}\nRepo: {repo_url}\n\nREMINDER: Use 'log_thought' to plan."
            messages = [SystemMessage(content=sys_msg)] + state["messages"]
            chain = llm.bind_tools(
                coder_tools, tool_choice="auto"
            )  # Bugfixer braucht Coder Tools

            response = await robust_llm_invoke(chain, messages, "BUGFIXER")
            return {"messages": [response]}

        async def analyst_node(state: AgentState):
            sys_msg = f"{ANALYST_SYSTEM}\nRepo: {repo_url}"
            messages = [SystemMessage(content=sys_msg)] + state["messages"]
            chain = llm.bind_tools(analyst_tools)

            # Analyst braucht oft keinen Retry Loop für Tools, da er chatten darf.
            response = await chain.ainvoke(messages)
            return {"messages": [response]}

        async def correction_node(state: AgentState):
            logger.warning("Agent chatted instead of working. Nudging...")
            return {
                "messages": [
                    HumanMessage(
                        content="That's a good plan/analysis. Now please EXECUTE it using a TOOL (write_to_file, etc.)."
                    )
                ]
            }

        tool_node = ToolNode(coder_tools)  # Shared Tool Node

        # --- GRAPH ---
        workflow = StateGraph(AgentState)
        workflow.add_node("router", router_node)
        workflow.add_node("coder", coder_node)
        workflow.add_node("bugfixer", bugfixer_node)
        workflow.add_node("analyst", analyst_node)
        workflow.add_node("tools", tool_node)
        workflow.add_node("correction", correction_node)

        workflow.set_entry_point("router")

        # Routing
        def route_after_router(state):
            step = state["next_step"]
            if step == "BUGFIXER":
                return "bugfixer"
            elif step == "ANALYST":
                return "analyst"
            return "coder"

        workflow.add_conditional_edges("router", route_after_router)

        # Exit Logic
        def check_exit(state):
            last_msg = state["messages"][-1]
            if not isinstance(last_msg, AIMessage):
                return "correction"

            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                for tool_call in last_msg.tool_calls:
                    if tool_call["name"] == "finish_task":
                        return END
                return "tools"

            # Coder/Bugfixer sollten nicht chatten -> Correction
            return "correction"

        # Analyst darf chatten -> Exit wenn keine Tools
        def check_exit_analyst(state):
            last_msg = state["messages"][-1]
            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                return "tools"
            return END

        workflow.add_conditional_edges("coder", check_exit)
        workflow.add_conditional_edges("bugfixer", check_exit)
        workflow.add_conditional_edges("analyst", check_exit_analyst)

        # Back-Routing
        def route_back(state):
            step = state.get("next_step", "CODER")
            if step == "BUGFIXER":
                return "bugfixer"
            elif step == "ANALYST":
                return "analyst"
            return "coder"

        workflow.add_conditional_edges("correction", route_back)
        workflow.add_conditional_edges("tools", route_back)

        app_graph = workflow.compile()

        logger.info(
            f"Task starts (Multi-Agent V14 - High Tokens) for Task {task['id']}..."
        )

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

        last_msg = final_state["messages"][-1]
        final_output = "Agent finished."
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                if tc["name"] == "finish_task":
                    final_output = tc["args"].get("summary", "Done.")
        elif last_msg.content:
            final_output = str(last_msg.content)

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
                task["id"], "🤖 Agent V14 (Multi-Agent + 8k Tokens) started..."
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
