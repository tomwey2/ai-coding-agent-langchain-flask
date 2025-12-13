import json
import logging
import os
import re
from typing import Dict, Optional

from cryptography.fernet import Fernet, InvalidToken
from langchain_core.messages import AIMessage

from models import AgentConfig

logger = logging.getLogger(__name__)


def get_cipher_suite() -> Optional[Fernet]:
    """
    Initializes the Fernet cipher suite from the ENCRYPTION_KEY environment variable.
    """
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        logger.error("CRITICAL: ENCRYPTION_KEY not set. Cannot decrypt configuration.")
        return None
    return Fernet(key.encode())


def sanitize_response(response: AIMessage) -> AIMessage:
    """
    Entfernt halluzinierte Tool-Calls (z.B. wenn der Name ein ganzer Satz ist).
    Verhindert API Fehler 3280 (Invalid function name).
    """
    # Wenn keine Tool Calls da sind oder es keine AI Message ist, einfach zurückgeben
    if not isinstance(response, AIMessage) or not response.tool_calls:
        return response

    valid_tools = []
    # Erlaubte Zeichen für Funktionsnamen: a-z, A-Z, 0-9, _, -
    name_pattern = re.compile(r"^[a-zA-Z0-9_-]+$")

    for tc in response.tool_calls:
        name = tc.get("name", "")
        # Check: Ist der Name im gültigen Format und nicht zu lang?
        if name_pattern.match(name) and len(name) < 64:
            valid_tools.append(tc)
        else:
            logger.warning(f"SANITIZER: Removed invalid tool call with name: '{name}'")

    # Das manipulierte Objekt zurückgeben
    response.tool_calls = valid_tools
    return response


def decrypt_config(config: AgentConfig) -> Optional[Dict]:
    """
    Decrypts the system_config_json from the agent configuration.
    """
    cipher_suite = get_cipher_suite()
    decrypted_json = "{}"
    if config.system_config_json and cipher_suite:
        try:
            decrypted_json = cipher_suite.decrypt(
                config.system_config_json.encode()
            ).decode()
        except (InvalidToken, TypeError):
            logger.warning(
                "Could not decrypt system_config_json. It might be unencrypted legacy data."
            )
            decrypted_json = config.system_config_json
    elif config.system_config_json:
        # Data exists but we have no key
        logger.error("CRITICAL: system_config_json exists but cannot be decrypted.")
        return None

    try:
        return json.loads(decrypted_json or "{}")
    except json.JSONDecodeError:
        logger.error("Invalid JSON in system_config_json after decryption.")
        return None
