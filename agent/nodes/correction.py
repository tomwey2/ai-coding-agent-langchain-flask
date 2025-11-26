import logging

from langchain_core.messages import HumanMessage

from agent.state import AgentState

logger = logging.getLogger(__name__)


def create_correction_node():
    async def correction_node(state: AgentState):
        logger.warning(
            "Agent generated text instead of tool call. Injecting correction message."
        )
        return {
            "messages": [
                HumanMessage(
                    content="ERROR: You responded with text but NO tool call. You MUST call a tool (e.g. log_thought, write_to_file)."
                )
            ]
        }

    return correction_node
