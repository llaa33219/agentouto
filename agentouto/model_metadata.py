from __future__ import annotations

import logging
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


class ModelMetadataError(Exception):
    pass


_loaded: bool = False
_load_attempted: bool = False
_api_metadata: dict[str, ModelMetadata] = {}


async def _load_from_openrouter() -> dict[str, ModelMetadata]:
    global _loaded, _load_attempted, _api_metadata
    
    if _loaded:
        return _api_metadata
    
    if _load_attempted:
        raise ModelMetadataError("Failed to load model metadata from OpenRouter")
    
    _load_attempted = True
    
    if not _AIOHTTP_AVAILABLE:
        raise ModelMetadataError("aiohttp not installed. Install with: pip install aiohttp")
    
    url = "https://openrouter.ai/api/v1/models"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    raise ModelMetadataError(
                        f"OpenRouter API returned status {resp.status}"
                    )
                
                data = await resp.json()
                for model_entry in data.get("data", []):
                    model_id = model_entry.get("id", "").lower()
                    endpoints = model_entry.get("endpoints", [])
                    if not endpoints:
                        continue
                    endpoint = endpoints[0]
                    context_length = endpoint.get("context_length")
                    if not context_length:
                        continue
                    max_output = endpoint.get("max_output_tokens")
                    meta = ModelMetadata(
                        context_window=context_length,
                        max_output_tokens=max_output,
                    )
                    _api_metadata[model_id] = meta
                    
                    author = model_entry.get("author", "")
                    name = model_entry.get("name", "").lower()
                    if author and name:
                        short_key = f"{author}/{name}"
                        _api_metadata[short_key] = meta
                
                if not _api_metadata:
                    raise ModelMetadataError("No models loaded from OpenRouter API")
                
                logger.info(
                    "Loaded %d models from OpenRouter API",
                    len(_api_metadata),
                )
    except ModelMetadataError:
        raise
    except Exception as e:
        raise ModelMetadataError(f"Failed to fetch model metadata from OpenRouter: {e}")
    
    _loaded = True
    return _api_metadata


async def ensure_loaded() -> None:
    await _load_from_openrouter()


def get_model_info(model: str) -> ModelMetadata:
    if not _loaded:
        raise ModelMetadataError(
            "Model metadata not loaded. Call ensure_loaded() first."
        )
    
    model_lower = model.lower()
    
    if model_lower in _api_metadata:
        return _api_metadata[model_lower]
    
    for known, meta in _api_metadata.items():
        if known in model_lower or model_lower in known:
            return meta
    
    available = ", ".join(sorted(_api_metadata.keys())[:20])
    raise ModelMetadataError(
        f"Model '{model}' not found in OpenRouter. "
        f"Available models (first 20): {available}..."
    )


def resolve_max_output_tokens(model: str, user_value: int | None) -> int | None:
    if user_value is not None:
        return user_value
    
    info = get_model_info(model)
    if info.max_output_tokens:
        return info.max_output_tokens
    
    raise ModelMetadataError(
        f"Model '{model}' does not have max_output_tokens info"
    )


async def get_context_window(model: str) -> int:
    await ensure_loaded()
    info = get_model_info(model)
    return info.context_window
