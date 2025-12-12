"""
This module defines the mappings for different task management systems.
It provides a centralized way to configure the commands, tools, and parsers
for each supported system.
"""

# A lambda function to parse the Trello card format into our canonical task format
trello_response_parser = lambda card: {
    "id": card.get("id"),
    "title": card.get("name"),
    "description": card.get("desc"),
}

SYSTEM_DEFINITIONS = {
    "TRELLO": {
        "command": ["node", "/app/servers/trello/dist/index.js"],
        "polling_tool": "get_cards_in_list",
        "polling_args": {
            "listId": "{trello_todo_list_id}"
        },  # Use the key from webapp.py
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
