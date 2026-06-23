from __future__ import annotations

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.config import settings

_SUPPORTED_PROVIDERS = {"gemini", "openai", "groq", "openai_compatible"}


def _normalize_provider(provider: str | None) -> str:
    value = (provider or "").strip().lower()
    return value or "gemini"


def _split_provider_prefix(model_name: str) -> tuple[str | None, str]:
    if "/" not in model_name:
        return None, model_name

    maybe_provider, raw_model = model_name.split("/", 1)
    provider = maybe_provider.strip().lower()
    if provider in _SUPPORTED_PROVIDERS and raw_model.strip():
        return provider, raw_model.strip()

    return None, model_name


def _resolve_provider_and_model(provider: str | None, model_name: str) -> tuple[str, str]:
    prefixed_provider, raw_model = _split_provider_prefix(model_name.strip())
    selected_provider = prefixed_provider or _normalize_provider(provider)

    if selected_provider not in _SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported provider '{selected_provider}'. Supported: {sorted(_SUPPORTED_PROVIDERS)}")

    return selected_provider, raw_model


def create_chat_model(provider: str | None, model_name: str, *, temperature: float = 0.2):
    """Return a LangChain chat model from provider + model configuration.

    Model names can be prefixed with provider (e.g. groq/llama-3.1-8b-instant)
    to override the provider parameter for that specific value.
    """
    selected_provider, raw_model = _resolve_provider_and_model(provider, model_name)

    if selected_provider == "gemini":
        return ChatGoogleGenerativeAI(model=raw_model, temperature=temperature)

    if selected_provider == "groq":
        return ChatOpenAI(
            model=raw_model,
            temperature=temperature,
            api_key=settings.GROQ_API_KEY or settings.OPENAI_API_KEY,
            base_url=settings.GROQ_BASE_URL,
        )

    if selected_provider == "openai_compatible":
        return ChatOpenAI(
            model=raw_model,
            temperature=temperature,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )

    # selected_provider == "openai"
    kwargs = {
        "model": raw_model,
        "temperature": temperature,
    }
    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    if settings.OPENAI_API_KEY:
        kwargs["api_key"] = settings.OPENAI_API_KEY
    return ChatOpenAI(**kwargs)
