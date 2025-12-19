import logging

from agent.state import AgentState
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

CODER_SYSTEM_PROMPT = """
You are an expert autonomous coding agent for feature implementation.
Your goal is to solve the task efficiently using the provided TOOLS.

### TOOLS:
- list_files, read_file: Analyze.
- log_thought: PLAN before you act!
- git_create_branch: Create a feature branch.
- write_to_file: Create/Edit code.
- git_add, git_commit, git_push_origin: Save work.
- create_pull_request: Create a pull request. (MANDATORY!!)
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
4. If you have written the code, try to execute the unit tests ('run_java_command').
5. Only if you have executed the code successfully, you MUST push AND create a Pull Request before finishing.

### EXECUTION PLAN:
1. [ ] Analyze (list_files/read_file).
2. [ ] Plan (log_thought).
3. [ ] BRANCH: Call 'git_create_branch'.
4. [ ] CODE: Call 'write_to_file'.
5. [ ] TEST: Call 'run_java_command' to build and run the tests (mvn clean test). if failed, log the error and goto CODE. if successful, goto SAVE.
6. [ ] SAVE: git_add ['.'] -> git_commit -> git_push_origin.
7. [ ] PR: Call 'create_github_pr(title="...", body="...")'.
8. [ ] DONE: finish_task(summary="PR created at URL...")."""


def create_coder_node(llm, tools, repo_url):
    async def coder_node(state: AgentState):
        sys_msg = f"{CODER_SYSTEM_PROMPT}\nRepo: {repo_url}\n\nREMINDER: Create a branch first!"
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
                        f"\n=== CODER RESPONSE (Attempt {attempt + 1}) ===\nContent: '{response.content}'\nTool Calls: {response.tool_calls}\n============================"
                    )
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
