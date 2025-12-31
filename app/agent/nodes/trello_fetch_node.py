import logging

from langchain_core.messages import HumanMessage

from agent.state import AgentState
from agent.trello_client import (
    get_all_trello_cards,
    get_all_trello_lists,
    move_trello_card_to_named_list,
)


logger = logging.getLogger(__name__)


def create_trello_fetch_node(sys_config: dict):
    async def trello_fetch(state: AgentState) -> dict:
        """
        Fetches the first task from the Trello board in a specified list.
        """
        logger.info(
            f"Fetching Trello lists of board id: {sys_config['trello_board_id']}"
        )

        try:
            trello_lists = await get_all_trello_lists(sys_config)
            trello_readfrom_list = sys_config["trello_readfrom_list"]
            read_from_list = next(
                (data for data in trello_lists if data["name"] == trello_readfrom_list),
                None,
            )

            if not read_from_list:
                logger.warning(f"{trello_readfrom_list} list not found")
                return {"trello_card_id": None}

            trello_readfrom_list_id = read_from_list["id"]
            logger.info(
                f"Found {trello_readfrom_list} list id: {trello_readfrom_list_id}"
            )

            cards = await get_all_trello_cards(trello_readfrom_list_id, sys_config)
            if not cards:
                logger.info(f"No open tasks found in {trello_readfrom_list}.")
                return {"trello_card_id": None}

            card = cards[0]
            move_card_result = await move_card_to_in_progress(
                card["id"], trello_readfrom_list_id, sys_config
            )

            logger.info(f"Processing card ID: {card['id']} - {card.get('name', '')}")
            return {
                "trello_card_id": card["id"],
                "messages": [
                    HumanMessage(
                        content=card.get("name", "") + "\n" + card.get("desc", "")
                    )
                ],
                "trello_list_id": move_card_result["trello_list_id"],
                "trello_in_progress": move_card_result["trello_in_progress"],
            }
        except Exception as e:
            logger.error(f"Error fetching Trello cards: {e}")
            return {"trello_card_id": None}

    return trello_fetch

async def move_card_to_in_progress(card_id: str, current_list_id: str, sys_config: dict) -> dict:
    """
    Moves the Trello card to the in-progress list before card processing begins.
    """
    trello_progress_list = sys_config.get("trello_progress_list")
    if not trello_progress_list:
        logger.warning("trello_progress_list not configured, skipping move to in-progress list")
    else:    
        logger.info(
            f"Moving card {card_id} to in-progress list: {trello_progress_list}"
        )

        try:
            progress_list_id = await move_trello_card_to_named_list(
                card_id, trello_progress_list, sys_config
            )
            return {
                "trello_list_id": progress_list_id,
                "trello_in_progress": True,
            }
        except ValueError as exc:
            logger.warning(f"Failed to move card to in-progress list: {exc}")
        except Exception as exc:
            logger.error(f"Failed to move card to in-progress list: {exc}")

    return {"trello_list_id": current_list_id, "trello_in_progress": False}
