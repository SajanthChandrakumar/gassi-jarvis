#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR="${HOME}/.local/share/jarvis"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
ENV_DIR="${HOME}/.config/jarvis"
ENV_FILE="$ENV_DIR/mac-agent.env"

mkdir -p "$INSTALL_DIR" "$LAUNCH_AGENTS_DIR" "$ENV_DIR"
install -m 755 "$SCRIPT_DIR/run-mac-agent.sh" "$INSTALL_DIR/run-mac-agent.sh"
install -m 644 "$SCRIPT_DIR/com.gassi.jarvis.mac-agent.plist" \
    "$LAUNCH_AGENTS_DIR/com.gassi.jarvis.mac-agent.plist"
if [ ! -e "$ENV_FILE" ]; then
    install -m 600 "$SCRIPT_DIR/mac-agent.env.example" "$ENV_FILE"
else
    chmod 600 "$ENV_FILE"
fi

echo "Installed the Jarvis Mac agent wrapper and user LaunchAgent plist."
echo "Edit ~/.config/jarvis/mac-agent.env and replace its placeholders before loading."
echo "The plist was not loaded; review it and load it manually when ready."
