import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mistralai import ChatMistralAI
from langchain_openai import ChatOpenAI
from pydantic import SecretStr


def get_llm(config: dict) -> BaseChatModel:
    """
    Factory function to get an LLM instance based on the provider.

    :param config: A dictionary with 'llm_provider', 'llm_model', and 'llm_temperature'.
    :return: An instance of a class that inherits from BaseChatModel.
    """
    provider = config.get("llm_provider")
    if not provider:
        raise ValueError("llm_provider not specified")
    model = config.get("llm_model")
    if not model:
        raise ValueError("llm_model not specified")
    temperature = float(config.get("llm_temperature", 0.0))

    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        return ChatOpenAI(
            model=model, temperature=temperature, api_key=SecretStr(api_key)
        )
    elif provider == "mistral":
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError("MISTRAL_API_KEY environment variable not set")
        return ChatMistralAI(
            model_name=model, temperature=0, api_key=SecretStr(api_key)
        )
    elif provider in ["google", "gemini"]:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not set")
        return ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            google_api_key=api_key,
            convert_system_message_to_human=True,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
