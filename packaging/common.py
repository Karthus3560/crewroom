"""Shared by the macOS and Linux package builds: which files make up the program, and zips/tarballs that keep
Unix permissions (built on Windows, the files themselves carry no "can run" bit)."""
import io
import tarfile
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / 'dist'
APP_FILES = ['teamchat', 'web', 'skill', 'team.py', 'serve.py', 'TeamChat.pyw', 'install.py', 'README.md', 'LICENSE']
SKIP = {'__pycache__', '.pytest_cache'}


def version():
    for line in (REPO / 'teamchat' / '__init__.py').read_text(encoding='utf-8').splitlines():
        if line.startswith('__version__'):
            return line.split('=', 1)[1].strip().strip('\'"')
    raise SystemExit('No __version__ in teamchat/__init__.py')


def app_files():
    """(relative path, bytes) for every file of the program."""
    for name in APP_FILES:
        src = REPO / name
        for p in ([src] if src.is_file() else sorted(src.rglob('*'))):
            if p.is_file() and not SKIP & set(p.parts) and p.suffix != '.pyc':
                yield p.relative_to(REPO).as_posix(), p.read_bytes()


class Archive:
    """Collects files with Unix modes, then writes a .zip (macOS) or .tar.gz (Linux)."""

    def __init__(self):
        self.items = []  # (path, bytes, mode)

    def add(self, path, data, executable=False):
        if isinstance(data, str):
            data = data.encode('utf-8')
        if executable:
            assert b'\r\n' not in data, f'{path} has Windows line endings and would not run'
        self.items.append((path, data, 0o755 if executable else 0o644))

    def zip(self, out):
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for path, data, mode in self.items:
                info = zipfile.ZipInfo(path, time.localtime()[:6])
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3  # Unix, so macOS's Archive Utility keeps the modes
                info.external_attr = (0o100000 | mode) << 16
                z.writestr(info, data)

    def tar(self, out):
        with tarfile.open(out, 'w:gz', compresslevel=9) as t:
            dirs = sorted({'/'.join(p.split('/')[:i]) for p, _, _ in self.items for i in range(1, p.count('/') + 1)})
            for d in dirs:
                info = tarfile.TarInfo(d)
                info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o755, time.time()
                t.addfile(info)
            for path, data, mode in self.items:
                info = tarfile.TarInfo(path)
                info.size, info.mode, info.mtime = len(data), mode, time.time()
                t.addfile(info, io.BytesIO(data))
