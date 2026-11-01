#!/bin/sh
# Remove Crewroom's skill and launcher. Your chats are kept.   (macOS: double-click "Uninstall Crewroom.command")
exec sh "$(dirname "$0")/install.sh" --uninstall "$@"
