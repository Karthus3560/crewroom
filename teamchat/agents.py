"""The coding agents Crewroom can hire, and how to run each one in the background.

Claude Code and Codex have their own runners in worker.py (Claude reads notes mid-run over stdin; Codex
talks to its app server). Cursor Agent and the Antigravity CLI are plain command-line agents with a
print mode, so one generic runner drives both from the description here:
how to find the program, how to build the command, and how to read its streamed JSON.

Member ids start with the agent's id: "cursor", "cursor-reviewer", "antigravity-designer", ...
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

from . import paths, system

HOME = Path.home()
NEVER = ['git push', 'git reset --hard', 'git clean', 'git checkout --', 'rm -rf', 'rm -r', 'rmdir', 'del ', 'erase',
         'format', 'shutdown', 'reg ', 'Remove-Item', 'Clear-Content', 'Stop-Computer', 'Restart-Computer']
LONG_PROMPT = 24000  # Windows caps a command line at ~32k characters; longer briefs go through a file


class Agent:
    def __init__(self, id, name, color, blurb, install, login, live_notes=False, shell=True):
        self.id, self.name, self.color, self.blurb = id, name, color, blurb
        self.install, self.login = install, login  # one-line hints for the setup check and the guide
        self.live_notes = live_notes  # reads the lead's notes while it works (else they become a follow-up)
        self.shell = shell            # whether "Can run commands" applies (Codex always runs in its own sandbox)


AGENTS = {
    'claude': Agent('claude', 'Claude', '#d97757', 'Claude Code · code, writing, review',
                    'Install the Claude app (claude.ai/download), open it once and switch to the Code tab, or install Claude Code.',
                    'Sign in inside the Claude app or run: claude', live_notes=True),
    'codex': Agent('codex', 'Codex', '#10a37f', 'Codex · ChatGPT models · images, shell, builds',
                   'Install the Codex app (chatgpt.com/codex) or the Codex CLI.', 'Sign in inside the Codex app or run: codex login',
                   live_notes=True, shell=False),
    'cursor': Agent('cursor', 'Cursor', '#6d5ce8', 'Cursor Agent · code, refactors, many models',
                    "Install Cursor's CLI: irm 'https://cursor.com/install?win32=true' | iex  (macOS/Linux: curl https://cursor.com/install -fsS | bash)",
                    'Run: agent login'),
    'antigravity': Agent('antigravity', 'Antigravity', '#3b82f6', 'Antigravity CLI · Gemini, Claude and GPT-OSS models',
                         'Install the Antigravity CLI: irm https://antigravity.google/cli/install.ps1 | iex  (macOS/Linux: see the guide)',
                         'Run: agy  (it opens Google sign-in the first time)'),
}
CLI_AGENTS = ('cursor', 'antigravity')


def app_of(mid):
    mid = str(mid)
    for app in sorted(AGENTS, key=len, reverse=True):
        if mid == app or mid.startswith(app + '-'):
            return app
    return 'human'


# --- finding the programs ----------------------------------------------------------
def _cursor():
    """Cursor Agent as an argv prefix. On Windows its .cmd launcher breaks on paths with spaces (user names like
    "DIGITAL WORLD"), so Crewroom runs the bundled node.exe + index.js of the newest version directly."""
    if system.WINDOWS:
        versions = Path(os.environ.get('LOCALAPPDATA', HOME)) / 'cursor-agent' / 'versions'
        newest = sorted((d for d in versions.glob('*') if (d / 'node.exe').exists() and (d / 'index.js').exists()),
                        key=lambda d: d.name, reverse=True) if versions.exists() else []
        return [str(newest[0] / 'node.exe'), str(newest[0] / 'index.js')] if newest else None
    for name in ('agent', 'cursor-agent'):
        found = system.candidates(name)
        if found:
            return [found[0]]
    return None


def _agy():
    if system.WINDOWS:
        exe = Path(os.environ.get('LOCALAPPDATA', HOME)) / 'agy' / 'bin' / 'agy.exe'
        return [str(exe)] if exe.exists() else None
    found = system.candidates('agy')
    return [found[0]] if found else None


def command(app):
    """argv prefix that starts the agent, or None if it isn't installed."""
    if app == 'claude':
        exe = paths.find_claude()
    elif app == 'codex':
        exe = paths.find_codex()
    else:
        return {'cursor': _cursor, 'antigravity': _agy}[app]()
    return [exe] if exe else None


# --- models ----------------------------------------------------------------------
_models = {}


def models(app):
    """[{'id', 'name'}] for the model picker; the first entry means "the agent's own default"."""
    if time.time() - _models.get(app, (0, None))[0] < 600:
        return _models[app][1]
    found = []
    exe = command(app)
    if exe and app in CLI_AGENTS:
        try:
            out = subprocess.run(exe + ['models'], capture_output=True, text=True, encoding='utf-8', errors='replace',
                                 timeout=45, stdin=subprocess.DEVNULL, **system.hidden()).stdout
            for line in out.splitlines():
                if app == 'cursor':
                    m = re.match(r'^\s*([\w.\-]+)\s+-\s+(.+?)\s*(\(.*\))?\s*$', line)
                else:
                    m = re.match(r'^\s*([\w.\-]+)\t+(.+?)\s*$', line)
                if m and m.group(1) not in ('auto', 'Available'):
                    found.append({'id': m.group(1), 'name': m.group(2)})
        except (OSError, subprocess.SubprocessError):
            pass
    default = ('Auto — Cursor picks a fitting model per request (default; cheapest in its Cost setting)' if app == 'cursor'
               else f'Default (your {AGENTS[app].name} setting)')
    out = [{'id': '', 'name': default}] + found
    _models[app] = (time.time(), out)
    return out


# --- running a turn ------------------------------------------------------------------
def brief(text, rid):
    """Very long prompts would overflow the command line on Windows: hand them over in a file instead."""
    if len(text) <= LONG_PROMPT:
        return text
    folder = paths.DATA / 'briefs'
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f'{rid}.md'
    f.write_text(text, encoding='utf-8')
    return (f'Your full task from Crewroom is in this file; read all of it first and follow it exactly:\n{f}\n\n'
            f'(It is long, so it was saved to a file. Its first lines:)\n{text[:1500]}')


def argv(app, member, root, cwd, session, text):
    """The command for one turn. `session` continues the member's ongoing chat when it has one."""
    exe = command(app)
    model = member.get('model')
    shell = bool(member.get('shell'))
    if app == 'cursor':
        args = exe + ['-p', '--output-format', 'stream-json', '--trust', '--workspace', root]
        if shell:
            args.append('--force')  # commands too; without it Cursor edits files but asks before commands (= refused here)
        if model:
            args += ['--model', model]
        if session:
            args += ['--resume', session]
        return args + [text]
    if app == 'antigravity':
        # Settings for this run only (never saved): file access always, commands only when the lead allowed them.
        allow = ['read_file(*)', 'write_file(*)'] + (['command(*)'] if shell else [])
        deny = [f'command({c.strip()}*)' for c in NEVER] if shell else ['command(*)', 'unsandboxed(*)']
        args = exe + ['--output-format', 'stream-json', '--mode', 'accept-edits',
                      '--settings', json.dumps({'permissions': {'allow': allow, 'deny': deny}})]
        if shell:
            args.append('--sandbox')
        if model:
            args += ['--model', model]
        if session:
            args += ['--conversation', session]
        if Path(cwd).resolve() != Path(root).resolve():
            args += ['--add-dir', cwd]
        return args + ['-p', text]  # -p takes the next word as the prompt, so it goes last
    raise ValueError(app)


def read(app, event):
    """One streamed event -> {'session': id} | {'final': text, 'error': bool} | {}."""
    if app == 'cursor':
        if event.get('type') == 'system' and event.get('session_id'):
            return {'session': event['session_id']}
        if event.get('type') == 'result':
            return {'final': event.get('result') or '', 'error': bool(event.get('is_error')) or event.get('subtype') != 'success'}
        return {}
    if app == 'antigravity':
        if event.get('event') == 'init' and event.get('conversation_id'):
            return {'session': event['conversation_id']}
        if event.get('event') == 'result':
            r = event.get('result') or {}
            return {'final': r.get('response') or '', 'error': r.get('status') != 'SUCCESS', 'session': r.get('conversation_id')}
        if event.get('event') == 'error':
            return {'final': json.dumps(event.get('error') or event)[:2000], 'error': True}
        return {}
    return {}


def setup_status():
    """{app: {'found': bool, 'install': hint, 'login': hint}} for the welcome screen."""
    return {a.id: {'found': bool(command(a.id)), 'name': a.name, 'install': a.install, 'login': a.login,
                   'optional': a.id in CLI_AGENTS} for a in AGENTS.values()}
