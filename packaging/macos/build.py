"""Build dist/Crewroom-<version>-macOS.zip: Crewroom.app, a normal Mac app you drag into Applications.

    python packaging/macos/build.py        (works on Windows, macOS or Linux)

The app is a small launcher plus Crewroom's Python code in Contents/Resources/app. It uses Python 3.10+ from
python.org or Homebrew, and if there is none it says so and offers the python.org download. Each time it opens it
re-points the team skill at itself, so moving or replacing the app (that's how you update) just works.
"""
import io
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import DIST, REPO, Archive, app_files, version  # noqa: E402

LAUNCHER = r'''#!/bin/sh
# Crewroom.app: find Python 3.10+, keep the team skill pointing at this app, then open the Crewroom window.
APP="$(cd "$(dirname "$0")/../.." && pwd)"
RES="$APP/Contents/Resources"
LOGS="$HOME/Library/Application Support/Crewroom/logs"
mkdir -p "$LOGS"

alert() {
  osascript -e "display dialog \"$1\" with title \"Crewroom\" buttons {\"OK\"} default button \"OK\" with icon caution" >/dev/null 2>&1
}

case "$APP" in
  */AppTranslocation/*|/Volumes/*)
    alert "Please move Crewroom into your Applications folder, then open it from there. (Apps opened straight from Downloads run from a temporary place on macOS, so Claude and Codex could not find Crewroom later.)"
    open "$HOME/Downloads" 2>/dev/null
    exit 1;;
esac

PY=""
for p in "$RES/python/bin/python3" /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 "$HOME/.pyenv/shims/python3"; do
  if [ -x "$p" ] && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then PY="$p"; break; fi
done
if [ -z "$PY" ]; then
  answer=$(osascript -e 'button returned of (display dialog "Crewroom needs Python 3.10 or newer (free). Install it from python.org: choose the macOS installer. Then open Crewroom again." with title "Crewroom" buttons {"Cancel", "Get Python"} default button "Get Python" with icon caution)' 2>/dev/null)
  [ "$answer" = "Get Python" ] && open "https://www.python.org/downloads/macos/"
  exit 1
fi

"$PY" "$RES/app/install.py" --from-app >> "$LOGS/app.log" 2>&1
exec "$PY" "$RES/app/TeamChat.pyw"
'''

PLIST = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Crewroom</string>
<key>CFBundleDisplayName</key><string>Crewroom</string>
<key>CFBundleIdentifier</key><string>io.github.karthus3560.crewroom</string>
<key>CFBundleVersion</key><string>{v}</string>
<key>CFBundleShortVersionString</key><string>{v}</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleExecutable</key><string>Crewroom</string>
<key>CFBundleIconFile</key><string>Crewroom</string>
<key>LSMinimumSystemVersion</key><string>11.0</string>
<key>LSUIElement</key><true/>
<key>NSHumanReadableCopyright</key><string>MIT licence. Designed by Ghaith Saad Jawad.</string>
</dict></plist>
'''

README = '''Crewroom {v} for macOS

1. Drag Crewroom into your Applications folder.
2. Open it from Applications (or press Cmd+Space and type Crewroom).
   The first time, macOS may say it can't check the app: right-click Crewroom, choose Open, then Open again.
3. Crewroom needs Python 3.10 or newer. If it isn't on your Mac, Crewroom offers the python.org download.

Update: drag the new Crewroom into Applications and choose Replace.
Uninstall: in Crewroom click the bottom-left corner, then Uninstall; then drag Crewroom to the Trash.
Your chats stay in ~/Library/Application Support/Crewroom.
'''


def icns():
    from PIL import Image  # build-time only
    out = io.BytesIO()
    Image.open(REPO / 'web' / 'assets' / 'app-icon.png').convert('RGBA').save(out, format='ICNS')
    return out.getvalue()


def main():
    v = version()
    a = Archive()
    base = 'Crewroom.app/Contents'
    a.add(f'{base}/Info.plist', PLIST.format(v=v))
    a.add(f'{base}/MacOS/Crewroom', LAUNCHER, executable=True)
    a.add(f'{base}/Resources/Crewroom.icns', icns())
    for rel, data in app_files():
        a.add(f'{base}/Resources/app/{rel}', data)
    a.add('Read me.txt', README.format(v=v))
    DIST.mkdir(exist_ok=True)
    out = DIST / f'Crewroom-{v}-macOS.zip'
    a.zip(out)
    shutil.copy2(out, DIST / 'Crewroom-macOS.zip')  # the name the website links to
    print(f'{out} ({out.stat().st_size / 1e6:.1f} MB), also as Crewroom-macOS.zip')


if __name__ == '__main__':
    main()
