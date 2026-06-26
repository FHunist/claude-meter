#!/usr/bin/env bash
#
# Remove the Claude Code usage widget (leaves SwiftBar itself installed).
#
set -euo pipefail

rm -f  "${HOME}/SwiftBarPlugins/claude-meter.5m.py"
rm -rf "${HOME}/.config/claude-meter"
open "swiftbar://refreshallplugins" >/dev/null 2>&1 || true

cat <<'EOF'
Removed the plugin and ~/.config/claude-meter cache.
SwiftBar itself was left installed — to remove it too:
    brew uninstall --cask swiftbar
EOF
