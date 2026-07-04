"""Environment-driven configuration, mirroring StandardGraph's DB_PATH pattern."""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("OER_DATA_DIR", str(Path.home() / ".oer-mcp")))

# Core database: CC BY (and more permissive) content only — the default install.
CORE_DB_PATH = Path(os.environ.get("OER_CORE_DB_PATH", str(DATA_DIR / "oer_core.db")))

# Optional add-on database: license-restricted content (CC BY-NC-SA: Khan,
# OpenStax 2e editions). Attached at runtime when present (D11).
ADDON_DB_PATH = Path(os.environ.get("OER_ADDON_DB_PATH", str(DATA_DIR / "oer_ncsa.db")))

# Optional AP database: AP free-response questions (College Board copyright,
# educational use). Partitioned separately so deployments can exclude it.
AP_DB_PATH = Path(os.environ.get("OER_AP_DB_PATH", str(DATA_DIR / "oer_ap.db")))

# Optional state database: state released exam items (e.g. NY Regents — state
# copyright with educational-reproduction permission, not CC). Partitioned like AP.
STATE_DB_PATH = Path(os.environ.get("OER_STATE_DB_PATH", str(DATA_DIR / "oer_state.db")))

# Build-time only (ingestion Stages 4–6); never required at query time.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://169.254.1.1:11434")
# "generate" (default) or "chat" — some hosts/models only answer via /api/chat.
OLLAMA_API = os.environ.get("OER_OLLAMA_API", "generate")
EMBED_MODEL = os.environ.get("OER_EMBED_MODEL", "nomic-embed-text")
ANNOTATE_MODEL = os.environ.get("OER_ANNOTATE_MODEL", "gemma4:31b-it-q8_0")

# StandardGraph database — read-only, ingestion Stage 5 only (D2).
STANDARDGRAPH_DB_PATH = Path(
    os.environ.get(
        "STANDARDGRAPH_DB_PATH", str(Path.home() / ".standardgraph" / "common_core.db")
    )
)

# Runtime search: query embedding via Ollama with FTS5 fallback (D13).
# Tools report search_mode="keyword_fallback" when Ollama is unreachable.
OLLAMA_QUERY_TIMEOUT_S = float(os.environ.get("OER_OLLAMA_QUERY_TIMEOUT_S", "3.0"))
