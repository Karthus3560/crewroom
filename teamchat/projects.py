"""Group folders into projects, so every request and app chat lands under the project it belongs to.

A project is the top folder you work in, e.g. Desktop\\Team Chat. A request in Desktop\\Team Chat\\web\\assets
and a Codex chat opened in Desktop\\Team Chat both belong to the "Team Chat" project.
"""
import hashlib
import os
from pathlib import Path

from . import system

HOME = Path.home()
# Folders whose direct children are projects.
CONTAINERS = [HOME / 'Desktop', HOME / 'OneDrive' / 'Desktop', HOME / 'Documents', HOME / 'Downloads',
              HOME / 'OneDrive' / 'Documents', HOME / 'source' / 'repos', HOME / 'Projects', HOME]
QUICK = HOME / 'Documents' / 'Codex'                 # Codex app's one-off chat folders
SCRATCH = system.scratch_dirs()

QUICK_KEY, SCRATCH_KEY, NONE_KEY = '~quick', '~scratch', '~none'
VIRTUAL = {QUICK_KEY: 'Codex quick chats', SCRATCH_KEY: 'Scratch & temporary', NONE_KEY: 'No folder'}


def _norm(p):
    return os.path.normcase(os.path.abspath(str(p)))


def _inside(path, folder):
    path, folder = _norm(path), _norm(folder)
    return path == folder or path.startswith(folder.rstrip('\\/') + os.sep)


_saved = {'roots': []}


def set_saved_roots(rows):
    """Projects made in Team Chat win over the folder guesses below (longest path first)."""
    _saved['roots'] = sorted(((r['root'], r['name']) for r in rows), key=lambda x: len(x[0]), reverse=True)


def root_of(cwd):
    """Return (key, name, root path or None) for a working folder."""
    if not cwd:
        return NONE_KEY, VIRTUAL[NONE_KEY], None
    path = Path(os.path.abspath(cwd))
    for root, name in _saved['roots']:
        if _inside(path, root):
            return key(root), name, root
    if _inside(path, QUICK):
        return QUICK_KEY, VIRTUAL[QUICK_KEY], None
    if any(_inside(path, s) for s in SCRATCH):
        return SCRATCH_KEY, VIRTUAL[SCRATCH_KEY], None
    for container in CONTAINERS:
        if _inside(path, container) and _norm(path) != _norm(container):
            rel = Path(os.path.relpath(path, container))
            root = Path(container) / rel.parts[0]
            return key(root), root.name, str(root)
    for root in codex_project_roots():
        if _inside(path, root):
            return key(root), Path(root).name, str(root)
    # Anything else (other drives, deep paths): the folder itself, minus generic sub-folders.
    while path.name.lower() in GENERIC and path.parent != path:
        path = path.parent
    return key(path), path.name or str(path), str(path)


GENERIC = {'assets', 'generated', 'images', 'img', 'src', 'web', 'public', 'static', 'build', 'dist', 'out',
           'output', 'outputs', 'docs', 'scripts', 'tests', 'icons', 'media', 'app', 'lib'}
_codex_roots = {'at': 0, 'value': []}


def codex_project_roots():
    """Project folders registered in the Codex app (read-only), longest first so nested ones win."""
    import sqlite3
    import time
    if time.time() - _codex_roots['at'] > 60:
        roots = []
        db = Path(os.environ.get('CODEX_HOME') or HOME / '.codex') / 'state_5.sqlite'
        try:
            con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=1)
            roots = [r[0] for r in con.execute('select path from project_roots') if r[0]]
            con.close()
        except sqlite3.Error:
            pass
        _codex_roots.update(at=time.time(), value=sorted(roots, key=len, reverse=True))
    return _codex_roots['value']


def key(root):
    return hashlib.sha1(_norm(root).encode()).hexdigest()[:12]


def group(requests, sessions, saved=()):
    """Build the project list shown in the left sidebar."""
    projects = {}
    for sp in saved:
        projects[sp['key']] = dict(key=sp['key'], name=sp['name'], root=sp['root'], virtual=False, saved=True,
                                   requests=0, open=0, chats=0, updated=_ts(sp.get('created')))

    def add(cwd, updated, kind):
        k, name, root = root_of(cwd)
        p = projects.setdefault(k, dict(key=k, name=name, root=root, virtual=k in VIRTUAL, saved=False,
                                        requests=0, open=0, chats=0, updated=0))
        p['updated'] = max(p['updated'], updated or 0)
        p[kind] += 1
        return p

    for r in requests:
        p = add(r.get('cwd'), _ts(r.get('updated')), 'requests')
        if r['status'] in ('asked', 'queued', 'working'):
            p['open'] += 1
    for s in sessions:
        add(s.get('cwd'), s.get('updated'), 'chats')
    return sorted(projects.values(), key=lambda p: (p['virtual'], -p['updated']))


def _ts(iso):
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return 0
