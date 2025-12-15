import logging

from langchain_core.messages import HumanMessage

from agent.state import AgentState
from agent.trello_adapter import get_all_trello_cards, get_all_trello_lists

logger = logging.getLogger(__name__)


def create_trello_fetch_node(sys_config: dict):
    async def trello_fetch(state: AgentState) -> dict:
        """
        Fetches tasks from the Trello board and updates the state.
        """
        logger.info(
            f"Fetching Trello lists of board id: {sys_config['trello_todo_list_id']}"
        )
        trello_lists = await get_all_trello_lists(sys_config)
        sprint_backlog_list = next(
            (data for data in trello_lists if data["name"] == "Sprint Backlog"), None
        )

        if not sprint_backlog_list:
            logger.warning("Sprint Backlog list not found")
            return {"trello_card_id": None}
        logger.info(f"Found Sprint Backlog list id: {sprint_backlog_list['id']}")

        cards = await get_all_trello_cards(sprint_backlog_list["id"], sys_config)
        if not cards:
            logger.info("No open tasks found in Sprint Backlog.")
            return {"trello_card_id": None}

        card = cards[0]
        logger.info(f"Processing card ID: {card['id']} - {card.get('name', '')}")
        return {
            "trello_card_id": card["id"],
            "messages": [
                HumanMessage(content=card.get("name", "") + "\n" + card.get("desc", ""))
            ],
        }

    return trello_fetch
