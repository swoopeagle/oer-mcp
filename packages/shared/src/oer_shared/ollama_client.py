"""One place to call an Ollama text model, supporting both /api/generate and
/api/chat. Some hosts/models in the arsenal only produce output via one of them
(e.g. the Windows gemma4:12b returns empty on /api/generate but works on
/api/chat), so the endpoint is selectable per worker via OER_OLLAMA_API.
Callers own their own retry loops; this is a single request.
"""

from __future__ import annotations

import httpx

from . import config


def complete(
    prompt: str, model: str, client: httpx.Client, *,
    temperature: float = 0.0, num_predict: int | None = None, timeout: float = 180.0,
) -> str:
    opts: dict = {"temperature": temperature}
    if num_predict is not None:
        opts["num_predict"] = num_predict
    if config.OLLAMA_API == "chat":
        resp = client.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={"model": model, "stream": False, "options": opts,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    resp = client.post(
        f"{config.OLLAMA_BASE_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False, "options": opts},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()
