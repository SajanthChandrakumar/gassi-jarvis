#!/bin/sh
set -eu

ENV_FILE=${JARVIS_AGENT_ENV_FILE:-"${HOME}/.config/jarvis/mac-agent.env"}

fail_env() {
    echo "Jarvis Mac agent env file rejected: $*" >&2
    exit 1
}

read_mode() {
    mode=$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || true)
    case "$mode" in
        [0-7][0-7][0-7]) ;;
        *) mode=$(stat -c '%a' "$ENV_FILE" 2>/dev/null || true) ;;
    esac
    while [ "${mode#0}" != "$mode" ]; do mode=${mode#0}; done
    printf '%s' "$mode"
}

load_env() {
    if [ -L "$ENV_FILE" ] || [ ! -f "$ENV_FILE" ]; then
        fail_env "must be a regular, non-symlink file"
    fi

    mode=$(read_mode)
    case "$mode" in
        400|600) ;;
        *) fail_env "must have mode 0600 or stricter" ;;
    esac

    while IFS= read -r line || [ -n "$line" ]; do
        trimmed=$(printf '%s\n' "$line" | sed 's/^[[:space:]]*//')
        case "$trimmed" in
            ""|\#*) continue ;;
        esac

        case "$line" in
            JARVIS_CLOUD_API_BASE_URL=*|JARVIS_DEVICE_TOKEN=*|JARVIS_DEVICE_ID=*|JARVIS_DEVICE_AGENT_STATE_PATH=*|JARVIS_SHELL_CWD=*|JARVIS_AGENT_PROJECT_DIR=*|JARVIS_AGENT_PYTHON=*) ;;
            *) fail_env "unknown or malformed entry" ;;
        esac
        key=${line%%=*}
        value=${line#*=}
        case "$value" in
            \"*\")
                value=${value#\"}; value=${value%\"}
                case "$value" in *\"*) fail_env "malformed quoted value" ;; esac
                ;;
            \'*\')
                value=${value#\'}; value=${value%\'}
                case "$value" in *\'*) fail_env "malformed quoted value" ;; esac
                ;;
            *[[:space:]]*|*\"*|*\'*) fail_env "values containing spaces must be quoted" ;;
        esac
        export "$key=$value"
    done < "$ENV_FILE"
}

load_env

: "${JARVIS_CLOUD_API_BASE_URL:?JARVIS_CLOUD_API_BASE_URL is required}"
: "${JARVIS_DEVICE_TOKEN:?JARVIS_DEVICE_TOKEN is required}"
: "${JARVIS_SHELL_CWD:?JARVIS_SHELL_CWD is required}"
: "${JARVIS_AGENT_PROJECT_DIR:?JARVIS_AGENT_PROJECT_DIR is required}"
: "${JARVIS_AGENT_PYTHON:?JARVIS_AGENT_PYTHON is required}"

cd "$JARVIS_AGENT_PROJECT_DIR"
exec "${JARVIS_AGENT_PYTHON}" -m app.device.agent
