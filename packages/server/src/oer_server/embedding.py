"""Runtime query embedding for hybrid search (D13).

Mirrors StandardGraph's prefix-free /api/embed call so query vectors share the
chunk-vector space. A short timeout keeps the tool responsive; any failure
(Ollama down/busy) returns None so search_content degrades to FTS5 keyword
search rather than erroring.
"""

import httpx
import numpy as np

from oer_shared import config


def embed_query(text: str) -> np.ndarray:
    resp = httpx.post(
        f"{config.OLLAMA_BASE_URL}/api/embed",
        json={"model": config.EMBED_MODEL, "input": [text]},
        timeout=config.OLLAMA_QUERY_TIMEOUT_S,
    )
    resp.raise_for_status()
    return np.array(resp.json()["embeddings"][0], dtype=np.float32)
