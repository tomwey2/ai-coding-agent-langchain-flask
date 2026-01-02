import logging
from typing import Dict, Literal

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agent.state import AgentState

logger = logging.getLogger(__name__)

ROUTER_SYSTEM = """You are the Senior Technical Lead.
Your job is to analyze the incoming task and route it to the correct specialist.

OPTIONS:
1. 'coder': For implementing new features, creating new files, or refactoring.
2. 'bugfixer': For fixing errors, debugging, or solving issues in existing code.
3. 'analyst': For explaining code, reviewing architecture, or answering questions (NO code changes).

Respond ONLY with valid JSON that matches {"role":"coder"|"bugfixer"|"analyst"} with no additional text or markdown.
"""


class RouterDecision(BaseModel):
    """Classify the incoming task into the correct category."""

    role: Literal["coder", "bugfixer", "analyst"] = Field(
        ..., description="The specific role needed to solve the task."
    )


def create_router_node(llm):
    structured_llm = llm.with_structured_output(RouterDecision)

    async def router_node(state: AgentState) -> Dict[str, str]:
        base_messages = [SystemMessage(content=ROUTER_SYSTEM)] + state["messages"]
        current_messages = list(base_messages)

        for attempt in range(3):
            try:
                response = await structured_llm.ainvoke(current_messages)
                logger.info(f"Router decided: {response.role}")
                return {"next_step": response.role}
            except OutputParserException as exc:
                logger.warning(
                    "Router invalid JSON attempt %d/3: %s", attempt + 1, exc, exc_info=True
                )
                correction = HumanMessage(
                    content=(
                        "STOP. Respond ONLY with compact JSON like "
                        '{"role":"coder"} and no other text.'
                    )
                )
                current_messages.append(correction)

        logger.error("Router failed to produce valid JSON after retries.")
        raise

    return router_node
