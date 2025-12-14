import logging
from typing import Dict, List

from langchain_core.messages import HumanMessage

from agent.mcp_adapter import McpServerClient
from agent.state import AgentState

logger = logging.getLogger(__name__)


def parse_trello_response(data) -> List[Dict[str, str]]:
    """
    Robustly parses a Trello API response to extract a flat list of cards.
    Handles responses that are board dictionaries or lists of cards.
    """
    logger.info(f"Trello response parser received data: {data}")

    raw_cards = []
    if isinstance(data, list):
        # Data is already a list of cards
        raw_cards = data
    elif isinstance(data, dict):
        # Check for 'cards' at the top level
        if "cards" in data and isinstance(data["cards"], list):
            raw_cards = data["cards"]
        # If not, check for nested 'lists' containing 'cards'
        elif "lists" in data and isinstance(data["lists"], list):
            all_cards = []
            for trello_list in data["lists"]:
                if isinstance(trello_list, dict) and "cards" in trello_list:
                    all_cards.extend(trello_list["cards"])
            raw_cards = all_cards

    if not raw_cards:
        return []

    # Convert the raw card objects into our canonical task format
    canonical_tasks = []
    for card in raw_cards:
        if isinstance(card, dict):
            canonical_tasks.append(card)
    return canonical_tasks


def create_trello_fetch_node(mcp_adapter: McpServerClient):
    async def trello_fetch(state: AgentState) -> dict:
        """
        Fetches tasks from the Trello board and updates the state.
        """
        logger.info("---FETCHING TRELLO TASK---")
        tool_args = {"boardId": "693bd2c8a6e57c48b0d22315"}
        board_content = await mcp_adapter.call_tool("read_board", **tool_args)
        if not board_content:
            logger.info("No board found with id=", {tool_args["boardId"]})
            return {
                "trello_card_id": None,
            }

        cards = parse_trello_response(board_content)
        if not cards:
            logger.info("No open tasks found in board.")
            return {
                "trello_card_id": None,
            }

        card = cards[0]
        logger.info(f"Processing card ID: {card['id']}")
        return {
            "trello_card_id": card.get("id"),
            "messages": [
                HumanMessage(content=card.get("name", "") + "\n" + card.get("desc", ""))
            ],
        }

    return trello_fetch
