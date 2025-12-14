import logging

from agent.mcp_adapter import McpServerClient
from agent.state import AgentState

# Placeholder for the Trello list ID for "Sprint Backlog"
SPRINT_BACKLOG_LIST_ID = "693bd2c8a6e57c48b0d22311"
# Placeholder for the Trello list ID for "Done"
DONE_LIST_ID = "693bd2c8a6e57c48b0d22314"

logger = logging.getLogger(__name__)


def create_trello_update_node(mcp_adapter: McpServerClient):
    async def trello_update(state: AgentState) -> dict:
        """
        Updates the Trello card with a comment and moves it to the "Done" list.
        """
        logger.info("---UPDATING TRELLO TASK---")
        card_id = state.get("trello_card_id")

        if card_id:
            tool_args = {"cardId": card_id, "text": "Task completed by AI Agent"}
            await mcp_adapter.call_tool(tool_name="add_comment", **tool_args)
            tool_args = {"cardId": card_id, "listId": DONE_LIST_ID}
            await mcp_adapter.call_tool(tool_name="move_card", **tool_args)

            logger.info(f"---TASK {card_id} COMPLETED---")
            return {
                "trello_list_id": DONE_LIST_ID,
            }

        return {}

    return trello_update
