import logging

from agent.state import AgentState
from agent.utils import load_system_prompt
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


def create_bugfixer_node(llm, tools, repo_url, agent_stack):
    sys_msg = load_system_prompt(agent_stack, "bugfixer")

    async def bugfixer_node(state: AgentState):
        current_messages = [SystemMessage(content=sys_msg)] + state["messages"]

        current_tool_choice = "auto"

        for attempt in range(3):
            try:
                chain = llm.bind_tools(tools, tool_choice=current_tool_choice)
                response = await chain.ainvoke(current_messages)

                has_content = bool(response.content)
                has_tool_calls = bool(getattr(response, "tool_calls", []))

                if has_content or has_tool_calls:
                    logger.info(
                        f"\n=== BUGFIXER RESPONSE (Attempt {attempt + 1}) ===\nContent: '{response.content}'\nTool Calls: {response.tool_calls}\n============================="
                    )
                    return {"messages": [response]}

                logger.warning(f"Attempt {attempt + 1}: Empty response. Escalating...")
                current_tool_choice = "any"
                current_messages.append(AIMessage(content="Thinking..."))
                current_messages.append(
                    HumanMessage(content="ERROR: Empty response. Use a tool!")
                )

            except Exception as e:
                logger.error(f"Error in LLM call (Attempt {attempt + 1}): {e}")

        # Fallback
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

    return bugfixer_node
