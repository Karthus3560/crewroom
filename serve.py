"""Run the Team Chat server in the foreground: `python serve.py [port]`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from teamchat import paths, server  # noqa: E402

server.serve(int(sys.argv[1]) if len(sys.argv) > 1 else paths.PORT)
