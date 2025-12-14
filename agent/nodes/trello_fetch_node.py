import logging

import httpx
from langchain_core.messages import HumanMessage

from agent.state import AgentState

logger = logging.getLogger(__name__)


async def get_all_trello_lists(sys_config: dict) -> list[dict]:
    env = sys_config.get("env")
    if not env:
        raise ValueError("Environment not found in sys_config")

    url = (
        f"https://api.trello.com/1/boards/{sys_config.get('trello_todo_list_id')}/lists"
    )
    headers = {"Accept": "application/json"}
    query = {"key": env.get("TRELLO_API_KEY"), "token": env.get("TRELLO_TOKEN")}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=query)

    if response.status_code != 200:
        raise Exception(f"Failed to fetch lists: {response.text}")

    data = response.json()
    return [{"name": list_item["name"], "id": list_item["id"]} for list_item in data]


async def get_all_trello_cards(list_id: str, sys_config: dict) -> list[dict]:
    env = sys_config.get("env")
    if not env:
        raise ValueError("Environment not found in sys_config")

    url = f"https://api.trello.com/1/lists/{list_id}/cards"
    headers = {"Accept": "application/json"}
    query = {"key": env.get("TRELLO_API_KEY"), "token": env.get("TRELLO_TOKEN")}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=query)

    if response.status_code != 200:
        raise Exception(f"Failed to fetch cards: {response.text}")

    data = response.json()
    return [
        {"id": card["id"], "name": card["name"], "desc": card["desc"]} for card in data
    ]


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
