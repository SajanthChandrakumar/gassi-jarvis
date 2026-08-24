#!/bin/sh
set -eu

ENV_FILE=${JARVIS_AGENT_ENV_FILE:-"${HOME}/.config/jarvis/mac-agent.env"}
if [ ! -r "$ENV_FILE" ]; then
    echo "Jarvis Mac agent env file is missing: $ENV_FILE" >&2
    exit 1
fi

set -a
. "$ENV_FILE"
set +a

: "${JARVIS_CLOUD_API_BASE_URL:?JARVIS_CLOUD_API_BASE_URL is required}"
: "${JARVIS_DEVICE_TOKEN:?JARVIS_DEVICE_TOKEN is required}"
: "${JARVIS_SHELL_CWD:?JARVIS_SHELL_CWD is required}"
: "${JARVIS_AGENT_PROJECT_DIR:?JARVIS_AGENT_PROJECT_DIR is required}"
: "${JARVIS_AGENT_PYTHON:?JARVIS_AGENT_PYTHON is required}"

cd "$JARVIS_AGENT_PROJECT_DIR"
exec "${JARVIS_AGENT_PYTHON}" -m app.device.agent
