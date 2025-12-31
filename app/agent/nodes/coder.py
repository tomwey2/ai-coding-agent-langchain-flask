import logging

from agent.state import AgentState
from agent.utils import load_system_prompt
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from agent.trello_client import move_trello_card_to_named_list

logger = logging.getLogger(__name__)


def safe_truncate(value, length=100):
    # 1. Alles erst in String umwandeln (verhindert Fehler bei int/bool/list)
    s_val = str(value)
    # 2. Kürzen und "..." anhängen, wenn zu lang
    if len(s_val) > length:
        return s_val[:length] + "..."
    # 3. Zeilenumbrüche für das Log entfernen (optional, macht es lesbarer)
    return s_val.replace("\n", "\\n")


def create_coder_node(llm, tools, repo_url, agent_stack):
    sys_msg = load_system_prompt(agent_stack, "coder")

    async def coder_node(state: AgentState):
        current_messages = [SystemMessage(content=sys_msg)] + state["messages"]

        current_tool_choice = "auto"

        for attempt in range(3):
            try:
                chain = llm.bind_tools(tools, tool_choice=current_tool_choice)
                response = await chain.ainvoke(current_messages)

                has_content = bool(response.content)
                tool_calls = getattr(response, "tool_calls", []) or []
                has_tool_calls = bool(getattr(response, "tool_calls", []))

                if has_content or has_tool_calls:
                    logger.info(f"\n=== CODER RESPONSE (Attempt {attempt + 1}) ===")

                    if has_tool_calls:
                        for tc in tool_calls:
                            name = tc.get("name", "unknown")
                            args = tc.get("args", {})

                            logger.info(f"Tool Call: {name}")

                            # Hier war dein Fehler: Wir nutzen jetzt safe_truncate
                            for k, v in args.items():
                                logger.info(f" └─ {k}: {safe_truncate(v, 100)}")

                    if has_content:
                        # Auch den Content kürzen, falls er riesig ist
                        logger.info(f"Content: {safe_truncate(response.content, 100)}")

                    return {"messages": [response]}

                logger.warning(
                    f"Attempt {attempt + 1}: Empty response. Escalating strategy..."
                )
                current_tool_choice = "any"
                current_messages.append(
                    AIMessage(
                        content="I have analyzed the files and planned the changes. I am ready to write the code."
                    )
                )
                current_messages.append(
                    HumanMessage(
                        content="Good. STOP THINKING. Call 'write_to_file' NOW with the complete content."
                    )
                )

            except Exception as e:
                logger.error(f"Error in LLM call (Attempt {attempt + 1}): {e}")

        # Fallback
        logger.error("Agent stuck after 3 attempts. Hard exit.")
        return {
            "messages": [
                AIMessage(
                    content="Stuck.",
                    tool_calls=[
                        {
                            "name": "finish_task",
                            "args": {"summary": "Agent stuck."},
                            "id": "call_emergency",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        }

    return coder_node
