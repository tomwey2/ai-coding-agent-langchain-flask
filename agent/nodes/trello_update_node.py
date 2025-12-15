import logging

from agent.mcp_adapter import McpServerClient
from agent.state import AgentState
from agent.trello_adapter import (
    add_comment_to_trello_card,
    get_all_trello_lists,
    move_trello_card_to_list,
)

# Placeholder for the Trello list ID for "Done"
TARGET_LIST = "In Review"
AGENT_COMMENT = "Task completed by AI Agent"

logger = logging.getLogger(__name__)


def create_trello_update_node(sys_config: dict):
    async def trello_update(state: AgentState) -> dict:
        """
        Updates the Trello card with a comment and moves it to the "Done" list.
        """
        logger.info("---UPDATING TRELLO TASK---")
        card_id = state.get("trello_card_id")

        logger.info(
            f"Fetching Trello lists of board id: {sys_config['trello_todo_list_id']}"
        )
        trello_lists = await get_all_trello_lists(sys_config)
        target_list = next(
            (data for data in trello_lists if data["name"] == TARGET_LIST), None
        )
        if not target_list:
            logger.warning(f"{TARGET_LIST} list not found")
            return {"trello_card_id": None}

        target_list_id = target_list["id"]
        logger.info(f"Found {TARGET_LIST} list id: {target_list_id}")

        if card_id:
            await add_comment_to_trello_card(card_id, AGENT_COMMENT, sys_config)
            await move_trello_card_to_list(card_id, target_list_id, sys_config)

            return {
                "trello_list_id": target_list_id,
            }

        return {}

    return trello_update
