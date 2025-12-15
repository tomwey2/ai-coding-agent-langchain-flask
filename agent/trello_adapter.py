import httpx


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
