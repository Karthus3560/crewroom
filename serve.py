"""Run the Crewroom server in the foreground: `python serve.py [port] [--dev]`.

--dev: a development copy next to the installed Crewroom (e.g. port 47801), on the same data, with no Supervisor
and no tray icon. Edit web/ and reload the page to see changes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from teamchat import paths, server  # noqa: E402

args = [a for a in sys.argv[1:] if a != '--dev']
server.serve(int(args[0]) if args else paths.PORT, dev='--dev' in sys.argv)
