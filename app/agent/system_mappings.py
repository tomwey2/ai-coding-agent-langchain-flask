"""
This module defines the mappings for different task management systems.
It provides a centralized way to configure the commands, tools, and parsers
for each supported system.
"""

import logging
import os

logger = logging.getLogger(__name__)


def parse_trello_response(data):
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
            canonical_tasks.append(
                {
                    "id": card.get("id"),
                    "title": card.get("name"),
                    "description": card.get("desc"),
                }
            )
    return canonical_tasks


# A lambda function to parse the Trello card format into our canonical task format
trello_response_parser = parse_trello_response

SERVERS_PATH = os.environ.get(
    "SERVERS_PATH", "/coding-agent/servers"
)


SYSTEM_DEFINITIONS = {
    "TRELLO": {
        "command": ["tsx", os.path.join(SERVERS_PATH, "trello/src/index.ts")],
        "polling_tool": "read_board",
        "polling_args": {"boardId": "{trello_todo_list_id}"},
        "response_parser": trello_response_parser,
    },
    # Future systems like JIRA can be added here
    # "JIRA": {
    #     "command": ["npx", "-y", "@modelcontextprotocol/server-jira"],
    #     "polling_tool": "get_issues_in_project",
    #     "polling_args": {"projectId": "{project_id}"},
    #     "response_parser": lambda issue: {
    #         "id": issue.get("key"),
    #         "title": issue.get("fields", {}).get("summary"),
    #         "description": issue.get("fields", {}).get("description"),
    #     },
    # },
}
