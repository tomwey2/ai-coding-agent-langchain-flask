import logging
from typing import Dict

from langchain_core.messages import SystemMessage

from agent.state import AgentState

logger = logging.getLogger(__name__)

ROUTER_SYSTEM = """You are the Senior Technical Lead.
Your job is to analyze the incoming task and route it to the correct specialist.

OPTIONS:
1. 'CODER': For implementing new features, creating new files, or refactoring.
2. 'BUGFIXER': For fixing errors, debugging, or solving issues in existing code.
3. 'ANALYST': For explaining code, reviewing architecture, or answering questions (NO code changes).

Output ONLY the category name: CODER, BUGFIXER, or ANALYST.
"""


def create_router_node(llm):
    async def router_node(state: AgentState) -> Dict[str, str]:
        messages = state["messages"]
        response = await llm.ainvoke([SystemMessage(content=ROUTER_SYSTEM)] + messages)

        raw = response.content
        if isinstance(raw, list):
            txt = "".join([x if isinstance(x, str) else x.get("text", "") for x in raw])
        else:
            txt = str(raw)

        decision = txt.strip().upper()
        if "BUG" in decision:
            decision = "BUGFIXER"
        elif "ANALYST" in decision:
            decision = "ANALYST"
        else:
            decision = "CODER"

        logger.info(f"Router decided: {decision}")
        return {"next_step": decision}

    return router_node
