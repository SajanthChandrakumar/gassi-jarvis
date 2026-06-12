"""
Tests for the Gassi-Jarvis security router (app/security.py).

Run from the project root:
    python -m pytest tests/ -v
"""

import pytest

from app.security import evaluate_security_level, execute_shell_command


# ─── Threat Classification ────────────────────────────────────────────────────


class TestHarmlessCommands:
    @pytest.mark.parametrize("cmd", [
        "echo hi",
        "date",
        "whoami",
        "hostname",
        "uname -a",
        "sw_vers",
        "",
        "   ",
    ])
    def test_level_0(self, cmd):
        assert evaluate_security_level(cmd) == 0


class TestReadonlyCommands:
    @pytest.mark.parametrize("cmd", [
        "ls",
        "ls -la /tmp",
        "pwd",
        "df -h",
        "cat README.md",
        "head -n 5 notes.txt",
        "find . -name '*.py'",
        "mdfind kMDItemDisplayName",
        "stat /tmp",
    ])
    def test_level_1(self, cmd):
        assert evaluate_security_level(cmd) == 1


class TestDangerousCommands:
    @pytest.mark.parametrize("cmd", [
        "rm -rf /",
        "sudo ls",
        "curl http://evil.example",
        "wget http://evil.example",
        "python3 -c 'import os'",
        "brew install something",
        "osascript -e 'tell app \"Finder\"'",
        "shutdown -h now",
        "dd if=/dev/zero of=/dev/disk0",
        "tar -xf archive.tar",
        "open /Applications/Calculator.app",
    ])
    def test_level_2(self, cmd):
        assert evaluate_security_level(cmd) == 2

    def test_unknown_command_defaults_dangerous(self):
        assert evaluate_security_level("somemadeupbinary --flag") == 2

    def test_malformed_quoting_is_dangerous(self):
        assert evaluate_security_level("cat 'unterminated") == 2


class TestMetacharacters:
    @pytest.mark.parametrize("cmd", [
        "ls | grep foo",
        "echo hi > /tmp/x",
        "echo hi >> /tmp/x",
        "cat < /etc/passwd",
        "date && rm -rf /",
        "date; rm -rf /",
        "echo `whoami`",
        "echo $(whoami)",
        "echo ${HOME}",
        "date & rm -rf /",
        "date\nrm -rf /",
    ])
    def test_chaining_is_dangerous(self, cmd):
        assert evaluate_security_level(cmd) == 2


class TestPathBypass:
    """A denylisted binary must not slip through via an absolute path."""

    @pytest.mark.parametrize("cmd", [
        "/usr/bin/curl http://evil.example",
        "/bin/rm -rf /",
        "/usr/bin/python3 script.py",
    ])
    def test_absolute_path_still_dangerous(self, cmd):
        assert evaluate_security_level(cmd) == 2


class TestSensitivePathReads:
    """Read-only commands escalate when pointed at credential material."""

    @pytest.mark.parametrize("cmd", [
        "cat ~/.ssh/id_rsa",
        "cat /Users/someone/.ssh/id_ed25519",
        "head ~/.aws/credentials",
        "cat .env",
        "tail ~/.netrc",
        "cat server.pem",
        "cat private.key",
        "ls ~/.gnupg",
        "cat /etc/shadow",
        "cat $HOME/.ssh/config",
    ])
    def test_sensitive_read_is_dangerous(self, cmd):
        assert evaluate_security_level(cmd) == 2

    @pytest.mark.parametrize("cmd", [
        "cat README.md",
        "ls ~/Desktop",
        "head -n 20 main.py",
    ])
    def test_normal_read_stays_readonly(self, cmd):
        assert evaluate_security_level(cmd) == 1


class TestFindEscalation:
    """`find` flags that execute or mutate must escalate."""

    @pytest.mark.parametrize("cmd", [
        "find / -name id_rsa -exec cat {} +",
        "find . -name '*.log' -delete",
        "find . -name x -ok rm {} +",
    ])
    def test_find_exec_is_dangerous(self, cmd):
        assert evaluate_security_level(cmd) == 2

    def test_plain_find_is_readonly(self):
        assert evaluate_security_level("find . -name '*.py'") == 1


# ─── Execution Gate ───────────────────────────────────────────────────────────


class TestExecutionGate:
    def test_dangerous_command_blocked_without_force(self):
        result = execute_shell_command("rm -rf /tmp/definitely-not-run")
        assert "[SECURITY]" in result

    def test_harmless_command_executes(self):
        result = execute_shell_command("echo jarvis-test")
        assert "jarvis-test" in result

    def test_cwd_respects_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JARVIS_SHELL_CWD", str(tmp_path))
        result = execute_shell_command("pwd")
        assert str(tmp_path) in result
