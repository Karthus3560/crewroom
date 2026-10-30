"""Where Team Chat keeps its data, and where the Claude and Codex programs live."""
import glob
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
DATA = Path(os.environ.get('TEAMCHAT_DATA') or Path(os.environ.get('LOCALAPPDATA', HOME)) / 'TeamChat')
DB = DATA / 'team.sqlite3'
LOGS = DATA / 'logs'
PORT = int(os.environ.get('TEAMCHAT_PORT', '47800'))

CLAUDE_PROJECTS = HOME / '.claude' / 'projects'
CODEX_HOME = Path(os.environ.get('CODEX_HOME') or HOME / '.codex')
CODEX_SESSIONS = CODEX_HOME / 'sessions'


def _newest(patterns):
    found = [p for pattern in patterns for p in glob.glob(pattern)]
    return max(found, key=os.path.getmtime) if found else None


def find_codex():
    """The Codex CLI moves with every app update, so look it up fresh each time."""
    try:
        out = subprocess.run(['powershell', '-NoProfile', '-Command',
            '(Get-AppxPackage -Name "OpenAI.Codex*" | Sort-Object Version -Descending | Select-Object -First 1).InstallLocation'],
            capture_output=True, text=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.strip()
        if out and (Path(out) / 'app' / 'resources' / 'codex.exe').exists():
            return str(Path(out) / 'app' / 'resources' / 'codex.exe')
    except (OSError, subprocess.SubprocessError):
        pass
    local = os.environ.get('LOCALAPPDATA', '')
    return _newest([os.path.join(local, 'OpenAI', 'Codex', 'bin', '*', 'codex.exe')]) or shutil.which('codex')


def find_claude():
    """Prefer the Claude Code build that ships with Claude Desktop."""
    env = os.environ.get('CLAUDE_CODE_EXECPATH')
    if env and Path(env).exists():
        return env
    local = os.environ.get('LOCALAPPDATA', '')
    return _newest([os.path.join(local, 'Claude-Data', 'claude_*', 'claude-code', '*', '*', 'claude.exe'),
                    os.path.join(local, 'AnthropicClaude', 'app-*', 'resources', 'claude-code', '*', 'claude.exe')]) \
        or shutil.which('claude')
