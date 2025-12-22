import logging
import os
import sys

from langchain_mistralai import ChatMistralAI
from pydantic import SecretStr

logger = logging.getLogger(__name__)


def get_llm_model(config=None):
    """
    Erstellt und konfiguriert das Mistral LLM.
    """

    # 1. API Key holen (Prio: Environment -> Config DB -> Fallback)
    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        print(
            "ERROR: Environment variable MISTRAL_API_KEY is not set.", file=sys.stderr
        )
        sys.exit(1)

    model = "mistral-medium-latest"  # oder "mistral-large-latest" für bessere Tool-Performance

    # 2. Modell initialisieren
    # Wir nutzen 'mistral-large-latest', da es die besten Fähigkeiten
    # für Tool-Use (Function Calling) hat.
    return ChatMistralAI(
        model_name=model,
        temperature=0,
        api_key=SecretStr(api_key),
        max_retries=2,
        max_tokens=8192,
    )
