import logging

from langchain_core.messages import AIMessage

from agent.state import AgentState
from agent.trello_client import (
    add_comment_to_trello_card,
    get_all_trello_lists,
    move_trello_card_to_list,
)

AGENT_DEFAULT_COMMENT = "Task completed by AI Agent."

logger = logging.getLogger(__name__)


def get_agent_result(messages):
    """
    Searches backward in the history for the 'finish_task' Tool-Call.
    The summary or result of the tool call is returned.
    If not found, returns the default comment.
    """
    for msg in reversed(messages):
        # Wir suchen nach einer AI-Nachricht, die Tools benutzt hat
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tool_call in msg.tool_calls:
                # Prüfen, ob es das Abschluss-Tool ist
                if tool_call["name"] == "finish_task":
                    # Das Argument 'summary' oder 'result' extrahieren
                    return tool_call["args"].get("summary", AGENT_DEFAULT_COMMENT)

    return AGENT_DEFAULT_COMMENT


def create_trello_update_node(sys_config: dict):
    async def trello_update(state: AgentState) -> dict:
        """
        Updates the Trello card with a comment and moves it to the specified list.
        """
        card_id = state.get("trello_card_id")
        if not card_id:
            logger.warning("No Trello card ID found in state")
            return {}

        logger.info(
            f"Updating Trello card {card_id} on board id: {sys_config['trello_board_id']}"
        )

        # add comment to card
        try:
            final_comment = get_agent_result(state["messages"])
            comment_text = f"**Agent Update:**\n{final_comment}"
            await add_comment_to_trello_card(card_id, comment_text, sys_config)
        except Exception as e:
            logger.error(f"Failed to add comment to Trello card: {e}")

        # move card to list
        try:
            trello_lists = await get_all_trello_lists(sys_config)
            trello_moveto_list = sys_config["trello_moveto_list"]
            moveto_list = next(
                (data for data in trello_lists if data["name"] == trello_moveto_list),
                None,
            )
            if not moveto_list:
                logger.warning(f"{trello_moveto_list} list not found")
                return {"trello_card_id": None}

            trello_moveto_list_id = moveto_list["id"]
            logger.info(f"Found {trello_moveto_list} list id: {trello_moveto_list_id}")
            await move_trello_card_to_list(card_id, trello_moveto_list_id, sys_config)

            return {
                "trello_list_id": trello_moveto_list_id,
            }
        except Exception as e:
            logger.error(f"Error moving card to list: {e}")
            return {"trello_card_id": None}

    return trello_update
