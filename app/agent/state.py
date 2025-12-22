from typing import Annotated, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    next_step: str
    stack: str
    retry_count: int  # Versuche, wie oft zwischen coder und tester gewechselt wurde
    test_result: Optional[str]
    error_log: Optional[str]  # Optional: Speichert den letzten Fehler explizit
    trello_card_id: Optional[str]
    trello_list_id: Optional[str]
