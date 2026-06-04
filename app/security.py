"""
Gassi-Jarvis — Zero-Trust Security Router for macOS Commands

Every shell command the LLM wants to execute passes through this module.
It classifies commands into threat levels and gates dangerous operations
behind a Human-in-the-Loop (HitL) approval flow.

Threat Levels:
    0 — Harmless (date, whoami, echo)
    1 — Read-only system queries (ls, pwd, df, cat)
    2 — Dangerous / destructive / unknown (rm, sudo, curl, pipes, redirects)
"""

import subprocess
import shlex

# ─── Threat Classification Tables ──────────────────────────────────────────────

DANGEROUS_KEYWORDS: list[str] = [
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
]

DANGEROUS_SYMBOLS: list[str] = [
    "|", ">", ">>", "&", "&&", "||", ";", "`", "$(", "${",
]

HARMLESS_COMMANDS: list[str] = [
    "echo", "date", "whoami", "hostname", "uname", "uptime",
    "cal", "arch", "sw_vers",
]

READONLY_COMMANDS: list[str] = [
    "ls", "pwd", "cat", "head", "tail", "wc", "find", "which", "where",
    "df", "du", "top", "ps", "env", "printenv", "id", "groups",
    "system_profiler", "sysctl", "ioreg", "diskutil list",
    "mdls", "mdfind", "file", "stat",
]


# ─── Threat Evaluation ────────────────────────────────────────────────────────

def evaluate_security_level(command: str) -> int:
    """
    Classify a shell command string into a threat level.

    Args:
        command: The raw shell command string to evaluate.

    Returns:
        0 if the command is harmless (echo, date, etc.),
        1 if it is a read-only system query (ls, pwd, etc.),
        2 if it contains dangerous keywords, symbols, or is unknown.
    """
    normalized = command.strip().lower()

    # Rule 1: Check for dangerous shell metacharacters / chaining
    for symbol in DANGEROUS_SYMBOLS:
        if symbol in normalized:
            return 2

    # Rule 2: Extract the base command (first token)
    try:
        tokens = shlex.split(normalized)
    except ValueError:
        # Malformed quoting → treat as dangerous
        return 2

    if not tokens:
        return 0

    base_command = tokens[0]

    # Rule 3: Check if the base command is explicitly dangerous
    if base_command in DANGEROUS_KEYWORDS:
        return 2

    # Rule 4: Check for harmless commands
    if base_command in HARMLESS_COMMANDS:
        return 0

    # Rule 5: Check for read-only commands
    if base_command in READONLY_COMMANDS:
        return 1

    # Rule 6: Unknown command → default to dangerous (Zero-Trust)
    return 2


# ─── Command Execution ────────────────────────────────────────────────────────

EXECUTION_TIMEOUT_SECONDS: int = 15


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
            cwd="/Users/Sajanth",
        )

        if result.returncode == 0:
            output = result.stdout.strip()
            return output if output else "[OK] Befehl ausgeführt, keine Ausgabe."
        else:
            stderr = result.stderr.strip()
            return f"[ERROR] Exit-Code {result.returncode}: {stderr}"

    except subprocess.TimeoutExpired:
        return (
            f"[TIMEOUT] Befehl '{command}' hat das Zeitlimit "
            f"von {EXECUTION_TIMEOUT_SECONDS}s überschritten und wurde abgebrochen."
        )
    except OSError as e:
        return f"[OS-ERROR] Befehl konnte nicht gestartet werden: {e}"
    except Exception as e:
        return f"[FATAL] Unerwarteter Fehler bei Befehlsausführung: {e}"
