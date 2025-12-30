import logging

from agent.state import AgentState
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from agent.trello_client import move_trello_card_to_named_list

logger = logging.getLogger(__name__)

CODER_SYSTEM_PROMPT = """
You are an expert autonomous coding agent for feature implementation.
Your goal is to solve the task efficiently using the provided TOOLS.

### TOOLS:
- list_files, read_file: Analyze.
- log_thought: PLAN before you act!
- git_create_branch: Create a feature branch.
- write_to_file: Create/Edit code.
- finish_task: Mark as done.

### CODING STANDARDS (Critical):
1. CLEAN CODE: Write modular, readable code. Use meaningful names.
2. DRY: Don't Repeat Yourself. Refactor if necessary.
3. NO PLACEHOLDERS: Implement full functionality. No 'TODO' or 'pass'.
4. ROBUSTNESS: Handle basic errors/edge cases.
5. STRICT SCOPE: Execute ONLY the requirement described in the task. Do not add "extra" features, do not "fix" unrelated bugs, and do not "improve" code style unless explicitly asked.

### RULES:
1. Do NOT chat. Use 'log_thought' to explain your thinking.
2. ALWAYS create a new branch.
3. If you write code, you MUST save it ('write_to_file').

### EXECUTION PLAN:
1. [ ] Analyze (list_files/read_file).
2. [ ] Plan (log_thought).
3. [ ] BRANCH: Call 'git_create_branch'.
4. [ ] CODE: Call 'write_to_file'.
5. [ ] DONE: finish_task(summary="a short summary (max 2 sentences)")
"""


def safe_truncate(value, length=100):
    # 1. Alles erst in String umwandeln (verhindert Fehler bei int/bool/list)
    s_val = str(value)
    # 2. Kürzen und "..." anhängen, wenn zu lang
    if len(s_val) > length:
        return s_val[:length] + "..."
    # 3. Zeilenumbrüche für das Log entfernen (optional, macht es lesbarer)
    return s_val.replace("\n", "\\n")


def create_coder_node(llm, tools, repo_url, sys_config):
    async def coder_node(state: AgentState):

        # Move card to in_progress list
        card_id = state.get("trello_card_id")
        trello_progress_list = sys_config.get("trello_progress_list")
        logger.info(
            f"Moving Trello card {card_id} to '{trello_progress_list}' list"
        )
        await move_trello_card_to_named_list(card_id, trello_progress_list, sys_config)

        # Add system message
        sys_msg = f"{CODER_SYSTEM_PROMPT}\nRepo: {repo_url}\n\nREMINDER: Create a branch first!"
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
