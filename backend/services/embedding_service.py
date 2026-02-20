"""
Embedding service — generates text embeddings using OpenAI's
text-embedding-3-small model (1536 dimensions).

Used for:
  - Embedding clinical note content when records are uploaded
  - Embedding user queries in record_lookup for semantic (RAG) retrieval

The model produces a 1536-dimensional vector stored in the patient_records
content_vector column (pgvector). Cosine similarity search is then used to
find the most semantically relevant records for a given user query.

Why text-embedding-3-small:
  - 1536 dimensions (matches the VECTOR(1536) schema)
  - Substantially better than ada-002 at medical/clinical terminology
  - Low cost and low latency — suitable for per-upload calls
"""

import logging
from openai import AsyncOpenAI

from config import get_settings

settings = get_settings()
log = logging.getLogger("wellbridge.embedding")

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 1536

# Maximum characters to embed — keeps token cost bounded.
# Clinical notes are typically 500–3000 chars; we cap at 8000 (≈ 6k tokens).
MAX_EMBED_CHARS = 8000


async def get_embedding(text: str) -> list[float]:
    """
    Generate a 1536-dim embedding for the given text.
    Returns an empty list on failure (caller should handle gracefully —
    records without embeddings fall back to keyword/recency search).
    """
    if not text or not text.strip():
        return []

    # Truncate to keep within model token limits
    truncated = text[:MAX_EMBED_CHARS]

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=truncated,
        )
        embedding = response.data[0].embedding
        log.debug("embedding: generated %d-dim vector for %d chars", len(embedding), len(truncated))
        return embedding
    except Exception as exc:
        log.warning("embedding: failed to generate embedding — %s", exc)
        return []


async def get_query_embedding(query: str) -> list[float]:
    """
    Generate an embedding for a user query.
    Identical to get_embedding() but logs differently for observability.
    """
    if not query or not query.strip():
        return []
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=query.strip(),
        )
        return response.data[0].embedding
    except Exception as exc:
        log.warning("embedding: query embedding failed — %s", exc)
        return []
