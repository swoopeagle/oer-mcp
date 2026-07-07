#!/usr/bin/env bash
# OER MCP installer
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/swoopeagle/oer-mcp/main/install.sh | bash
#   ... | bash -s -- --with-khan      # + CC BY-NC-SA Khan/OpenMiddle add-on DB
#   ... | bash -s -- --with-state     # + state released-exam DB (NY Regents, MCAS)
#   ... | bash -s -- --with-ap        # + AP free-response DB
#   ... | bash -s -- --all            # core + every add-on
set -euo pipefail

REPO="swoopeagle/oer-mcp"
HF="https://huggingface.co/datasets/swoopeagle/oer-mcp/resolve/main"
DB_DIR="$HOME/.oer-mcp"
CORE_DB="$DB_DIR/oer_core.db"
ADDON_DB="$DB_DIR/oer_ncsa.db"
STATE_DB="$DB_DIR/oer_state.db"
AP_DB="$DB_DIR/oer_ap.db"
case "$(uname -s)" in
    Darwin) CLAUDE_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json" ;;
    Linux)  CLAUDE_CONFIG="$HOME/.config/Claude/claude_desktop_config.json" ;;
    *)      CLAUDE_CONFIG="$HOME/.config/Claude/claude_desktop_config.json" ;;
esac
WITH_KHAN=0; WITH_STATE=0; WITH_AP=0
for arg in "$@"; do case "$arg" in
    --with-khan)  WITH_KHAN=1 ;;
    --with-state) WITH_STATE=1 ;;
    --with-ap)    WITH_AP=1 ;;
    --all)        WITH_KHAN=1; WITH_STATE=1; WITH_AP=1 ;;
esac; done

bold=$(tput bold 2>/dev/null || true); reset=$(tput sgr0 2>/dev/null || true)
green=$(tput setaf 2 2>/dev/null || true); blue=$(tput setaf 4 2>/dev/null || true)
red=$(tput setaf 1 2>/dev/null || true)
ok(){ echo "${green}✓${reset} $*"; }
info(){ echo "${blue}→${reset} $*"; }
fail(){ echo "${red}✗${reset} $*"; exit 1; }

echo; echo "${bold}OER MCP installer${reset}"
echo "Open-licensed curriculum content + released assessment items, standards-aligned, for Claude"; echo

# 1. uv
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"  # pick up a prior uv install before checking
info "Checking for uv..."
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh || true  # ignore shell-profile permission errors
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
fi
UVX="$(command -v uvx 2>/dev/null || true)"
[ -z "$UVX" ] && fail "uvx not found after uv install. Restart your terminal and re-run."
ok "uv found at $(command -v uv)"

# 2. Databases
mkdir -p "$DB_DIR"
dl(){ # url dest label [optional]  — trailing "optional" => a failed download warns, not aborts
    if [ -f "$2" ]; then info "$3 already present ($(du -sh "$2" | cut -f1)); skipping."; return; fi
    info "Downloading $3..."
    if ! curl -fL --progress-bar "$1" -o "$2"; then
        rm -f "$2"
        if [ "${4:-}" = "optional" ]; then
            echo "${red}✗${reset} $3 not available yet — skipping (core install unaffected)."
            return 1
        fi
        fail "$3 download failed."
    fi
    ok "$3 → $2 ($(du -sh "$2" | cut -f1))"
}
dl "$HF/oer_core.db" "$CORE_DB" "core database (CC BY)"

if [ "$WITH_KHAN" = "1" ]; then
    echo
    echo "${bold}Khan / OpenMiddle add-on (CC BY-NC-SA 4.0)${reset}"
    echo "Khan video-transcript + OpenMiddle content is licensed CC BY-NC-SA: free"
    echo "for non-commercial use with attribution; derivatives must ShareAlike."
    echo "Attribution is carried in every response. See NOTICE for details."
    dl "$HF/oer_ncsa.db" "$ADDON_DB" "NC-SA add-on database (CC BY-NC-SA)" optional || WITH_KHAN=0
fi

if [ "$WITH_STATE" = "1" ]; then
    echo
    echo "${bold}State released-exam add-on (state copyright, educational use)${reset}"
    echo "NY Regents + MCAS released items. State-copyright content reproduced"
    echo "under each state's educational-reproduction permission — NOT CC-licensed."
    echo "Attribution is carried in every response. See NOTICE for details."
    dl "$HF/oer_state.db" "$STATE_DB" "state exam database (educational use)" optional || WITH_STATE=0
fi

if [ "$WITH_AP" = "1" ]; then
    echo
    echo "${bold}AP free-response add-on (© College Board, educational use)${reset}"
    echo "AP free-response questions (Calculus, Statistics, Precalculus). College"
    echo "Board copyright, included under an educational-use rationale — NOT CC."
    echo "Attribution is carried in every response. See NOTICE for details."
    dl "$HF/oer_ap.db" "$AP_DB" "AP FRQ database (educational use)" optional || WITH_AP=0
fi

# 3. Configure Claude Desktop
info "Configuring Claude Desktop..."
[ -f "$CLAUDE_CONFIG" ] || { mkdir -p "$(dirname "$CLAUDE_CONFIG")"; echo '{"mcpServers":{}}' > "$CLAUDE_CONFIG"; }

python3 - "$CLAUDE_CONFIG" "$UVX" "$CORE_DB" "$ADDON_DB" "$WITH_KHAN" "$STATE_DB" "$WITH_STATE" "$AP_DB" "$WITH_AP" <<'PYEOF'
import json, os, shutil, sys
cfg_path, uvx, core_db, addon_db, with_khan, state_db, with_state, ap_db, with_ap = sys.argv[1:10]
with open(cfg_path) as f: cfg = json.load(f)
env = {"OER_CORE_DB_PATH": core_db}
if with_khan == "1":  env["OER_ADDON_DB_PATH"] = addon_db
if with_state == "1": env["OER_STATE_DB_PATH"] = state_db
if with_ap == "1":    env["OER_AP_DB_PATH"] = ap_db
cfg.setdefault("mcpServers", {})["oer-mcp"] = {
    "command": uvx,
    "args": ["oer-mcp"],
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
[ "$WITH_KHAN" = "1" ]  || echo "Tip: --with-khan  adds K-12 Khan transcripts + OpenMiddle (CC BY-NC-SA)."
[ "$WITH_STATE" = "1" ] || echo "Tip: --with-state adds NY Regents + MCAS released exam items (educational use)."
[ "$WITH_AP" = "1" ]    || echo "Tip: --with-ap    adds AP free-response items (educational use)."
echo "     (or --all for everything)"
echo "Core DB: $CORE_DB"
echo "Config:  $CLAUDE_CONFIG"
echo "Issues:  https://github.com/$REPO/issues"
