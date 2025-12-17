import logging
from typing import Dict, Literal

from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

from agent.state import AgentState

logger = logging.getLogger(__name__)

ROUTER_SYSTEM = """You are the Senior Technical Lead.
Your job is to analyze the incoming task and route it to the correct specialist.

OPTIONS:
1. 'coder': For implementing new features, creating new files, or refactoring.
2. 'bugfixer': For fixing errors, debugging, or solving issues in existing code.
3. 'analyst': For explaining code, reviewing architecture, or answering questions (NO code changes).
"""


class RouterDecision(BaseModel):
    """Classify the incoming task into the correct category."""

    role: Literal["coder", "bugfixer", "analyst"] = Field(
        ..., description="The specific role needed to solve the task."
    )


def create_router_node(llm):
    structured_llm = llm.with_structured_output(RouterDecision)

    async def router_node(state: AgentState) -> Dict[str, str]:
        messages = state["messages"]
        response = await structured_llm.ainvoke(
            [SystemMessage(content=ROUTER_SYSTEM)] + messages
        )

        logger.info(f"Router decided: {response.role}")

        # Rückgabe als String für den Graph
        return {"next_step": response.role}

    return router_node
