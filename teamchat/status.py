"""Which Crewroom is installed, which one is running, and how to stop it.

Shared by the launcher, the installer and `team status`, so they always tell the same story.
"""
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__, paths, system


def url(port=None):
    return f'http://127.0.0.1:{port or paths.PORT}/'


def ping(port=None):
    """What the server on the port says about itself, or None if nothing answers. Crewroom 1.0 says only
    {'ok': True, 'app': 'teamchat'}; 1.1 and later add version, root and pid."""
    try:
        with urllib.request.urlopen(url(port) + 'api/ping', timeout=1.5) as r:
            data = json.load(r)
            return data if data.get('app') == 'teamchat' else None
    except (OSError, ValueError):
        return None


def installed():
    """The install record written by install.py, or None."""
    try:
        return json.loads(paths.INSTALL.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def version_of(root):
    """The version of a Crewroom folder, read from its files (folders from before 1.1 have no version line)."""
    try:
        for line in (Path(root) / 'teamchat' / '__init__.py').read_text(encoding='utf-8').splitlines():
            if line.startswith('__version__'):
                return line.split('=', 1)[1].strip().strip('\'"')
    except OSError:
        return None
    return '1.0'


def running_root(info, port=None):
    """The folder the running server came from. 1.0 servers don't say, so read it from the process."""
    if info.get('root'):
        return info['root']
    pid = system.port_owner(port or paths.PORT)
    found = re.search(r'([^"\']*?)[\\/]serve\.py', system.command_line(pid) if pid else '')
    return found.group(1).strip() if found else None


def same(a, b):
    return bool(a and b) and Path(a).resolve() == Path(b).resolve()


def stop(port=None, wait=10):
    """Stop the Crewroom server on the port. Background requests that are already running keep going.
    Returns True when nothing answers any more."""
    info = ping(port)
    if not info:
        return True
    req = urllib.request.Request(url(port) + 'api/shutdown', data=b'{}', method='POST',
                                 headers={'Content-Type': 'application/json', 'Origin': url(port).rstrip('/')})
    try:
        urllib.request.urlopen(req, timeout=3).close()
    except urllib.error.HTTPError:  # 1.0 has no Stop: end its process instead
        pid = info.get('pid') or system.port_owner(port or paths.PORT)
        if pid:
            system.stop(pid)
    except OSError:
        pass
    end = time.time() + wait
    while time.time() < end:
        if not ping(port):
            return True
        time.sleep(0.2)
    return False


def report():
    """Plain-language lines for `team status`."""
    rec = installed()
    run = ping()
    lines = [f'This copy:   Crewroom {__version__} in {paths.ROOT}']
    if rec:
        lines.append(f"Installed:   Crewroom {rec.get('version', '?')} in {rec.get('root')}"
                     + ('' if same(rec.get('root'), paths.ROOT) else '   <- a different folder'))
    else:
        lines.append('Installed:   no install record (run the installer in the folder you want to keep)')
    if run:
        where = running_root(run) or 'a folder Crewroom could not find'
        lines.append(f"Running:     Crewroom {run.get('version', '1.0')} from {where} at {url()}"
                     + ('' if same(where, paths.ROOT) else '   <- a different folder'))
    else:
        lines.append('Running:     no (open Crewroom to start it)')
    lines.append(f'Data:        {paths.DATA}')
    lines.append(f'Uninstall:   {uninstall_hint(rec.get("root") if rec else paths.ROOT)}')
    return lines


def uninstall_hint(root):
    rec = installed() or {}
    if rec.get('installer') == 'setup':
        return 'Windows Settings > Apps > Installed apps > Crewroom > Uninstall (or Control Panel > Programs)'
    root = Path(root)
    if system.WINDOWS:
        return f'double-click uninstall.cmd in {root}'
    if system.MAC:
        return f'double-click "Uninstall Crewroom.command" in {root}'
    return f'run: sh "{root / "uninstall.sh"}"'
