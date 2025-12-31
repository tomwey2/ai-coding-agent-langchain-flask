import logging
from typing import Literal

from agent.local_tools import report_test_result
from agent.state import AgentState
from agent.utils import load_system_prompt
from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


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


def create_tester_node(llm, tools, repo_url, agent_stack):
    sys_msg = load_system_prompt(agent_stack, "coder")
    llm_with_tools = llm.bind_tools(tools + [report_test_result])

    async def tester_node(state: AgentState):
        current_messages = [SystemMessage(content=sys_msg)] + state["messages"]

        # LLM Aufruf
        response = await llm_with_tools.ainvoke(current_messages)

        has_content = bool(response.content)
        has_tool_calls = bool(getattr(response, "tool_calls", []))

        if has_content or has_tool_calls:
            logger.info(f"\n=== TESTER RESPONSE ===\nTool Calls: {response.tool_calls}")
            logger.debug(f"\nContent: '{response.content}")
            return {"messages": [response]}

        # Wir geben die Message zurück. LangGraph kümmert sich um den Rest.
        return {"messages": [response]}

    return tester_node
