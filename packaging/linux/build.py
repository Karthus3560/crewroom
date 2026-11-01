"""Build dist/crewroom-<version>-linux.tar.gz: Crewroom for Linux, installed per user with one command.

    python packaging/linux/build.py        (works on Windows, macOS or Linux)

Its install.sh copies the program to ~/.local/lib/crewroom (always the same place, so a newer package updates
it in place), adds Crewroom to the apps menu and sets up the team skill. Uses the system's Python 3.10+.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import DIST, Archive, app_files, version  # noqa: E402

FIND_PYTHON = r'''PY=""
for p in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys, sqlite3; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$(command -v "$p")"; break
  fi
done'''

INSTALL = r'''#!/bin/sh
# Install or update Crewroom for this user:   sh install.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/lib/crewroom"
''' + FIND_PYTHON + r'''
if [ -z "$PY" ]; then
  echo
  echo "  Crewroom needs Python 3.10 or newer (with sqlite3). Install it with your package manager, for example:"
  echo "    Ubuntu/Debian: sudo apt install python3      Fedora: sudo dnf install python3      Arch: sudo pacman -S python"
  echo "  Then run this again."
  exit 1
fi

echo
echo "  Crewroom {v} installer"
echo
if [ -f "$DEST/team.py" ]; then
  echo "  Crewroom is already installed in $DEST: updating it."
  "$PY" "$DEST/team.py" stop >/dev/null 2>&1 || true
fi
mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST.new"
cp -R "$HERE/app" "$DEST.new"
rm -rf "$DEST"
mv "$DEST.new" "$DEST"
"$PY" "$DEST/install.py" --from-app

echo "  Installed Crewroom {v} in $DEST"
echo "  Python:     $PY"
echo "  Your chats: ${{XDG_DATA_HOME:-$HOME/.local/share}}/crewroom"
echo
echo "  Open it:    Crewroom in your apps menu, or: \"$PY\" \"$DEST/TeamChat.pyw\""
echo "  Update:     download the new package and run its install.sh. It replaces this one."
echo "  Uninstall:  in Crewroom click the bottom-left corner, then Uninstall. Or: sh \"$DEST/uninstall.sh\""
echo
if [ -t 0 ]; then
  printf "  Open Crewroom now? [Y/n] "
  read answer || answer=""
  case "$answer" in [nN]*) ;; *) nohup "$PY" "$DEST/TeamChat.pyw" >/dev/null 2>&1 & ;; esac
fi
'''

UNINSTALL = r'''#!/bin/sh
# Remove Crewroom: the team skill, the apps-menu entry and this program folder. Your chats are kept.
DIR="$(cd "$(dirname "$0")" && pwd)"
''' + FIND_PYTHON + r'''
[ -n "$PY" ] && "$PY" "$DIR/install.py" --uninstall --from-app
if [ "$DIR" = "$HOME/.local/lib/crewroom" ]; then
  rm -rf "$DIR"
  echo "  Removed $DIR"
fi
echo "  Your chats are still in ${XDG_DATA_HOME:-$HOME/.local/share}/crewroom. Delete that folder if you don't want them."
'''

README = '''Crewroom {v} for Linux

Install or update:   sh install.sh
  Copies Crewroom to ~/.local/lib/crewroom, adds it to your apps menu and sets up the team skill for Claude
  Code and Codex. Running a newer package's install.sh updates it in place. Needs Python 3.10+.

Uninstall: in Crewroom click the bottom-left corner, then Uninstall. Or: sh ~/.local/lib/crewroom/uninstall.sh
Your chats stay in ~/.local/share/crewroom.
'''


def main():
    v = version()
    top = f'crewroom-{v}-linux'
    a = Archive()
    a.add(f'{top}/install.sh', INSTALL.replace('{v}', v).replace('{{', '{').replace('}}', '}'), executable=True)
    a.add(f'{top}/README.txt', README.format(v=v))
    a.add(f'{top}/app/uninstall.sh', UNINSTALL, executable=True)
    for rel, data in app_files():
        a.add(f'{top}/app/{rel}', data)
    DIST.mkdir(exist_ok=True)
    out = DIST / f'{top}.tar.gz'
    a.tar(out)
    print(f'{out} ({out.stat().st_size / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
