import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.state import AgentState

logger = logging.getLogger(__name__)

BUGFIXER_PROMPT = """
You are an expert autonomous bugfixing agent for error correction.
Your goal is to solve the task efficiently using the provided TOOLS.

TOOLS:
- list_files, read_file: Analyze.
- log_thought: PLAN before you act!
- write_to_file: Create/Edit code.
- git_add, git_commit, git_push_origin: Save work.
- finish_task: Mark as done.

RULES:
1. Do NOT chat. Use 'log_thought' to explain your thinking.
2. If you write code, you MUST save it ('write_to_file').
3. 'git_push_origin' is MANDATORY before 'finish_task'.

CHECKLIST:
1. [ ] Read failing files (read_file).
2. [ ] Plan fix (log_thought).
3. [ ] Apply fix (write_to_file).
4. [ ] Save (git_add -> commit -> push).
5. [ ] Finish.
"""


def create_bugfixer_node(llm, tools, repo_url):
    async def bugfixer_node(state: AgentState):
        sys_msg = f"{BUGFIXER_PROMPT}\nRepo: {repo_url}\n\nREMINDER: Use 'log_thought' to plan."
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
