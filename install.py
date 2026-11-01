"""Install, update or uninstall Crewroom on Windows, macOS or Linux.

Double-click the file for your system instead of running this directly:
    Windows: install.cmd / uninstall.cmd
    macOS:   Install Crewroom.command / Uninstall Crewroom.command
    Linux:   sh install.sh / sh uninstall.sh

It changes nothing outside these places:
    the "team" skill for Claude and Codex   ~/.claude/skills/team-chat and ~/.agents/skills/team-chat
                                            (a skill that was there before Crewroom is kept as SKILL.md.bak)
    a way to open Crewroom                  Windows: Desktop and Start menu shortcuts
                                            macOS:   ~/Applications/Crewroom.app (Spotlight and Launchpad find it)
                                            Linux:   ~/.local/share/applications/crewroom.desktop
    an install record                       install.json in the data folder, so the next install or the
                                            uninstaller knows what is there
Your chats and requests stay in the data folder; uninstalling keeps them.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

if sys.version_info < (3, 10):
    sys.exit(f'Crewroom needs Python 3.10 or newer; this is {sys.version.split()[0]}. Get it from https://www.python.org/downloads/')

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from teamchat import __version__, paths, status, system  # noqa: E402

SKILL_DIRS = ('.claude/skills/team-chat', '.agents/skills/team-chat')
TEAM_PY = re.compile(r'"([^"]+?)[\\/]team\.py"')  # the folder a Crewroom skill points at


# --- small helpers -------------------------------------------------------------------
def say(text='', colour=None):
    codes = {'ok': '32', 'warn': '33', 'bad': '31', 'title': '1;33'}
    if colour and sys.stdout.isatty() and (not system.WINDOWS or os.environ.get('WT_SESSION') or os.environ.get('TERM')):
        text = f'\033[{codes[colour]}m{text}\033[0m'
    print(f'  {text}' if text else '')


def ask(question, default, assume):
    """Yes/no question. Enter takes the default; --yes, or no keyboard, takes it too."""
    if assume or not sys.stdin.isatty():
        return default
    hint = '[Y/n]' if default else '[y/N]'
    answer = input(f'  {question} {hint} ').strip().lower()
    return default if not answer else answer.startswith('y')


def quoted(path):
    return f'"{path}"'


def is_ours(skill_file):
    try:
        return 'team.py' in skill_file.read_text(encoding='utf-8') and 'Crewroom' in skill_file.read_text(encoding='utf-8')
    except OSError:
        return False


def skill_roots(home):
    """Crewroom folders the installed skills point at (also finds 1.0 installs, which left no record)."""
    found = []
    for d in SKILL_DIRS:
        f = home / d / 'SKILL.md'
        if is_ours(f):
            found += [m.group(1) for m in TEAM_PY.finditer(f.read_text(encoding='utf-8'))]
    return list(dict.fromkeys(found))


def powershell(script, **env):
    return subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
                          capture_output=True, text=True, env={**os.environ, **env}, **system.hidden())


# --- launchers -----------------------------------------------------------------------
def make_launchers(home, desktop, python):
    """Create the way to open Crewroom on this system. Returns the paths made."""
    made = []
    if system.WINDOWS:
        pythonw = Path(python).with_name('pythonw.exe')
        start_menu = Path(os.environ.get('APPDATA', home / 'AppData' / 'Roaming')) / 'Microsoft/Windows/Start Menu/Programs'
        folders = [desktop, start_menu]
        if home != Path.home():  # a test run with a pretend home: keep the Start menu out of it
            folders[1] = home / 'Start Menu'
        elif system.appdata_redirected():
            folders.pop()
            say('Skipped the Start menu shortcut: this installer runs inside another app (Claude or Codex), and Windows', 'warn')
            say('hides Start menu shortcuts made from there. Double-click install.cmd yourself to get one.', 'warn')
        for folder in folders:
            folder.mkdir(parents=True, exist_ok=True)
            lnk = folder / 'Crewroom.lnk'
            # Paths travel as environment variables, so quotes or non-Latin letters in them can't break the script.
            r = powershell('$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:CR_LNK); $s.TargetPath = $env:CR_PY; '
                           '$s.Arguments = \'"\' + $env:CR_PYW + \'"\'; $s.WorkingDirectory = $env:CR_ROOT; '
                           '$s.IconLocation = $env:CR_ICON; $s.Description = "Crewroom: your AI team, together"; $s.Save()',
                           CR_LNK=str(lnk), CR_PY=str(pythonw if pythonw.exists() else python), CR_PYW=str(ROOT / 'TeamChat.pyw'),
                           CR_ROOT=str(ROOT), CR_ICON=str(ROOT / 'web' / 'assets' / 'app-icon.ico'))
            if r.returncode == 0 and lnk.exists():
                made.append(str(lnk))
            else:
                say(f'Could not make the shortcut {lnk}: {r.stderr.strip()[:200]}', 'warn')
    elif system.MAC:
        app = home / 'Applications' / 'Crewroom.app'
        if app.exists():
            shutil.rmtree(app)
        (app / 'Contents' / 'MacOS').mkdir(parents=True)
        (app / 'Contents' / 'Resources').mkdir()
        icon = ''
        if shutil.which('sips'):
            out = app / 'Contents' / 'Resources' / 'Crewroom.icns'
            r = subprocess.run(['sips', '-s', 'format', 'icns', str(ROOT / 'web' / 'assets' / 'app-icon.png'), '--out', str(out)],
                               capture_output=True)
            icon = '<key>CFBundleIconFile</key><string>Crewroom</string>' if r.returncode == 0 and out.exists() else ''
        (app / 'Contents' / 'Info.plist').write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Crewroom</string>
<key>CFBundleDisplayName</key><string>Crewroom</string>
<key>CFBundleIdentifier</key><string>io.github.karthus3560.crewroom</string>
<key>CFBundleVersion</key><string>{__version__}</string>
<key>CFBundleShortVersionString</key><string>{__version__}</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleExecutable</key><string>Crewroom</string>
<key>LSUIElement</key><true/>
{icon}
</dict></plist>
''', encoding='utf-8')
        run = app / 'Contents' / 'MacOS' / 'Crewroom'
        run.write_text(f'#!/bin/sh\n# Opens the Crewroom installed from {ROOT}\nexec {quoted(python)} {quoted(ROOT / "TeamChat.pyw")}\n',
                       encoding='utf-8')
        run.chmod(0o755)
        made.append(str(app))
    else:
        apps = home / '.local' / 'share' / 'applications'
        apps.mkdir(parents=True, exist_ok=True)
        entry = apps / 'crewroom.desktop'
        entry.write_text('[Desktop Entry]\nType=Application\nName=Crewroom\nComment=Your AI team, together\n'
                         f'Exec={quoted(python)} {quoted(ROOT / "TeamChat.pyw")}\nIcon={ROOT / "web" / "assets" / "app-icon.png"}\n'
                         'Terminal=false\nCategories=Development;\n', encoding='utf-8')
        entry.chmod(0o755)
        made.append(str(entry))
    return made


def old_launchers(home, desktop):
    """Launchers an earlier install may have left (1.0 made only the Desktop shortcut and kept no record)."""
    if system.WINDOWS:
        return [desktop / 'Crewroom.lnk']
    if system.MAC:
        return [home / 'Applications' / 'Crewroom.app']
    return [home / '.local' / 'share' / 'applications' / 'crewroom.desktop']


def remove(path):
    p = Path(path)
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    else:
        return False
    return True


# --- the two jobs --------------------------------------------------------------------
def where_to_open(launchers):
    if system.WINDOWS:
        return 'the "Crewroom" shortcut on your Desktop (also in the Start menu)'
    if system.MAC:
        return 'Crewroom in your Applications folder (or press Cmd+Space and type Crewroom)'
    return 'Crewroom in your apps menu, or: ' + f'{quoted(sys.executable)} {quoted(ROOT / "TeamChat.pyw")}'


def install(a, home, desktop):
    say(f'Crewroom {__version__} installer', 'title')
    say()
    rec = status.installed()
    if rec and rec.get('installer') == 'setup' and not a.from_setup and not status.same(rec.get('root'), ROOT):
        say(f"Crewroom {rec.get('version', '')} is installed as a Windows program in {rec.get('root')}.", 'warn')
        say('To update it, run the new CrewroomSetup.exe: it updates that program in place.')
        say('To run Crewroom from this folder instead, uninstall it first: Settings > Apps > Installed apps > Crewroom.')
        return 1
    tmp = Path(tempfile.gettempdir()).resolve()
    if ROOT == tmp or tmp in ROOT.parents:
        say('This folder is temporary: it looks like the zip was opened without extracting it.', 'bad')
        say('Extract the zip, move the Crewroom folder somewhere permanent (for example Documents), and run the installer there.')
        return 1

    # What is here already?
    others = [r for r in dict.fromkeys(([rec['root']] if rec and rec.get('root') else []) + skill_roots(home))
              if not status.same(r, ROOT)]
    running = status.ping()
    running_root = status.running_root(running) if running else None
    if others:
        say('Crewroom is already installed:', 'warn')
        for r in others:
            v = status.version_of(r)
            say(f'  Crewroom{" " + v if v else ""} in {r}' + ('' if Path(r).exists() else '  (that folder is gone)'))
        if running and not status.same(running_root, ROOT):
            say(f"  It is running now (from {running_root or 'an unknown folder'}).")
        if not ask(f'Replace it with Crewroom {__version__} from this folder ({ROOT})?', True, a.yes or a.from_setup):
            say('Nothing changed.')
            return 0
    elif rec and status.same(rec.get('root'), ROOT):
        say(f"Updating the Crewroom installed here (was {rec.get('version', '?')}).")
    if running:
        say('Stopping the running Crewroom server (requests already running keep going)...')
        if not status.stop():
            say('Could not stop it. Close Crewroom, then run the installer again.', 'bad')
            return 1

    python = sys.executable
    if system.WINDOWS and Path(python).name.lower() == 'pythonw.exe':
        python = str(Path(python).with_name('python.exe'))
    say(f'Python:     {python}')
    say(f'Your data:  {paths.DATA}')
    if system.WINDOWS and system.OLD_WINDOWS_DATA.exists() and not paths.DB.exists():
        say(f'Crewroom 1.0 kept its chats in {system.OLD_WINDOWS_DATA}. 1.1 starts fresh in the folder above;', 'warn')
        say('the old chats stay where they were.', 'warn')

    # 1. The "team" skill for Claude Code and Codex, pointing at this folder.
    text = (ROOT / 'skill' / 'team-chat' / 'SKILL.md').read_text(encoding='utf-8')
    text = text.replace('{{TEAM_COMMAND}}', f'{quoted(python)} {quoted(ROOT / "team.py")}')
    skills, backups = [], []
    for d in SKILL_DIRS:
        folder = home / d
        folder.mkdir(parents=True, exist_ok=True)
        f = folder / 'SKILL.md'
        if f.exists() and not is_ours(f) and not (folder / 'SKILL.md.bak').exists():
            shutil.copy2(f, folder / 'SKILL.md.bak')
            backups.append(str(folder / 'SKILL.md.bak'))
        f.write_text(text, encoding='utf-8')
        skills.append(str(folder))
        say(f'Skill:      {folder}')

    # 2. A way to open it. Launchers of a replaced install go first, so there is only ever one "Crewroom".
    #    The setup.exe makes its own Start menu and Desktop shortcuts (same names), so it skips this step.
    launchers = []
    if not a.from_setup:
        for old in (rec or {}).get('launchers', []) if others else []:
            remove(old)
        launchers = make_launchers(home, desktop, python)
    for l in launchers:
        say(f'Open with:  {l}')

    # 3. The record the next installer, the uninstaller and `team status` read.
    paths.DATA.mkdir(parents=True, exist_ok=True)
    paths.INSTALL.write_text(json.dumps({
        'version': __version__, 'root': str(ROOT), 'python': python, 'skills': skills, 'backups': backups,
        'launchers': launchers, 'installer': 'setup' if a.from_setup else 'script', 'installed': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }, indent=2), encoding='utf-8')

    # 4. Which agents can this computer run?
    say()
    claude, codex = paths.find_claude(), paths.find_codex()
    say('Claude Code: found' if claude else 'Claude Code: not found. Install the Claude app (claude.ai/download), open it once, '
        'switch to the Code tab and sign in. Or install Claude Code (claude.ai/code).', 'ok' if claude else 'warn')
    say('Codex:       found' if codex else 'Codex:       not found. Install the Codex app (chatgpt.com/codex) or the Codex CLI, then sign in.',
        'ok' if codex else 'warn')

    if a.from_setup:
        return 0
    say()
    say(f'Done. Crewroom {__version__} is installed from {ROOT}', 'ok')
    say('Keep this folder where it is: Crewroom runs from it.')
    if others:
        say('The old folder was left as it was. Your chats are not in it, so you can delete it when you like.')
    say()
    say(f'Open it:    {where_to_open(launchers)}')
    say(f'Check it:   {quoted(python)} {quoted(ROOT / "team.py")} status')
    say('Update:     download the new version, extract it, and run its installer. It replaces this one.')
    say(f'Uninstall:  {status.uninstall_hint(ROOT)}. Your chats are kept.')
    say()
    if not a.no_open and ask('Open Crewroom now?', True, a.yes):
        subprocess.Popen([system.background_python(), str(ROOT / 'TeamChat.pyw')], cwd=str(ROOT),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **system.detached())
    return 0


def uninstall(a, home, desktop):
    say('Crewroom uninstaller', 'title')
    say()
    rec = status.installed() or {}
    if rec.get('installer') == 'setup' and not a.from_setup:
        say('Crewroom is installed as a Windows program. Uninstall it from Settings > Apps > Installed apps > Crewroom.', 'warn')
        return 1
    if not ask('Remove Crewroom (the team skill and its shortcut)? Your chats are kept.', True, a.yes or a.from_setup):
        say('Nothing changed.')
        return 0
    if status.ping():
        say('Stopping the running Crewroom server...')
        status.stop()
    for d in rec.get('skills') or [str(home / d) for d in SKILL_DIRS]:
        folder = Path(d)
        f = folder / 'SKILL.md'
        if (folder / 'SKILL.md.bak').exists():
            os.replace(folder / 'SKILL.md.bak', f)
            say(f'Restored your earlier skill in {folder}')
        elif is_ours(f):
            f.unlink()
            if not any(folder.iterdir()):
                folder.rmdir()
            say(f'Removed {folder}')
    leftovers = [] if a.from_setup else [str(p) for p in old_launchers(home, desktop)]  # setup.exe removes its own
    for l in dict.fromkeys(list(rec.get('launchers', [])) + leftovers):
        if remove(l):
            say(f'Removed {l}')
    if paths.INSTALL.exists():
        paths.INSTALL.unlink()
    say()
    say('Crewroom is uninstalled.', 'ok')
    say(f"Your chats and requests are still in {paths.DATA}. Delete that folder if you don't want them.")
    say(f"You can also delete the Crewroom folder itself: {rec.get('root') or ROOT}")
    return 0


def main():
    ap = argparse.ArgumentParser(description='Install, update or uninstall Crewroom.')
    ap.add_argument('--uninstall', action='store_true', help='remove the skill, the shortcut and the install record')
    ap.add_argument('--yes', action='store_true', help='answer yes to every question')
    ap.add_argument('--no-open', action='store_true', help="don't offer to open Crewroom at the end")
    ap.add_argument('--from-setup', action='store_true', help=argparse.SUPPRESS)  # run by CrewroomSetup.exe: skill and record only
    ap.add_argument('--home', help=argparse.SUPPRESS)     # tests: a pretend home folder
    ap.add_argument('--desktop', help=argparse.SUPPRESS)  # tests: a pretend Desktop
    a = ap.parse_args()
    home = Path(a.home) if a.home else Path.home()
    desktop = Path(a.desktop) if a.desktop else home / 'Desktop'
    if system.WINDOWS and not a.desktop and not a.home:
        r = powershell("[Environment]::GetFolderPath('Desktop')")  # OneDrive often moves the Desktop
        if r.returncode == 0 and r.stdout.strip():
            desktop = Path(r.stdout.strip())
    try:
        return uninstall(a, home, desktop) if a.uninstall else install(a, home, desktop)
    except KeyboardInterrupt:
        print()
        return 1


if __name__ == '__main__':
    sys.exit(main())
