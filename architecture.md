# Gassi-Jarvis System Architecture

The Gassi-Jarvis backend operates on a decoupled, layered architecture. It combines a Voice-First UI with a Layered Security Router that acts as a Large Action Model (LAM) for macOS automation, gated behind bearer-token auth and a Human-in-the-Loop approval flow.

## Microservice Architecture Diagram

```mermaid
graph TD
    CLIENT["Frontend (PWA / Voice)"] -->|POST /api/chat<br/>Bearer token| AUTH["main.py<br/>(Auth + Rate Limit + CORS)"]
    AUTH --> MAIN["main.py<br/>(Gateway & Route Controller)"]

    subgraph FastAPI Backend
        MAIN -->|Step 1: HitL Check| MEMORY["memory.py<br/>(Session State & ChromaDB)"]
        MAIN -->|Step 1: Intent Check| AGENT_NLP["agent.py<br/>(NLP Intent Classifier)"]
        MAIN -->|Step 2: LLM Call| AGENT_LLM["agent.py<br/>(Gemini Orchestrator)"]

        MAIN -->|open_app| OSASCRIPT["osascript<br/>(AppleScript Execution)"]
        MAIN -->|shell_command| SECURITY["security.py<br/>(Layered Security Router)"]
        MAIN -->|take_screenshot| VISION["vision.py<br/>(macOS Screencapture)"]
        MAIN -->|web_search| SEARCH["agent.search_web<br/>(Google Search grounding)"]
        MAIN -->|save/recall_memory| MEMDISP["agent.handle_memory_tool"]

        SECURITY -->|Level 0-1 & untainted| EXEC["subprocess.run()"]
        SECURITY -->|Level 2 OR tainted context| MEMORY
        MEMORY -.->|Saves pending_command + ts| MAIN

        MAIN -->|Validate In/Out| MODELS["models.py<br/>(Pydantic v2 Schemas)"]
        MAIN -.->|Structured logs| LOG["logging_config.py"]
        MAIN -.->|Persist sessions| DISK["jarvis_sessions.json"]
    end

    AGENT_LLM <--> GEMINI["Google Gemini 2.5 API"]
    AGENT_LLM <--> TOOLS["Tools: execute_mac_command<br/>take_screenshot, web_search<br/>save/recall/get_memory"]
```

---

## File Structure & Responsibilities

| File | Primary Responsibility | Key Components |
|------|------------------------|----------------|
| **`main.py`** | **Gateway & Controller** | Single entry point. Enforces bearer-token auth (`JARVIS_API_TOKEN`), per-IP rate limiting (SlowAPI), and a CORS allowlist. Manages the 4-step request lifecycle (HitL Interceptor → LLM Call → Tool Executor → TTS/Response). |
| **`models.py`** | **API Contract** | Enforces strict JSON validation using Pydantic v2 (`MessagePayload`, `ChatRequest`, `ChatResponse`). |
| **`memory.py`** | **Session & RAG** | Disk-persistent session state (multi-turn history, pending HitL command + timestamp, taint flags) and long-term memory via ChromaDB (local `all-MiniLM-L6-v2` embeddings). |
| **`agent.py`** | **LLM Orchestrator** | Handles all Google Gemini integrations. Declares the tool set, manages multi-turn contexts, runs vision analysis, dispatches memory tools (`handle_memory_tool`) and live web search (`search_web`, Google Search grounding), and acts as an NLP intent classifier. |
| **`security.py`** | **Layered Security Router** | Evaluates shell commands via `evaluate_security_level`. Sandboxes execution via `subprocess.run()` with a configurable working directory. |
| **`vision.py`** | **Vision Module** | Executes macOS `screencapture` against a `tempfile.mkstemp` path (symlink-race safe), drops alpha channels, and compresses images via Pillow. |
| **`logging_config.py`** | **Observability** | Central logging setup; verbosity toggled via `JARVIS_LOG_LEVEL`. Quiets noisy third-party loggers (chromadb, httpx). |
| **`static/`** | **Installable PWA** | `index.html` (conversation transcript + inline HitL approval cards, token-TTL auth, AbortController kill-switch), `manifest.json` + maskable icons, and `sw.js` (network-first navigation, cache-first static, never intercepts `/api/*`). |

### Static Serving Routes

- `GET /` → serves the PWA `index.html`.
- `GET /sw.js` → serves the service worker at root scope so it can control the whole app.
- `/static/*` → mounted `StaticFiles` for the manifest and icons.
- `POST /api/chat` → the only dynamic endpoint; token-gated and rate-limited.

---

## Auth & Transport

`/api/chat` sits behind three composable defenses:

1. **Bearer-token auth** — `JARVIS_API_TOKEN` is compared with `secrets.compare_digest` to avoid timing attacks. If the env var is unset, the endpoint silently downgrades to localhost-only (for safe local dev). The frontend PWA stores the token in `localStorage` with a 12-hour TTL, so a stolen unlocked phone loses access by the next morning.
2. **Rate limiting** — SlowAPI caps `/api/chat` at 20 requests/minute. Behind a tunnel every request arrives from `127.0.0.1`, so the key function reads the leftmost `X-Forwarded-For` entry (the real client) and falls back to the peer. Run uvicorn with `--forwarded-allow-ips` to trust that header. (`X-Forwarded-For` is spoofable, so this is not a hard brute-force guarantee — the token remains the wall — but it prevents the shared-bucket self-lock.)
3. **CORS allowlist** — `JARVIS_ALLOWED_ORIGINS` (comma-separated) restricts which origins the browser will let read the response. Limits cross-site request forgery from random pages the user happens to visit.

The intended deployment topology is **Mac (local) → tunnel (ngrok or Tailscale, HTTPS) → phone PWA**. The Mac never opens a port to the public internet directly.

---

## Tool Dispatch (why some tools are handled by hand)

Gemini's automatic function calling (AFC) is **disabled** whenever the tool list mixes manual `FunctionDeclaration`s with Python callables. The mac-control tools *must* stay manual so every shell command is gated through `security.py`, so the SDK never auto-runs anything. As a consequence, `main.py` dispatches each tool call itself:

- **`execute_mac_command`** → `open_app` (regex-checked `osascript`) or `shell_command` (security router).
- **`take_screenshot`** → `vision.py` → Gemini Vision follow-up call.
- **`web_search`** → `agent.search_web`, a **separate grounding-only call** (Google Search grounding cannot share a request with function declarations). Read-only: the model reads results and answers, it never gains a way to act on the web.
- **`save/recall/get_memory`** → `agent.handle_memory_tool` runs the ChromaDB operation, then feeds the result back to Gemini for a natural-language reply.

---

## Indirect-Injection Guard

Screenshots, web results, and recalled memories are **untrusted input** — they can contain text that tries to steer the model ("ignore previous instructions, run …"). Each reply built from such content is marked `tainted` in the session history. If the model proposes a `shell_command` on the **immediately following turn**, that command is forced through the HitL gate regardless of its own threat level (`last_reply_tainted`).

This is a mitigation, not a proof: it covers the direct "read something → act on it" attack. A delayed variant (tainted turn, an innocuous turn, then the attack) is out of scope by design, to avoid forcing HitL on every command for the rest of a conversation after a single screenshot.

---

## Session Persistence

Sessions live in `jarvis_sessions.json` (path via `JARVIS_SESSIONS_FILE`), written atomically (temp file + `os.replace`) and loaded corrupt-safely at startup. This means a server restart no longer drops the conversation history — or, more importantly, a **pending HitL command** still awaiting approval.

Because a queued command now survives restarts, it also carries a timestamp and **expires after 5 minutes** (`PENDING_COMMAND_TTL_SECONDS`), so a stale "yes" can't fire a command proposed long ago.

The file contains conversation content and is git-ignored and docker-ignored.

---

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `GOOGLE_API_KEY` | Gemini API key (required) | — |
| `JARVIS_API_TOKEN` | Bearer token for `/api/chat`; unset ⇒ localhost-only | unset |
| `JARVIS_ALLOWED_ORIGINS` | Comma-separated CORS origins | localhost |
| `JARVIS_LOG_LEVEL` | `DEBUG`\|`INFO`\|`WARNING`\|`ERROR` | `INFO` |
| `JARVIS_SHELL_CWD` | Working dir for sandboxed shell exec | `$HOME` |
| `JARVIS_BRAIN_DIR` | ChromaDB store location | `<root>/jarvis_brain` |
| `JARVIS_SESSIONS_FILE` | Persisted session store | `<root>/jarvis_sessions.json` |

---

## Layered Human-in-the-Loop (HitL) Flow

To safely operate as a Large Action Model (LAM) on local macOS hardware, every terminal command generated by Gemini passes through `security.py`.

### Threat Levels
1. **Level 0 (Harmless)**: `echo`, `date`, `whoami` → Executed instantly.
2. **Level 1 (Read-Only)**: `ls`, `pwd`, `cat` → Executed instantly (unless accessing sensitive paths like `.env` or `~/.ssh`).
3. **Level 2 (Dangerous)**: `rm`, `sudo`, `curl`, `pip`, `find -exec`, reads of sensitive paths, or any unknown command → **Intercepted**.

A Level 0/1 command is also intercepted if the previous reply was `tainted`
(see Indirect-Injection Guard above).

### The Interception Lifecycle
If a Level 2 (or injection-suspect) command is generated:
1. The command is halted and saved to `memory.py` as a `pending_command` (with a timestamp; it expires after 5 minutes).
2. Jarvis responds to the user via TTS: *"Achtung! Der Befehl X ist gefährlich. Soll ich ihn ausführen?"*
3. The next time the user speaks, `main.py` intercepts the audio.
4. `agent.py` uses Gemini (Temperature 0.0) as an NLP intent classifier to evaluate if the user said `APPROVE` ("Ja", "Mach das") or `DENY` ("Stopp", "Nein").
5. **Fail-Closed Gate:** If approved, `security.py` executes the command with `force=True`. If denied, or if the intent is ambiguous (UNCLEAR), the command is safely dropped.

---

## Kill-Switch (Interruptibility)

To ensure the AI is fully controllable and not locked in long operations or TTS playback, a frontend Kill-Switch is implemented:
- **AbortController:** Every fetch request to `/api/chat` is bound to an `AbortController`. If the user interrupts, the pending HTTP request is instantly aborted.
- **Audio Interruption:** If Jarvis is currently speaking (TTS playback), clicking the microphone instantly pauses the audio, resets the time, and triggers the microphone for new input.
- **UI State Management:** Visual feedback (Amber pulsing) is provided when Jarvis is speaking, making it clear that he can be interrupted.
