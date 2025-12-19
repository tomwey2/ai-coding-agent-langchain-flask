from langchain.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from agent.local_tools import (
    create_github_pr,
    finish_task,
    git_create_branch,
    git_push_origin,
    list_files,
    log_thought,
    read_file,
    run_java_command,
    write_to_file,
)
from agent.nodes.analyst import create_analyst_node
from agent.nodes.bugfixer import create_bugfixer_node
from agent.nodes.coder import create_coder_node
from agent.nodes.correction import create_correction_node
from agent.nodes.router import create_router_node
from agent.nodes.tester import create_tester_node
from agent.nodes.trello_fetch_node import create_trello_fetch_node
from agent.nodes.trello_update_node import create_trello_update_node
from agent.state import AgentState


def router_tester(state):
    messages = state["messages"]
    last_message = messages[-1]

    # Prüfen, ob Tools aufgerufen wurden
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        tool_call = last_message.tool_calls[0]

        # Wenn das Tool "TesterResult" heißt, sind wir fertig!
        if tool_call["name"] == "TesterResult":
            # Argumente parsen (pass/fail)
            result_args = tool_call["args"]
            # Entscheidung für den Graphen zurückgeben
            decision = result_args.get("result")
            if decision == "pass":
                return "pass"
            else:
                return state.get("next_step") + " failed"

        # Wenn es ein anderes Tool ist (mvn, git), ab zum ToolNode
        return "tools"

    # Fallback (sollte eigentlich nicht passieren bei bind_tools)
    return "tools"


def create_workflow(
    llm_large: BaseChatModel,
    llm_small: BaseChatModel,
    git_tools: list,
    task_tools: list,
    repo_url: str,
    sys_config: dict,
) -> StateGraph:
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
    tester_tools = git_tools + [run_java_command]

    # --- Graph Wiring ---
    workflow = StateGraph(AgentState)
    workflow.add_node("trello_fetch", create_trello_fetch_node(sys_config))
    workflow.add_node("router", create_router_node(llm_small))
    workflow.add_node("coder", create_coder_node(llm_large, coder_tools, repo_url))
    workflow.add_node(
        "bugfixer", create_bugfixer_node(llm_large, coder_tools, repo_url)
    )
    workflow.add_node(
        "analyst", create_analyst_node(llm_large, analyst_tools, repo_url)
    )
    workflow.add_node("tester", create_tester_node(llm_large, tester_tools))
    workflow.add_node("tools_coder", ToolNode(coder_tools))
    workflow.add_node("tools_analyst", ToolNode(analyst_tools))
    workflow.add_node("tools_tester", ToolNode(tester_tools))
    workflow.add_node("correction", create_correction_node())
    workflow.add_node("trello_update", create_trello_update_node(sys_config))

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
            "finish": "tester",
        },
    )

    workflow.add_conditional_edges(
        "bugfixer",
        check_agent_exit,
        {
            "tools": "tools_coder",
            "fail": "correction",
            "finish": "tester",
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

    workflow.add_conditional_edges(
        "tester",
        router_tester,
        {
            "tools": "tools_tester",
            "pass": "trello_update",
            "coder failed": "coder",
            "bugfixer failed": "bugfixer",
        },
    )

    workflow.add_edge("trello_update", END)

    workflow.add_conditional_edges(
        "correction",
        lambda state: state.get("next_step"),
        {"coder": "coder", "bugfixer": "bugfixer", "analyst": "analyst"},
    )
    workflow.add_conditional_edges(
        "tools_coder",
        lambda state: state.get("next_step"),
        {"coder": "coder", "bugfixer": "bugfixer"},
    )
    workflow.add_edge("tools_analyst", "analyst")
    workflow.add_edge("tools_tester", "tester")

    return workflow
