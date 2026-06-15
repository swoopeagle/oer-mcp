#!/usr/bin/env bash
# OER MCP installer
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/swoopeagle/oer-mcp/main/install.sh | bash
#   ... | bash -s -- --with-khan      # also install the CC BY-NC-SA Khan add-on DB
set -euo pipefail

REPO="swoopeagle/oer-mcp"
HF="https://huggingface.co/datasets/swoopeagle/oer-mcp/resolve/main"
DB_DIR="$HOME/.oer-mcp"
CORE_DB="$DB_DIR/oer_core.db"
ADDON_DB="$DB_DIR/oer_ncsa.db"
CLAUDE_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
WITH_KHAN=0
for arg in "$@"; do [ "$arg" = "--with-khan" ] && WITH_KHAN=1; done

bold=$(tput bold 2>/dev/null || true); reset=$(tput sgr0 2>/dev/null || true)
green=$(tput setaf 2 2>/dev/null || true); blue=$(tput setaf 4 2>/dev/null || true)
red=$(tput setaf 1 2>/dev/null || true)
ok(){ echo "${green}✓${reset} $*"; }
info(){ echo "${blue}→${reset} $*"; }
fail(){ echo "${red}✗${reset} $*"; exit 1; }

echo; echo "${bold}OER MCP installer${reset}"
echo "Open-licensed curriculum content (OpenStax + Khan), standards-aligned, for Claude"; echo

# 1. uv
info "Checking for uv..."
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
fi
UVX="$(command -v uvx 2>/dev/null || true)"
[ -z "$UVX" ] && { export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"; UVX="$(command -v uvx)"; }
[ -z "$UVX" ] && fail "uvx not found after uv install. Restart your terminal and re-run."
ok "uv found at $(command -v uv)"

# 2. Databases
mkdir -p "$DB_DIR"
dl(){ # url dest label
    if [ -f "$2" ]; then info "$3 already present ($(du -sh "$2" | cut -f1)); skipping."; return; fi
    info "Downloading $3..."
    curl -L --progress-bar "$1" -o "$2" || fail "$3 download failed."
    ok "$3 → $2 ($(du -sh "$2" | cut -f1))"
}
dl "$HF/oer_core.db" "$CORE_DB" "core database (CC BY)"

if [ "$WITH_KHAN" = "1" ]; then
    echo
    echo "${bold}Khan Academy add-on (CC BY-NC-SA 4.0)${reset}"
    echo "Khan video-transcript content is licensed CC BY-NC-SA: free for"
    echo "non-commercial use with attribution; derivatives must ShareAlike."
    echo "Attribution is carried in every response. See NOTICE for details."
    dl "$HF/oer_ncsa.db" "$ADDON_DB" "Khan add-on database (CC BY-NC-SA)"
fi

# 3. Configure Claude Desktop
info "Configuring Claude Desktop..."
[ -f "$CLAUDE_CONFIG" ] || { mkdir -p "$(dirname "$CLAUDE_CONFIG")"; echo '{"mcpServers":{}}' > "$CLAUDE_CONFIG"; }

python3 - "$CLAUDE_CONFIG" "$UVX" "$CORE_DB" "$ADDON_DB" "$REPO" "$WITH_KHAN" <<'PYEOF'
import json, os, shutil, sys
cfg_path, uvx, core_db, addon_db, repo, with_khan = sys.argv[1:7]
with open(cfg_path) as f: cfg = json.load(f)
env = {"OER_CORE_DB_PATH": core_db}
if with_khan == "1": env["OER_ADDON_DB_PATH"] = addon_db
cfg.setdefault("mcpServers", {})["oer-mcp"] = {
    "command": uvx,
    "args": ["--from", f"git+https://github.com/{repo}@main", "oer-mcp"],
    "env": env,
}
if os.path.exists(cfg_path): shutil.copy2(cfg_path, cfg_path + ".bak")
with open(cfg_path, "w") as f: json.dump(cfg, f, indent=2)
print(f"  Config updated: {cfg_path}")
PYEOF
ok "Claude Desktop configured"

echo; echo "${bold}${green}Installation complete!${reset}"; echo
echo "Next steps:"
echo "  1. Quit and reopen Claude Desktop"
echo "  2. Look for the tools (🔨) icon in a new conversation"
echo "  3. Try: \"Find OpenStax content that teaches CCSS.MATH.6.NS.1\""
echo "          \"Explain dividing fractions using the actual textbook examples\""
echo "          \"How completely does the indexed content cover CCSS 6.RP?\""
echo
[ "$WITH_KHAN" = "1" ] || echo "Tip: re-run with --with-khan to add K-12 Khan transcript content (CC BY-NC-SA)."
echo "Core DB: $CORE_DB"
echo "Config:  $CLAUDE_CONFIG"
echo "Issues:  https://github.com/$REPO/issues"
