from langchain.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from agent.nodes.analyst import create_analyst_node
from agent.nodes.bugfixer import create_bugfixer_node
from agent.nodes.coder import create_coder_node
from agent.nodes.correction import create_correction_node
from agent.nodes.router import create_router_node
from agent.nodes.trello_fetch_node import create_trello_fetch_node
from agent.nodes.trello_update_node import create_trello_update_node
from agent.state import AgentState


def create_workflow(
    llm: BaseChatModel,
    coder_tools: list,
    analyst_tools: list,
    repo_url: str,
    sys_config: dict,
) -> StateGraph:
    # --- Node Creation ---
    router_node = create_router_node(llm)
    coder_node = create_coder_node(llm, coder_tools, repo_url)
    bugfixer_node = create_bugfixer_node(llm, coder_tools, repo_url)
    analyst_node = create_analyst_node(llm, analyst_tools, repo_url)
    correction_node = create_correction_node()
    tools_coder_node = ToolNode(coder_tools)
    tools_analyst_node = ToolNode(analyst_tools)
    trello_fetch_node = create_trello_fetch_node(sys_config)
    trello_update_node = create_trello_update_node(sys_config)

    # --- Graph Wiring ---
    workflow = StateGraph(AgentState)
    workflow.add_node("trello_fetch", trello_fetch_node)
    workflow.add_node("router", router_node)
    workflow.add_node("coder", coder_node)
    workflow.add_node("bugfixer", bugfixer_node)
    workflow.add_node("analyst", analyst_node)
    workflow.add_node("tools_coder", tools_coder_node)
    workflow.add_node("tools_analyst", tools_analyst_node)
    workflow.add_node("correction", correction_node)
    workflow.add_node("trello_update", trello_update_node)

    workflow.set_entry_point("trello_fetch")

    def after_trello_fetch(state: AgentState) -> str:
        return "router" if state.get("trello_card_id") else END

    workflow.add_conditional_edges(
        "trello_fetch",
        after_trello_fetch,
        {END: END, "router": "router"},
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

    def route_coder_exit(state: AgentState) -> str:
        last_msg = state["messages"][-1]
        if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
            return "correction"
        if any(call["name"] == "finish_task" for call in last_msg.tool_calls):
            return "trello_update"
        return "tools_coder"

    def route_analyst_exit(state: AgentState) -> str:
        last_msg = state["messages"][-1]
        if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
            return "correction"
        if any(call["name"] == "finish_task" for call in last_msg.tool_calls):
            return "trello_update"
        return "tools_analyst"

    workflow.add_conditional_edges(
        "coder",
        route_coder_exit,
        {
            "tools_coder": "tools_coder",
            "correction": "correction",
            "trello_update": "trello_update",
        },
    )
    workflow.add_conditional_edges(
        "bugfixer",
        route_coder_exit,
        {
            "tools_coder": "tools_coder",
            "correction": "correction",
            "trello_update": "trello_update",
        },
    )
    workflow.add_conditional_edges(
        "analyst",
        route_analyst_exit,
        {
            "tools_analyst": "tools_analyst",
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
        "tools_coder",
        route_back,
        {"coder": "coder", "bugfixer": "bugfixer"},
    )
    workflow.add_conditional_edges(
        "tools_analyst",
        route_back,
        {"analyst": "analyst"},
    )

    return workflow
