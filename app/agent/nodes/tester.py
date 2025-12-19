import logging
from typing import Literal

from agent.state import AgentState
from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TESTER_SYSTEM_PROMPT = """You are a QA Software Tester.
Your job is to run tests, handle version control, and report the result.

TOOLS AVAILABLE:
- run_java_command: Execute 'mvn clean test'.
- git_tools... (deine Git Tools hier)
- TesterResult: Call this tool FINALLY to report if the task is 'pass' or 'fail'.

WORKFLOW:
1. EXECUTE: Run 'mvn clean test'.
2. ANALYZE: Look at the console output.
   - IF FAIL: Call TesterResult(result='fail', summary='Error details...'). DONE.
   - IF SUCCESS: Proceed to step 3.
3. GIT: git_add -> git_commit -> git_push.
4. PR: Create the Pull Request.
5. FINISH: Call TesterResult(result='pass', summary='PR created...').

RULES:
- Do not guess the result. You MUST run the command first.
- If tests fail, DO NOT create a PR. Report fail immediately.
"""


class TesterResult(BaseModel):
    """Call this tool ONLY when you have completed the testing process."""

    result: Literal["pass", "fail"] = Field(
        ...,
        description="The final result. 'pass' if tests and PR are successful, 'fail' otherwise.",
    )
    summary: str = Field(
        ...,
        description="A short summary of what happened (e.g. 'PR created at xyz' or 'Tests failed because of NPE').",
    )


def create_tester_node(llm, tools):
    llm_with_tools = llm.bind_tools(tools + [TesterResult])

    async def tester_node(state: AgentState):
        messages = state["messages"]

        # System Prompt hinzufügen (falls noch nicht da)
        if (
            not isinstance(messages[0], SystemMessage)
            or "QA Software Tester" not in messages[0].content
        ):
            messages = [SystemMessage(content=TESTER_SYSTEM_PROMPT)] + messages

        # LLM Aufruf
        response = await llm_with_tools.ainvoke(messages)

        # Wir geben die Message zurück. LangGraph kümmert sich um den Rest.
        return {"messages": [response]}

    return tester_node
