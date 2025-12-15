import logging

from langchain_core.messages import HumanMessage

from agent.state import AgentState
from agent.trello_client import get_all_trello_cards, get_all_trello_lists

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
            logger.info(f"Processing card ID: {card['id']} - {card.get('name', '')}")
            return {
                "trello_card_id": card["id"],
                "messages": [
                    HumanMessage(
                        content=card.get("name", "") + "\n" + card.get("desc", "")
                    )
                ],
            }
        except Exception as e:
            logger.error(f"Error fetching Trello cards: {e}")
            return {"trello_card_id": None}

    return trello_fetch
