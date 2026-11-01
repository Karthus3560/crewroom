"""Everything that differs between Windows, macOS and Linux, in one place.

The rest of Crewroom calls these helpers instead of Windows-only APIs, so the same code runs on all three.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WINDOWS = sys.platform == 'win32'
MAC = sys.platform == 'darwin'
HOME = Path.home()

if WINDOWS:
    import msvcrt
else:
    import fcntl

HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def data_dir():
    """Where the mailbox, logs and install record live.

    Not AppData on Windows: the Claude and Codex apps are packaged Windows apps, and Windows quietly redirects
    AppData writes from anything they start (Claude Code running `team ask`) into a private copy. Crewroom 1.0
    kept its mailbox there and ended up with two: the window read one while Claude wrote to the other.
    The home folder is never redirected, which is why ~/.claude and ~/.codex live there too."""
    if os.environ.get('TEAMCHAT_DATA'):
        return Path(os.environ['TEAMCHAT_DATA'])
    if WINDOWS:
        return HOME / '.crewroom'
    if MAC:
        return HOME / 'Library' / 'Application Support' / 'Crewroom'
    return Path(os.environ.get('XDG_DATA_HOME') or HOME / '.local' / 'share') / 'crewroom'


def scratch_dirs():
    """Folders whose chats are throwaway (temp files, app caches)."""
    found = [Path(tempfile.gettempdir())]
    if WINDOWS:
        found.append(HOME / 'AppData')
    elif MAC:
        found += [HOME / 'Library', Path('/private/var/folders'), Path('/tmp')]
    else:
        found += [HOME / '.cache', Path('/tmp')]
    return found


def background_python():
    """The Python to start background processes with: pythonw on Windows, so no console window opens."""
    exe = Path(sys.executable)
    if WINDOWS and exe.with_name('pythonw.exe').exists():
        return str(exe.with_name('pythonw.exe'))
    return str(exe)


def detached():
    """Popen options for a process that outlives the one that started it and shows no window."""
    if WINDOWS:
        return {'creationflags': HIDDEN | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {'start_new_session': True}


def hidden():
    """Popen options for a child process that should not open a console window."""
    return {'creationflags': HIDDEN} if WINDOWS else {}


# --- locks and processes -----------------------------------------------------------
def try_lock(f):
    """Take an exclusive lock on an open file without waiting. True if we got it."""
    try:
        if WINDOWS:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def unlock(f):
    try:
        if WINDOWS:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def alive(pid):
    if not pid:
        return False
    if WINDOWS:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists, it just isn't ours
    try:  # a finished child we never waited for is a zombie: gone for our purposes
        return os.waitpid(int(pid), os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True


def stop(pid):
    """End a process (used only for an old Crewroom server that has no Stop button)."""
    try:
        if WINDOWS:
            subprocess.run(['taskkill', '/PID', str(int(pid)), '/T', '/F'], capture_output=True, timeout=15, **hidden())
        else:
            os.kill(int(pid), 15)
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def port_owner(port):
    """The process id listening on 127.0.0.1:<port>, or None. Only needed to find a 1.0 server."""
    try:
        if WINDOWS:
            out = subprocess.run(['netstat', '-ano', '-p', 'TCP'], capture_output=True, text=True, timeout=15, **hidden()).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(f':{port}') and parts[3] == 'LISTENING':
                    return int(parts[4])
        elif shutil.which('lsof'):
            out = subprocess.run(['lsof', '-nP', f'-iTCP:{port}', '-sTCP:LISTEN', '-t'], capture_output=True, text=True, timeout=15).stdout
            return int(out.split()[0]) if out.split() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


# --- files and windows -------------------------------------------------------------
FILE_MANAGER = 'File Explorer' if WINDOWS else 'Finder' if MAC else 'the file manager'


def open_path(path):
    """Open a file or folder with the app the system uses for it."""
    if WINDOWS:
        os.startfile(str(path))
    elif MAC:
        subprocess.Popen(['open', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(['xdg-open', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reveal(path):
    """Show a file selected in its folder."""
    if WINDOWS:
        subprocess.Popen(f'explorer /select,"{path}"')
    elif MAC:
        subprocess.Popen(['open', '-R', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        open_path(Path(path).parent if Path(path).is_file() else path)


def _app_browser():
    """A Chromium browser that can show a page as its own app window, as an argv prefix, or None."""
    if WINDOWS:
        for base in (os.environ.get('ProgramFiles(x86)', ''), os.environ.get('ProgramFiles', '')):
            edge = Path(base) / 'Microsoft/Edge/Application/msedge.exe'
            if base and edge.exists():
                return [str(edge)]
        return None
    if MAC:
        for app in ('Google Chrome', 'Microsoft Edge', 'Brave Browser', 'Chromium'):
            for folder in (Path('/Applications'), HOME / 'Applications'):
                if (folder / f'{app}.app').exists():
                    return ['open', '-na', str(folder / f'{app}.app'), '--args']
        return None
    for name in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'microsoft-edge', 'brave-browser'):
        if shutil.which(name):
            return [shutil.which(name)]
    return None


def open_window(url):
    """Open Crewroom as its own window when a Chromium browser is installed, else in the default browser."""
    browser = _app_browser()
    if browser:
        try:
            subprocess.Popen(browser + [f'--app={url}', '--window-size=1280,860'], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **detached())
            return
        except OSError:
            pass
    import webbrowser
    webbrowser.open(url)


# --- finding the agents ------------------------------------------------------------
def candidates(name):
    """Usual install places for a command-line tool. Apps opened from the Dock or a launcher get a short PATH,
    so looking only at PATH misses tools a terminal would find."""
    found = [shutil.which(name)]
    dirs = [HOME / '.local' / 'bin', HOME / '.npm-global' / 'bin', HOME / 'bin', HOME / '.bun' / 'bin',
            Path('/opt/homebrew/bin'), Path('/usr/local/bin'), Path('/usr/bin')]
    if name == 'claude':
        dirs.insert(0, HOME / '.claude' / 'local')
    found += [str(d / name) for d in dirs]
    nvm = sorted((HOME / '.nvm' / 'versions' / 'node').glob(f'*/bin/{name}'), reverse=True)
    found += [str(p) for p in nvm]
    return [p for p in dict.fromkeys(found) if p and Path(p).is_file() and os.access(p, os.X_OK)]


def command_line(pid):
    """The command line a process was started with, or ''. Lets `team status` name a 1.0 server's folder."""
    try:
        if WINDOWS:
            return subprocess.run(['powershell', '-NoProfile', '-Command',
                f'(Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}").CommandLine'],
                capture_output=True, text=True, timeout=15, **hidden()).stdout.strip()
        return subprocess.run(['ps', '-o', 'command=', '-p', str(int(pid))], capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return ''


OLD_WINDOWS_DATA = Path(os.environ.get('LOCALAPPDATA', HOME)) / 'TeamChat'  # Crewroom 1.0's mailbox


def appdata_redirected():
    """True when this process runs inside a packaged app (for example the installer started from Claude Code),
    where Windows sends AppData writes to the app's private copy. Shortcuts made there never reach the Start menu."""
    if not WINDOWS:
        return False
    import uuid
    roaming = Path(os.environ.get('APPDATA', HOME / 'AppData' / 'Roaming'))
    packages = Path(os.environ.get('LOCALAPPDATA', HOME / 'AppData' / 'Local')) / 'Packages'
    probe = roaming / f'crewroom-probe-{uuid.uuid4().hex[:8]}'
    try:
        probe.write_text('', encoding='utf-8')
        return any(packages.glob(f'*/LocalCache/Roaming/{probe.name}'))
    except OSError:
        return False
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def pick_folder(start=None, title='Choose a folder'):
    """Show the system's own folder picker on this computer and return the chosen path, or None if cancelled.
    The window can't open a native dialog with a real path itself, so the Crewroom server does it for it."""
    start = str(start or HOME)
    try:
        if WINDOWS:
            # Windows won't let a background program bring a window to the front, so the picker would open behind
            # the Crewroom window. Joining the input of the window in front (AttachThreadInput) lifts that for a moment;
            # a hidden top-most owner window then keeps the picker on top.
            script = ('Add-Type -AssemblyName System.Windows.Forms; '
                      'Add-Type -Namespace CR -Name Fg -MemberDefinition \''
                      '[DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); '
                      '[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr p); '
                      '[DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId(); '
                      '[DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool on); '
                      '[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); '
                      '[DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);\'; '
                      '$o = New-Object System.Windows.Forms.Form -Property @{TopMost=$true; ShowInTaskbar=$false; Opacity=0; '
                      'StartPosition="CenterScreen"; Width=1; Height=1}; $o.Show(); '
                      '$front = [CR.Fg]::GetWindowThreadProcessId([CR.Fg]::GetForegroundWindow(), [IntPtr]::Zero); '
                      '$me = [CR.Fg]::GetCurrentThreadId(); [void][CR.Fg]::AttachThreadInput($me, $front, $true); '
                      '[void][CR.Fg]::BringWindowToTop($o.Handle); [void][CR.Fg]::SetForegroundWindow($o.Handle); $o.Activate(); '
                      '[void][CR.Fg]::AttachThreadInput($me, $front, $false); '
                      '$d = New-Object System.Windows.Forms.FolderBrowserDialog; '
                      '$d.Description = $env:CR_TITLE; $d.SelectedPath = $env:CR_START; $d.ShowNewFolderButton = $true; '
                      'if ($d.ShowDialog($o) -eq "OK") { [Console]::OutputEncoding = [Text.Encoding]::UTF8; $d.SelectedPath }')
            out = subprocess.run(['powershell', '-NoProfile', '-STA', '-Command', script], capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=900, env={**os.environ, 'CR_TITLE': title, 'CR_START': start},
                                 **hidden()).stdout.strip()
        elif MAC:
            out = subprocess.run(['osascript', '-e', f'POSIX path of (choose folder with prompt {json_quote(title)} '
                                  f'default location (POSIX file {json_quote(start)}))'],
                                 capture_output=True, text=True, timeout=900).stdout.strip()
        elif shutil.which('zenity'):
            out = subprocess.run(['zenity', '--file-selection', '--directory', '--title', title, '--filename', start.rstrip('/') + '/'],
                                 capture_output=True, text=True, timeout=900).stdout.strip()
        elif shutil.which('kdialog'):
            out = subprocess.run(['kdialog', '--getexistingdirectory', start, '--title', title],
                                 capture_output=True, text=True, timeout=900).stdout.strip()
        else:
            raise OSError('No folder picker found on this computer (install zenity), so type the folder path instead.')
    except subprocess.TimeoutExpired:
        return None
    out = out.splitlines()[-1].strip() if out else ''
    return out.rstrip('/') if out and Path(out).is_dir() else None


def json_quote(text):
    """A string literal for AppleScript (same escaping rules as JSON for our purposes)."""
    import json
    return json.dumps(str(text))
