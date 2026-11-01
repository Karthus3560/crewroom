"""Work on Crewroom's window next to the installed Crewroom:   python dev.py

Starts a development copy from this folder on port 47801 (same data, no Supervisor, no tray icon) unless it is
already running, and opens it as its own app window. The window reloads by itself when anything in web/ changes;
after changing Python files, stop the copy (team stop, with TEAMCHAT_PORT=47801) and run this again.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from teamchat import status, system  # noqa: E402

PORT = 47801
info = status.ping(PORT)
if info and not status.same(info.get('root'), ROOT):
    sys.exit(f"Port {PORT} is used by another Crewroom ({info.get('root')}). Stop it first.")
if not info:
    subprocess.Popen([system.background_python(), str(ROOT / 'serve.py'), str(PORT), '--dev'], cwd=str(ROOT),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **system.detached())
    for _ in range(80):
        if status.ping(PORT):
            break
        time.sleep(0.1)
system.open_window(status.url(PORT))
print(f'Crewroom (dev) at {status.url(PORT)}')
