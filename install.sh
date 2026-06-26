#!/usr/bin/env bash
#
# Claude Code usage — macOS menu-bar widget installer.
# Installs SwiftBar (if needed) and drops the plugin into ~/SwiftBarPlugins.
#
set -euo pipefail

PLUGIN="claude-meter.5m.py"
PLUGIN_DIR="${HOME}/SwiftBarPlugins"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Used only for the `curl | bash` install path (when the repo is public):
RAW_URL="https://raw.githubusercontent.com/FHunist/claude-meter/main/${PLUGIN}"

say(){ printf "\033[1;36m==>\033[0m %s\n" "$*"; }
err(){ printf "\033[1;31mError:\033[0m %s\n" "$*" >&2; exit 1; }

[[ "$(uname)" == "Darwin" ]] || err "This widget is macOS-only."
command -v brew    >/dev/null 2>&1 || err "Homebrew is required — https://brew.sh"
command -v python3 >/dev/null 2>&1 || err "python3 is required — 'brew install python'."

# 1. SwiftBar (the menu-bar host)
if [[ ! -d "/Applications/SwiftBar.app" ]]; then
  say "Installing SwiftBar…"
  brew install --cask swiftbar
  xattr -dr com.apple.quarantine "/Applications/SwiftBar.app" 2>/dev/null || true
else
  say "SwiftBar already installed."
fi

# 2. Drop the plugin into place
mkdir -p "$PLUGIN_DIR"
if [[ -f "${SCRIPT_DIR}/${PLUGIN}" ]]; then
  cp "${SCRIPT_DIR}/${PLUGIN}" "${PLUGIN_DIR}/${PLUGIN}"
else
  say "Plugin not found next to installer — downloading…"
  curl -fsSL "$RAW_URL" -o "${PLUGIN_DIR}/${PLUGIN}" \
    || err "Download failed. If the repo is private, clone it and run ./install.sh from inside."
fi
chmod +x "${PLUGIN_DIR}/${PLUGIN}"
say "Plugin installed → ${PLUGIN_DIR}/${PLUGIN}"

# 3. Point SwiftBar at the folder
defaults write com.ambar.SwiftBar PluginDirectory "$PLUGIN_DIR" >/dev/null 2>&1 || true

# 4. Launch or refresh
if pgrep -x SwiftBar >/dev/null 2>&1; then
  open "swiftbar://refreshallplugins" >/dev/null 2>&1 || true
  say "Refreshed SwiftBar."
else
  open "/Applications/SwiftBar.app" >/dev/null 2>&1 || true
  say "Launched SwiftBar."
fi

cat <<'EOF'

Done. Two one-time grants on first launch:
  1) If SwiftBar asks for a plugin folder, choose:  ~/SwiftBarPlugins
  2) When "SwiftBar wants to use the Claude Code-credentials key" appears,
     click "Always Allow" so it can read your usage. (Deny → it falls back
     to a local estimate instead of live numbers.)

Look for the ◔ disc in your menu bar. Click it for the full breakdown.
EOF
