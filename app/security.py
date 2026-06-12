"""
Gassi-Jarvis — Security Router for macOS Commands

Every shell command the LLM wants to execute passes through this module.
It classifies commands into threat levels and gates dangerous operations
behind a Human-in-the-Loop (HitL) approval flow.

Threat Levels:
    0 — Harmless (date, whoami, echo)
    1 — Read-only system queries (ls, pwd, df) — no path argument may
        resolve into a sensitive location (e.g. ~/.ssh, dotfiles, *.pem).
    2 — Dangerous / destructive / unknown / sensitive-path read
"""

import os
import shlex
import subprocess
from pathlib import Path

# ─── Threat Classification Tables ──────────────────────────────────────────────

DANGEROUS_KEYWORDS: set[str] = {
    "rm", "sudo", "su", "mv", "cp", "chmod", "chown", "chgrp",
    "kill", "killall", "pkill",
    "curl", "wget", "ssh", "scp", "sftp", "nc", "ncat",
    "dd", "mkfs", "fdisk", "diskutil",
    "shutdown", "reboot", "halt", "poweroff",
    "launchctl", "defaults", "csrutil", "spctl",
    "python", "python3", "node", "ruby", "perl", "bash", "zsh", "sh",
    "pip", "pip3", "npm", "brew",
    "osascript",  # AppleScript is handled separately via open_app
    "networksetup", "scutil", "dscl",
    "xattr", "codesign", "security",
    "tar", "zip", "unzip", "gzip", "gunzip",  # can write anywhere
    "open",  # can launch arbitrary apps/URLs
}

DANGEROUS_SYMBOLS: tuple[str, ...] = (
    "|", ">", ">>", "<", "&", "&&", "||", ";", "`", "$(", "${", "\n",
)

HARMLESS_COMMANDS: set[str] = {
    "echo", "date", "whoami", "hostname", "uname", "uptime",
    "cal", "arch", "sw_vers",
}

# Read-only commands that DO NOT take a file path argument (safe).
READONLY_NO_PATH: set[str] = {
    "pwd", "df", "top", "ps", "env", "printenv", "id", "groups",
    "system_profiler", "sysctl", "ioreg", "mdfind",
}

# Read-only commands that DO take a path argument — must be path-checked.
READONLY_WITH_PATH: set[str] = {
    "ls", "cat", "head", "tail", "wc", "find", "which", "where",
    "du", "mdls", "file", "stat",
}

# Path fragments / suffixes that must never be read by a level-1 command.
SENSITIVE_PATH_FRAGMENTS: tuple[str, ...] = (
    ".ssh", ".aws", ".gnupg", ".kube", ".docker",
    ".env", ".envrc", ".netrc", ".pgpass", ".my.cnf",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "credentials", "secrets", "keychain",
    "/etc/shadow", "/etc/sudoers", "/etc/master.passwd",
    "/private/etc/shadow", "/private/etc/sudoers",
    "/private/var/db/sudo",
)

SENSITIVE_SUFFIXES: tuple[str, ...] = (
    ".pem", ".key", ".p12", ".pfx", ".keystore", ".jks",
)

# `find` flags that turn read-only traversal into arbitrary execution / mutation.
FIND_DANGEROUS_FLAGS: set[str] = {
    "-exec", "-execdir", "-delete", "-ok", "-okdir", "-fprint",
    "-fprint0", "-fprintf",
}


# ─── Path Safety ──────────────────────────────────────────────────────────────


def _is_sensitive_path(arg: str) -> bool:
    """
    Return True if `arg` points to (or could resolve to) a sensitive location.

    Operates on the lexical form *and* the resolved absolute form. Uses string
    matching against known sensitive fragments — anything that even looks like
    a credential path is treated as sensitive.
    """
    # Strip surrounding quotes that shlex may have left.
    candidate = arg.strip().strip("'\"")
    if not candidate:
        return False

    # Expand ~ and env vars so "~/.ssh/id_rsa" and "$HOME/.ssh/..." are caught.
    expanded = os.path.expanduser(os.path.expandvars(candidate))

    try:
        resolved = str(Path(expanded).resolve(strict=False))
    except (OSError, RuntimeError):
        resolved = expanded

    haystacks = (candidate.lower(), expanded.lower(), resolved.lower())

    for hay in haystacks:
        for fragment in SENSITIVE_PATH_FRAGMENTS:
            if fragment in hay:
                return True
        for suffix in SENSITIVE_SUFFIXES:
            if hay.endswith(suffix):
                return True
    return False


def _readonly_args_are_safe(base_command: str, tokens: list[str]) -> bool:
    """
    For a read-only command, walk its positional args and reject if any
    points at a sensitive path or, for `find`, uses a mutating/exec flag.
    """
    args = tokens[1:]

    if base_command == "find":
        for tok in args:
            if tok in FIND_DANGEROUS_FLAGS:
                return False

    for tok in args:
        # Skip option flags (-l, --color, etc.); they aren't paths.
        if tok.startswith("-"):
            continue
        if _is_sensitive_path(tok):
            return False
    return True


# ─── Threat Evaluation ────────────────────────────────────────────────────────


def evaluate_security_level(command: str) -> int:
    """
    Classify a shell command string into a threat level.

    Returns:
        0 if the command is harmless,
        1 if it is a safe read-only query,
        2 if it contains dangerous keywords, shell metacharacters, is unknown,
          or is a read-only command pointed at a sensitive path.
    """
    stripped = command.strip()
    if not stripped:
        return 0

    # Rule 1: Dangerous shell metacharacters / chaining anywhere in the string.
    for symbol in DANGEROUS_SYMBOLS:
        if symbol in stripped:
            return 2

    # Rule 2: Tokenize (preserve case — paths and many flags are case-sensitive).
    try:
        tokens = shlex.split(stripped)
    except ValueError:
        # Malformed quoting → treat as dangerous.
        return 2

    if not tokens:
        return 0

    base_command = os.path.basename(tokens[0])

    # Rule 3: Explicitly dangerous base command.
    if base_command in DANGEROUS_KEYWORDS:
        return 2

    # Rule 4: Harmless.
    if base_command in HARMLESS_COMMANDS:
        return 0

    # Rule 5: Read-only without path args.
    if base_command in READONLY_NO_PATH:
        return 1

    # Rule 6: Read-only with path args — verify the paths aren't sensitive.
    if base_command in READONLY_WITH_PATH:
        return 1 if _readonly_args_are_safe(base_command, tokens) else 2

    # Rule 7: Unknown command → default to dangerous.
    return 2


# ─── Command Execution ────────────────────────────────────────────────────────

EXECUTION_TIMEOUT_SECONDS: int = 15


def _resolve_working_dir() -> str:
    """
    Working directory for shell execution. Configurable via env var so the
    home path of any single developer is never baked into the repo.
    """
    return os.environ.get("JARVIS_SHELL_CWD") or os.path.expanduser("~")


def execute_shell_command(command: str, force: bool = False) -> str:
    """
    Execute a shell command in a sandboxed subprocess.

    Args:
        command: The shell command to run.
        force: If True, bypass the threat level check entirely.
               Used when the user has explicitly approved via HitL voice confirmation.

    Returns:
        The stdout output of the command, or a formatted error string.
    """
    if not force:
        threat_level = evaluate_security_level(command)
        if threat_level >= 2:
            return (
                f"[SECURITY] Befehl blockiert (Threat Level {threat_level}): "
                f"'{command}' erfordert explizite Freigabe vom User."
            )

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=EXECUTION_TIMEOUT_SECONDS,
            cwd=_resolve_working_dir(),
        )

        if result.returncode == 0:
            output = result.stdout.strip()
            return output if output else "[OK] Befehl ausgeführt, keine Ausgabe."
        stderr = result.stderr.strip()
        return f"[ERROR] Exit-Code {result.returncode}: {stderr}"

    except subprocess.TimeoutExpired:
        return (
            f"[TIMEOUT] Befehl '{command}' hat das Zeitlimit "
            f"von {EXECUTION_TIMEOUT_SECONDS}s überschritten und wurde abgebrochen."
        )
    except OSError as e:
        return f"[OS-ERROR] Befehl konnte nicht gestartet werden: {e}"
