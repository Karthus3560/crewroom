"""Where Crewroom keeps its data, and where the Claude and Codex programs live."""
import glob
import os
import shutil
import subprocess
from pathlib import Path

from . import system

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
DATA = system.data_dir()
DB = DATA / 'team.sqlite3'
LOGS = DATA / 'logs'
INSTALL = DATA / 'install.json'  # written by install.py: which folder is installed, and what it added
PORT = int(os.environ.get('TEAMCHAT_PORT', '47800'))

CLAUDE_PROJECTS = HOME / '.claude' / 'projects'
CODEX_HOME = Path(os.environ.get('CODEX_HOME') or HOME / '.codex')
CODEX_SESSIONS = CODEX_HOME / 'sessions'


def _newest(patterns):
    found = [p for pattern in patterns for p in glob.glob(pattern)]
    return max(found, key=os.path.getmtime) if found else None


def find_codex():
    """The Codex CLI moves with every app update, so look it up fresh each time."""
    if system.WINDOWS:
        try:
            out = subprocess.run(['powershell', '-NoProfile', '-Command',
                '(Get-AppxPackage -Name "OpenAI.Codex*" | Sort-Object Version -Descending | Select-Object -First 1).InstallLocation'],
                capture_output=True, text=True, timeout=15, **system.hidden()).stdout.strip()
            if out and (Path(out) / 'app' / 'resources' / 'codex.exe').exists():
                return str(Path(out) / 'app' / 'resources' / 'codex.exe')
        except (OSError, subprocess.SubprocessError):
            pass
        local = os.environ.get('LOCALAPPDATA', '')
        return _newest([os.path.join(local, 'OpenAI', 'Codex', 'bin', '*', 'codex.exe')]) or shutil.which('codex')
    if system.MAC:  # the Codex app carries its own CLI
        app = _newest(['/Applications/Codex.app/Contents/Resources/codex', str(HOME / 'Applications/Codex.app/Contents/Resources/codex')])
        if app:
            return app
    found = system.candidates('codex')
    return found[0] if found else None


def find_claude():
    """Prefer the Claude Code build that ships with Claude Desktop."""
    env = os.environ.get('CLAUDE_CODE_EXECPATH')
    if env and Path(env).exists():
        return env
    if system.WINDOWS:
        local = os.environ.get('LOCALAPPDATA', '')
        return _newest([os.path.join(local, 'Claude-Data', 'claude_*', 'claude-code', '*', '*', 'claude.exe'),
                        os.path.join(local, 'AnthropicClaude', 'app-*', 'resources', 'claude-code', '*', 'claude.exe')]) \
            or shutil.which('claude')
    if system.MAC:
        app = _newest([str(HOME / 'Library/Application Support/Claude/claude-code/*/claude'),
                       str(HOME / 'Library/Application Support/Claude-3p/claude-code/*/claude')])
        if app:
            return app
    found = system.candidates('claude')
    return found[0] if found else None
