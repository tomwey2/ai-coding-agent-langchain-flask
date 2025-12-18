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
    llm_large: BaseChatModel,
    llm_small: BaseChatModel,
    coder_tools: list,
    analyst_tools: list,
    repo_url: str,
    sys_config: dict,
) -> StateGraph:
    # --- Node Creation ---
    router_node = create_router_node(llm_small)
    coder_node = create_coder_node(llm_large, coder_tools, repo_url)
    bugfixer_node = create_bugfixer_node(llm_large, coder_tools, repo_url)
    analyst_node = create_analyst_node(llm_large, analyst_tools, repo_url)
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

    workflow.add_conditional_edges(
        "trello_fetch",
        # if there is a card go to router otherwise end
        lambda state: "router" if state.get("trello_card_id") else END,
        {END: END, "router": "router"},
    )

    workflow.add_conditional_edges(
        "router",
        lambda state: state.get("next_step", "coder"),
        {"coder": "coder", "bugfixer": "bugfixer", "analyst": "analyst"},
    )

    def check_agent_exit(state: AgentState) -> str:
        last_msg = state["messages"][-1]
        if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
            return "fail"
        if any(call["name"] == "finish_task" for call in last_msg.tool_calls):
            return "finish"
        return "tools"

    workflow.add_conditional_edges(
        "coder",
        check_agent_exit,
        {
            "tools": "tools_coder",
            "fail": "correction",
            "finish": "trello_update",
        },
    )
    workflow.add_conditional_edges(
        "bugfixer",
        check_agent_exit,
        {
            "tools": "tools_coder",
            "fail": "correction",
            "finish": "trello_update",
        },
    )
    workflow.add_conditional_edges(
        "analyst",
        check_agent_exit,
        {
            "tools": "tools_analyst",
            "fail": "correction",
            "finish": "trello_update",
        },
    )
    workflow.add_edge("trello_update", END)

    workflow.add_conditional_edges(
        "correction",
        lambda state: state.get("next_step", "coder"),
        {"coder": "coder", "bugfixer": "bugfixer", "analyst": "analyst"},
    )
    workflow.add_conditional_edges(
        "tools_coder",
        lambda state: state.get("next_step", "coder"),
        {"coder": "coder", "bugfixer": "bugfixer"},
    )
    workflow.add_conditional_edges(
        "tools_analyst",
        lambda state: state.get("next_step", "coder"),
        {"analyst": "analyst"},
    )

    return workflow
