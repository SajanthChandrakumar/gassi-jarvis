# Cloud and Mac-agent deployment

Task 5 keeps the cloud process and the macOS capability process in separate
trust zones. The cloud image contains FastAPI, Gemini, memory, Calendar, and
deterministic research. The Mac agent is the only process that contains the
shell classifier, AppleScript app launcher, screenshot capture, and local
device state.

## Cloud with Compose

Copy `deploy/cloud.env.example` to an external file, replace every
`CHANGE_ME`, and keep that file outside the repository. Then run Compose with
that path:

```bash
cp deploy/cloud.env.example ~/.config/jarvis/cloud.env
chmod 600 ~/.config/jarvis/cloud.env
JARVIS_CLOUD_ENV_FILE="$HOME/.config/jarvis/cloud.env" docker compose -f compose.yaml up --build
```

The cloud binds to `127.0.0.1` only. Named volumes persist ChromaDB,
`jarvis_sessions.json`, and the cloud device queue. `JARVIS_API_TOKEN` and
`JARVIS_DEVICE_TOKEN` are separate bearer credentials; neither belongs in a
committed file. The image runs as the unprivileged `jarvis` user and its build
context excludes the Mac executor, security, vision, AppleScript, state, and
launchd implementations.

The existing `requirements.txt` remains the complete local compatibility set.
The cloud image installs `requirements-cloud.txt` (including the unchanged
OpenBB and Uvicorn pins), while the outbound Mac process uses the smaller
`requirements-device.txt` set.

## Tailscale Serve

Keep the cloud listener on localhost and expose it through Tailscale Serve:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8000
```

Use the resulting HTTPS origin in `JARVIS_ALLOWED_ORIGINS` and
`JARVIS_FRONTEND_API_BASE_URL`. Tailscale Serve app tokens, when enabled by
the tailnet policy, are transport/application credentials and are distinct
from both Jarvis bearer tokens. Store an app token only in an external
operator-owned env file or the Tailscale configuration; never put it in the
Compose file, plist, frontend, or image.

## Mac LaunchAgent

The committed plist is secret-free and uses `KeepAlive` plus `RunAtLoad`. It
loads `~/.config/jarvis/mac-agent.env` through the wrapper, so the device token
and local paths stay outside the plist. Copy the external example and enforce
mode `0600`:

```bash
cp deploy/launchd/mac-agent.env.example ~/.config/jarvis/mac-agent.env
chmod 600 ~/.config/jarvis/mac-agent.env
```

Review the files, then optionally run `deploy/launchd/install.sh`. The script
only copies the wrapper and plist; it does not install or load a LaunchAgent
during repository validation. Loading is an explicit operator action after
checking the external env file and plist.

On macOS, grant the Python/Terminal host running the agent **Screen Recording**
permission for `screencapture`, and **Automation** permission for AppleScript
app activation. These permissions belong only on the Mac; the cloud process
does not request or receive them.

## Static-host frontend

The FastAPI deployment serves a no-store `/config.js`. A separate static host
must provide the same contract before `app.js` loads, with an origin/root URL
only — never a value ending in `/api`:

```js
window.JARVIS_CONFIG = { apiBaseUrl: "https://jarvis.example.ts.net" };
```

Do not cache this file with a stale API origin. All browser API calls use the
configured origin helper and retain their existing `/api/...` route paths.

## Local two-process compatibility

The existing one-command local mode remains available for migration and tests:

```bash
JARVIS_DEVICE_TOKEN=... \
JARVIS_SHELL_CWD="$HOME/JarvisSandbox" \
python scripts/run_local_compat.py
```

It starts Uvicorn and the outbound Mac agent on loopback, and stops both on
exit. It does not replace the cloud/device boundary and does not install or
load launchd.
