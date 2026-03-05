from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("agentouto")

try:
    import aiohttp
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False


@dataclass
class ModelMetadata:
    context_window: int
    max_output_tokens: int | None = None


_MINIMAL_FALLBACK: dict[str, ModelMetadata] = {
    "gpt-5": ModelMetadata(context_window=400_000, max_output_tokens=128_000),
    "gpt-5-mini": ModelMetadata(context_window=400_000, max_output_tokens=128_000),
    "gpt-5-nano": ModelMetadata(context_window=400_000, max_output_tokens=128_000),
    "gpt-4o": ModelMetadata(context_window=128_000, max_output_tokens=16_384),
    "claude-opus-4-6": ModelMetadata(context_window=200_000, max_output_tokens=32_768),
    "claude-sonnet-4-6": ModelMetadata(context_window=200_000, max_output_tokens=32_768),
    "gemini-2.5-pro": ModelMetadata(context_window=1_000_000, max_output_tokens=64_000),
}


_api_key: str | None = None
_loaded: bool = False
_api_metadata: dict[str, ModelMetadata] = {}


def set_api_key(key: str | None) -> None:
    global _api_key, _loaded
    _api_key = key
    _loaded = False
    _api_metadata.clear()


def _get_api_key_from_env() -> str | None:
    return os.environ.get("ARTIFICIAL_ANALYSIS_API_KEY")


async def _load_from_api() -> dict[str, ModelMetadata]:
    global _loaded, _api_metadata
    if _loaded:
        return _api_metadata
    
    api_key = _api_key or _get_api_key_from_env()
    if not api_key:
        _loaded = True
        return {}
    
    if not _AIOHTTP_AVAILABLE:
        _loaded = True
        return {}
    
    url = "https://artificialanalysis.ai/api/v2/data/llms/models"
    headers = {"x-api-key": api_key}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for model_data in data.get("data", []):
                        name = model_data.get("name", "").lower()
                        slug = model_data.get("slug", "").lower()
                        context_window = model_data.get("context_window")
                        max_output = model_data.get("max_output_tokens")
                        if context_window:
                            meta = ModelMetadata(
                                context_window=context_window,
                                max_output_tokens=max_output,
                            )
                            _api_metadata[name] = meta
                            if slug and slug != name:
                                _api_metadata[slug] = meta
                    logger.info(
                        "Loaded %d models from Artificial Analysis API",
                        len(_api_metadata),
                    )
                else:
                    logger.warning(
                        "Artificial Analysis API returned status %s", resp.status
                    )
    except Exception as e:
        logger.warning("Failed to fetch model metadata from API: %s", e)
    
    _loaded = True
    return _api_metadata


async def ensure_loaded() -> None:
    await _load_from_api()


def get_model_info(model: str) -> ModelMetadata | None:
    model_lower = model.lower()
    
    if model_lower in _api_metadata:
        return _api_metadata[model_lower]
    
    if model_lower in _MINIMAL_FALLBACK:
        return _MINIMAL_FALLBACK[model_lower]
    
    for known, meta in _api_metadata.items():
        if known in model_lower or model_lower in known:
            return meta
    
    for known, meta in _MINIMAL_FALLBACK.items():
        if known in model_lower or model_lower in known:
            return meta
    
    return None


def resolve_max_output_tokens(model: str, user_value: int | None) -> int | None:
    if user_value is not None:
        return user_value
    
    info = get_model_info(model)
    if info and info.max_output_tokens:
        return info.max_output_tokens
    
    return None


async def get_context_window(model: str) -> int | None:
    await ensure_loaded()
    info = get_model_info(model)
    if info:
        return info.context_window
    return None
