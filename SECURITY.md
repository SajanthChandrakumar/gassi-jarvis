# Security Model

Gassi-Jarvis is a **single-user, self-hosted** assistant that runs shell
commands and captures the screen on the machine it runs on, driven by an LLM.
That makes the security posture the most important part of the project. This
document describes the threat model, the layered defenses, their known limits,
and how to report an issue.

> **Disclaimer:** this is a personal research project, not a production-hardened
> product. Run it on your own machine, with a strong token, behind a private
> tunnel — and read [`app/security.py`](app/security.py) before trusting it.

---

## What we defend

The backend is reachable from the internet through a tunnel, so the design
assumes an attacker who can reach `/api/chat` and who can influence content the
model reads (a web page, a screenshot, a previously stored memory). The assets
worth protecting are: **arbitrary command execution on the host**, **the user's
files and secrets**, and **the bearer token**.

---

## Layered defenses

### 1. Authentication & transport
- **Bearer token** (`JARVIS_API_TOKEN`) compared with `secrets.compare_digest`
  (constant-time). If unset, the API silently downgrades to **localhost-only**.
- **Token TTL on the client**: the PWA caches the token for 12 hours, so a
  stolen unlocked phone loses access by the next day.
- **Rate limiting** (SlowAPI, 20/min) keyed on the real client via
  `X-Forwarded-For` behind the tunnel.
- **CORS allowlist** (`JARVIS_ALLOWED_ORIGINS`) so a random site the user visits
  can't read responses.
- **Topology**: Mac → ngrok/Tailscale (HTTPS) → phone. The Mac never opens a
  public port directly.

### 2. Command threat classification (`security.py`)
Every shell command the model proposes is parsed and rated:

| Level | Meaning | Examples | Action |
|-------|---------|----------|--------|
| 0 | Harmless | `echo`, `date`, `whoami` | run |
| 1 | Read-only | `ls`, `cat`, `pwd`, `find` | run, unless a sensitive path |
| 2 | Dangerous / unknown | `rm`, `sudo`, `curl`, pipes, `$( )`, unknown cmd, sensitive-path read | **HitL** |

Additional guards:
- **Shell metacharacters** (`|`, `>`, `;`, `&&`, backticks, `$(`, `${`, newlines)
  force Level 2 — no command chaining slips through.
- **Sensitive paths** blocked at Level 1: `~/.ssh`, `~/.aws`, `~/Library/Cookies`,
  `~/Library/Keychains`, `~/Library/Messages`, `/etc/passwd`, `*.pem`, and more.
- **`find` argument inspection**: `-exec`/`-delete` and path-valued flags
  (`-name id_rsa`) are caught, not just the base command.
- **App launches** go through a strict regex before `osascript`, so an app name
  can't break out into arbitrary AppleScript.

### 3. Human-in-the-Loop (HitL)
Level-2 commands are queued as a `pending_command` and require an explicit
spoken **"Ja"** on the next turn. The intent classifier runs at temperature 0.0
and **fails closed**: `DENY` or ambiguous → the command is dropped. Queued
commands **expire after 5 minutes** so a stale approval can't fire them.

### 4. Indirect-injection guard
Replies built from **untrusted content** — screenshots, web-search results,
recalled memories — are marked `tainted`. If the model proposes a shell command
on the immediately following turn, it is forced through HitL regardless of its
own threat level. This blocks the direct "read this → silently run that" attack.

### 5. Execution sandboxing & secret hygiene
- Commands run via `subprocess.run` with a timeout and a configurable working
  directory (`JARVIS_SHELL_CWD`).
- Screenshots write to a `tempfile.mkstemp` path (no symlink race).
- `.env`, `jarvis_brain/`, and `jarvis_sessions.json` are git-ignored and
  docker-ignored, so secrets and personal data never enter the repo or an image.
- Internal exception text is never returned to the client.

---

## Known limitations (honest)

- **`shell=True`** is the single point of failure: the classifier list is the
  only thing between the model's output and `bash -c`. A missed token would be an
  execution bypass. Argv-list execution would be strictly safer.
- **Indirect injection is only mitigated, not solved.** A *delayed* attack
  (tainted turn → innocuous turn → attack) is out of scope, by design, to avoid
  forcing HitL on every command after a single screenshot.
- **`X-Forwarded-For` is spoofable**, so rate limiting is not a hard
  anti-brute-force guarantee — the token strength is what actually matters.
- **The LLM chooses the commands.** Prompt injection resistance ultimately
  depends on Gemini; the defenses above bound the blast radius, they don't make
  the model incorruptible.

---

## Recommendations for operators

1. Set a long random `JARVIS_API_TOKEN` (`python -c "import secrets; print(secrets.token_urlsafe(32))"`).
2. Prefer **Tailscale** over a public ngrok URL where possible.
3. Point `JARVIS_SHELL_CWD` at a scratch directory if you don't want `$HOME`
   reachable by default.
4. Keep your phone's lockscreen strong — it's the last barrier behind the token TTL.

---

## Reporting a vulnerability

This is a personal project without a formal disclosure program. If you find an
issue, please open a GitHub issue describing the problem (omit any live secrets),
or contact the maintainer directly. Please don't file exploit details against
someone else's running instance.
