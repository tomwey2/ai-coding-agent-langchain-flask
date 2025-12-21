from langchain.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

# Imports deiner Tools
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

# WICHTIG: TesterResult muss importiert werden, falls es als Klasse existiert,
# oder wir gehen davon aus, dass es dynamisch im Node erzeugt wird.
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
    """
    Entscheidet nach dem Tester-LLM:
    - Wurde TesterResult aufgerufen? -> Auswerten (pass/fail).
    - Anderes Tool (git, mvn)? -> Ab zum ToolNode.
    """
    messages = state["messages"]
    last_message = messages[-1]

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        tool_call = last_message.tool_calls[0]

        if tool_call["name"] == "TesterResult":
            result_args = tool_call["args"]
            decision = result_args.get("result")

            if decision == "pass":
                return "pass"
            else:
                # Gibt z.B. "coder failed" oder "bugfixer failed" zurück
                return state.get("next_step") + " failed"

        return "tools"

    return "tools"


def check_agent_exit(state: AgentState) -> str:
    """
    Prüft nach Coder/Bugfixer/Analyst:
    - Hat das LLM ein Tool gewählt? -> tools
    - Hat es Text gelabert? -> fail (Korrektur)
    """
    last_msg = state["messages"][-1]

    if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return "fail"

    # Wir führen ALLE Tools aus, auch finish_task
    return "tools"


def route_after_tools_coder(state: AgentState) -> str:
    """
    Entscheidet NACHDEM die Tools für Coder/Bugfixer liefen:
    - War das letzte Tool 'finish_task'? -> Weiter zum Tester.
    - Sonst -> Loop zurück zum aktuellen Agenten (Coder oder Bugfixer).
    """
    messages = state["messages"]

    # 1. Bestimmen, wer gerade dran war (Coder oder Bugfixer)
    current_agent = state.get("next_step", "coder")

    # 2. Prüfen auf finish_task
    if len(messages) >= 2:
        ai_msg = messages[-2]  # Die Nachricht VOR dem Tool-Output
        if isinstance(ai_msg, AIMessage) and ai_msg.tool_calls:
            # Wir prüfen den ersten Call (oder iterieren, falls nötig)
            if ai_msg.tool_calls[0]["name"] == "finish_task":
                return "finish"

    # 3. Kein Finish? Dann Loop zurück zum Agenten
    return current_agent


def route_after_tools_analyst(state: AgentState) -> str:
    """
    Spezial-Router für Analyst:
    - finish_task -> trello_update (Nicht Tester!)
    - Sonst -> Loop zurück zum Analyst
    """
    messages = state["messages"]

    if len(messages) >= 2:
        ai_msg = messages[-2]
        if isinstance(ai_msg, AIMessage) and ai_msg.tool_calls:
            if ai_msg.tool_calls[0]["name"] == "finish_task":
                return "finish"  # Geht zu trello_update

    return "analyst"


def create_workflow(
    llm_large: BaseChatModel,
    llm_small: BaseChatModel,
    git_tools: list,
    task_tools: list,
    repo_url: str,
    sys_config: dict,
) -> StateGraph:
    # --- Tool Sets ---
    base_tools = [log_thought, finish_task]
    read_tools = [list_files, read_file]
    write_tools = [write_to_file]

    # Git Tools lokal definieren
    git_local_tools = [
        git_create_branch,
        git_push_origin,
        create_github_pr,
    ]

    analyst_tools = read_tools + base_tools
    coder_tools = read_tools + write_tools + base_tools
    # Tester braucht Java + Git
    tester_tools = git_tools + git_local_tools + [run_java_command]

    # --- Graph Nodes ---
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

    # Tool Nodes
    workflow.add_node("tools_coder", ToolNode(coder_tools))
    workflow.add_node("tools_analyst", ToolNode(analyst_tools))
    workflow.add_node("tools_tester", ToolNode(tester_tools))

    workflow.add_node("correction", create_correction_node())
    workflow.add_node("trello_update", create_trello_update_node(sys_config))

    workflow.set_entry_point("trello_fetch")

    # --- Edges ---

    # 1. Start -> Router
    workflow.add_conditional_edges(
        "trello_fetch",
        lambda state: "router" if state.get("trello_card_id") else END,
        {END: END, "router": "router"},
    )

    # 2. Router -> Spezialisten: Coder | Bugfixer | Analyst
    workflow.add_conditional_edges(
        "router",
        lambda state: state.get("next_step", "coder"),
        {"coder": "coder", "bugfixer": "bugfixer", "analyst": "analyst"},
    )

    # 3. Coder -> Tools | Correction
    workflow.add_conditional_edges(
        "coder",
        check_agent_exit,
        {
            "tools": "tools_coder",
            "fail": "correction",
        },
    )

    # 4. Bugfixer -> Tools | Correction
    workflow.add_conditional_edges(
        "bugfixer",
        check_agent_exit,
        {
            "tools": "tools_coder",
            "fail": "correction",
        },
    )

    # 5. Analyst -> Tools | Correction
    workflow.add_conditional_edges(
        "analyst",
        check_agent_exit,
        {
            "tools": "tools_analyst",
            "fail": "correction",
        },
    )

    # 6. ROUTING NACH DEN TOOLS

    # Für Coder & Bugfixer:
    # Prüft auf finish_task -> Tester. Sonst -> Zurück zum Agenten (Loop).
    workflow.add_conditional_edges(
        "tools_coder",
        route_after_tools_coder,
        {
            "coder": "coder",  # Loop
            "bugfixer": "bugfixer",  # Loop
            "finish": "tester",  # Exit zu Tester
        },
    )

    # Für Analyst:
    # Prüft auf finish_task -> Trello Update. Sonst -> Loop.
    workflow.add_conditional_edges(
        "tools_analyst",
        route_after_tools_analyst,
        {"analyst": "analyst", "finish": "trello_update"},
    )

    # 7. Tester Logik
    workflow.add_conditional_edges(
        "tester",
        router_tester,
        {
            "tools": "tools_tester",  # git/java tools ausführen
            "pass": "trello_update",  # Testergebnis grün
            "coder failed": "coder",  # Zurück zur Arbeit
            "bugfixer failed": "bugfixer",  # Zurück zur Arbeit
        },
    )

    # Tester Loop zurück
    workflow.add_edge("tools_tester", "tester")

    # 8. Correction & Ende
    workflow.add_conditional_edges(
        "correction",
        lambda state: state.get("next_step"),
        {"coder": "coder", "bugfixer": "bugfixer", "analyst": "analyst"},
    )

    workflow.add_edge("trello_update", END)

    return workflow
