"""Entry point: `python team.py ask codex "Make 6 icons" --run`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from teamchat.cli import main  # noqa: E402

sys.exit(main())
