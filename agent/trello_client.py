import logging

import httpx

logger = logging.getLogger(__name__)


def get_safe_url(url: str, params: dict) -> str:
    """
    Erstellt eine URL für das Logging, bei der sensitive Parameter maskiert sind.
    """
    # Wir bauen die volle URL inkl. Params nach, um sie zu parsen
    req = httpx.Request("GET", url, params=params)
    parsed_url = req.url

    # Wir kopieren die Query-Parameter, aber überschreiben die Secrets
    new_query_params = []
    for key, value in parsed_url.params.items():
        if key in ["key", "token"]:
            new_query_params.append((key, "SECRET"))
        else:
            new_query_params.append((key, value))

    # URL mit sicherem Query-String zurückgeben
    return str(parsed_url.copy_with(params=new_query_params))


async def get_all_trello_lists(sys_config: dict) -> list[dict]:
    env = sys_config.get("env")
    if not env:
        raise ValueError("Environment not found in sys_config")

    url = f"https://api.trello.com/1/boards/{sys_config.get('trello_board_id')}/lists"
    headers = {"Accept": "application/json"}
    query = {"key": env.get("TRELLO_API_KEY"), "token": env.get("TRELLO_TOKEN")}

    logger.info(f"Trello GET: {get_safe_url(url, query)}")
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

    logger.info(f"Trello GET: {get_safe_url(url, query)}")
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=query)

    if response.status_code != 200:
        raise Exception(f"Failed to fetch cards: {response.text}")

    data = response.json()
    return [
        {"id": card["id"], "name": card["name"], "desc": card["desc"]} for card in data
    ]


async def move_trello_card_to_list(card_id: str, list_id: str, sys_config: dict):
    env = sys_config.get("env")
    if not env:
        raise ValueError("Environment not found in sys_config")

    url = f"https://api.trello.com/1/cards/{card_id}"
    headers = {"Accept": "application/json"}
    query = {
        "idList": list_id,
        "key": env.get("TRELLO_API_KEY"),
        "token": env.get("TRELLO_TOKEN"),
    }

    logger.info(f"Trello PUT: {get_safe_url(url, query)}")
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, params=query)

    if response.status_code != 200:
        raise Exception(
            f"Failed to move card {card_id} to list {list_id}: {response.text}"
        )


async def add_comment_to_trello_card(card_id: str, comment: str, sys_config: dict):
    env = sys_config.get("env")
    if not env:
        raise ValueError("Environment not found in sys_config")

    url = f"https://api.trello.com/1/cards/{card_id}/actions/comments"
    headers = {"Accept": "application/json"}
    query = {
        "text": comment,
        "key": env.get("TRELLO_API_KEY"),
        "token": env.get("TRELLO_TOKEN"),
    }

    logger.info(f"Trello POST: {get_safe_url(url, query)}")
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, params=query)

    if response.status_code != 200:
        raise Exception(f"Failed to add a comment to card {card_id}: {response.text}")
