import os
import logging
from typing import Callable, Dict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mistralai import ChatMistralAI
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from pydantic import SecretStr


logger = logging.getLogger(__name__)

def _get_api_key(env_var_name: str) -> str:
    api_key = os.environ.get(env_var_name)
    if not api_key:
        raise ValueError(f"{env_var_name} environment variable not set")
    return api_key


def _create_openai_llm(model: str, temperature: float) -> BaseChatModel:
    api_key = _get_api_key("OPENAI_API_KEY")
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=SecretStr(api_key)
    )


def _create_mistral_llm(model: str, temperature: float) -> BaseChatModel:
    api_key = _get_api_key("MISTRAL_API_KEY")
    return ChatMistralAI(
        model_name=model,
        temperature=temperature,
        api_key=SecretStr(api_key)
    )


def _create_google_llm(model: str, temperature: float) -> BaseChatModel:
    api_key = _get_api_key("GOOGLE_API_KEY")
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        google_api_key=api_key,
        convert_system_message_to_human=True,
    )


def _create_openrouter_llm(model: str, temperature: float) -> BaseChatModel:
    api_key = _get_api_key("OPENROUTER_API_KEY")
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        base_url="https://openrouter.ai/api/v1",
        api_key=SecretStr(api_key)
    )

def _create_ollama_llm(model: str, temperature: float) -> BaseChatModel:
    return ChatOllama(
        model=model,
        temperature=temperature,
        base_url="http://host.docker.internal:11434"
    )

LLM_PROVIDERS: Dict[str, Callable[[str, float], BaseChatModel]] = {
    "openai": _create_openai_llm,
    "mistral": _create_mistral_llm,
    "google": _create_google_llm,
    "gemini": _create_google_llm,
    "openrouter": _create_openrouter_llm,
    "ollama": _create_ollama_llm,
}  


def get_llm(config: dict, large: bool = True) -> BaseChatModel:
    """
    Factory function to get an LLM instance based on the provider.

    :param config: A dictionary with 'llm_provider', 'llm_model_large',
                   'llm_model_small', and 'llm_temperature'.
    :param large: If True, use llm_model_large; otherwise use llm_model_small.
    :return: An instance of a class that inherits from BaseChatModel.
    :raises ValueError: If provider is not specified, model is not specified,
                       or provider is unknown.
    """
    provider = config.get("llm_provider")
    if not provider:
        raise ValueError("llm_provider not specified")

    model = config.get("llm_model_large") if large else config.get("llm_model_small")
    if not model:
        raise ValueError("llm_model not specified")

    temperature = float(config.get("llm_temperature", 0.0))

    provider_factory = LLM_PROVIDERS.get(provider)
    if not provider_factory:
        raise ValueError(f"Unknown LLM provider: {provider}")

    logger.info(f"Creating LLM: provider={provider}, model={model}, temperature={temperature}")
    return provider_factory(model, temperature)
