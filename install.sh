#!/bin/sh
# Install or update Crewroom on macOS or Linux: sh install.sh   (macOS: double-click "Install Crewroom.command")
cd "$(dirname "$0")" || exit 1
for p in python3.14 python3.13 python3.12 python3.11 python3.10 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    exec "$p" install.py "$@"
  fi
done
echo
echo "  Crewroom needs Python 3.10 or newer."
echo "  macOS: get it from https://www.python.org/downloads/macos/ (or: brew install python)"
echo "  Linux: install python3 with your package manager (for example: sudo apt install python3)"
echo "  Then run this again."
exit 1
