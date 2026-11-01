#!/bin/sh
# macOS: double-click to remove Crewroom's skill and app. Your chats are kept.
exec sh "$(dirname "$0")/install.sh" --uninstall "$@"
