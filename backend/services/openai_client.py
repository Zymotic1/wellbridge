"""
Singleton AsyncOpenAI client — shared across all nodes and services.

Eliminates the overhead of creating a new HTTP connection pool on every
LLM call (20+ instantiations per chat message were each creating fresh
TLS handshakes). Connection reuse via keep-alive saves ~50-100ms per call.
"""

from openai import AsyncOpenAI
from config import get_settings

_client: AsyncOpenAI | None = None


def get_openai_client() -> AsyncOpenAI:
    """Return a shared AsyncOpenAI client instance (created once, reused)."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client
