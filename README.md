<p align="center"><img src="docs/assets/share-cover.png" alt="Crewroom: your AI team, together" width="860"></p>

# Crewroom

**Your AI team, together.** Crewroom turns Claude Code, OpenAI Codex, Cursor and Google Antigravity into one team on your computer (Windows, macOS or Linux). They hand work to each other, results land in one chat, and you lead.

▶ **[Watch the video (2:23) and see the site](https://karthus3560.github.io/crewroom/)**

## What it does
- **Hire a crew per project:** any mix of Claude and Codex members, each with its own roles, model and colour, and its own ongoing chat.
- **Real hand-offs:** an agent runs `team ask codex "Make 2 app icons" --run` and keeps working. When the job is done, the files and images land back in the chat. Codex askers get a note in their chat, and Claude waits with `team wait`.
- **Work in parallel:** different members work at the same time.
- **Producer:** write what you want in #general in plain words. The Producer sharpens it into orders and routes each one to the member that fits.
- **@mentions:** tag a member while it works. Codex and Claude both read your note between steps and adapt.
- **Safety net:**
  - While Crewroom is open, a Supervisor restarts a worker that died, retries a failure once, then asks for help.
  - When a hand-off chain runs too long, a Referee sorts it out, and anything past the limit waits for your OK. Nothing is dropped silently.
- **Your rules:** Claude members run commands only if you tick *Can run commands*. Common destructive ones (git push, rm -rf, Remove-Item, registry, shutdown) are refused. It's a guard-rail, not a sandbox. Codex works inside its own workspace sandbox.
- **One window:** projects, team chat with #general and #discussion, requests, galleries, and every agent's chat. Click a file path in a message to open it.

## Install

You need at least one agent, signed in with your own plan: **Claude Code**, **Codex**, **Cursor Agent** or the **Antigravity CLI**. The **[agent setup guide](AGENTS-SETUP.md)** shows how to install, sign in to and check each one.

### Windows 10/11
1. Download **[CrewroomSetup.exe](https://github.com/Karthus3560/crewroom/releases/latest)** and run it. Python is included; nothing else to install.
   Windows says *"Windows protected your PC"*? Click **More info → Run anyway** (the installer isn't code-signed yet).
2. Crewroom is now a normal program: in the Start menu and on the Desktop, and listed in **Settings → Apps → Installed apps**, where you uninstall it.
3. **Updating:** run the newer CrewroomSetup.exe. It closes Crewroom and updates the installed program in place; it never adds a second copy. You can delete the downloaded file afterwards.

### macOS (11 or newer)
1. You need **Python 3.10+** from [python.org](https://www.python.org/downloads/macos/) or `brew install python`. If it's missing, Crewroom says so and offers the download.
2. Download **Crewroom-macOS.zip** from the [latest release](https://github.com/Karthus3560/crewroom/releases/latest), open it, and drag **Crewroom** into **Applications**.
3. Open Crewroom from Applications (or Cmd+Space, "Crewroom"). The first time, macOS may say it can't check the app: right-click Crewroom, choose **Open**, then **Open** again.
   Each time it opens, Crewroom sets up the `team` skill for Claude and Codex.
- **Update:** drag the new Crewroom into Applications and choose **Replace**.
- **Uninstall:** in Crewroom click the bottom-left corner → **Uninstall**, then drag Crewroom to the Trash.

### Linux
1. You need **Python 3.10+** (Ubuntu/Debian: `sudo apt install python3`).
2. Download **crewroom-linux.tar.gz** from the [latest release](https://github.com/Karthus3560/crewroom/releases/latest), extract it, and run `sh install.sh` inside.
   It installs Crewroom for your user in `~/.local/lib/crewroom`, adds it to your apps menu and sets up the `team` skill.
- **Update:** run the newer package's `install.sh`. It replaces the installed Crewroom in place.
- **Uninstall:** in Crewroom click the bottom-left corner → **Uninstall**, or `sh ~/.local/lib/crewroom/uninstall.sh`.

### Running from a folder (any system)
The [Crewroom zip](https://github.com/Karthus3560/crewroom/releases/latest/download/crewroom.zip) runs from wherever you extract it (needs Python 3.10+): `install.cmd`, `Install Crewroom.command` or `sh install.sh`, and the matching uninstall. Handy for development; most people want the packages above.

### Then
Open **Crewroom**, press **＋ New**, pick a folder, hire your crew.

Then just tell an agent: *"ask Codex to make 6 cozy icons for this app and tell me when they're done."*

### Updating, and knowing what's installed
- **Already have Crewroom?** The installer tells you which version is installed and where, and asks before replacing it. Install a new version the same way; it stops the old one and takes its place.
- **Which copy is running?** The bottom-left corner of the window shows the version and folder. Click it to see where your data is, how to uninstall, or to **Stop** Crewroom. Or run `team status`.
- Opening Crewroom always opens the copy you clicked. If a different copy was running, it is stopped first.
- **Moved the folder or updated Python?** Run the installer again.
- **Uninstalling** removes the skill and the shortcut. Your chats are kept in the data folder (below).
- **Window says "can't reach this page"?** See `logs/server.log` in the data folder. Another program may be using port 47800.

## Good to know
- **Privacy:** it runs on your machine. The app listens on `127.0.0.1:47800` only, and your mailbox stays in the data folder: `%USERPROFILE%\.crewroom` on Windows (1.0 used `%LOCALAPPDATA%\TeamChat`), `~/Library/Application Support/Crewroom` on macOS, `~/.local/share/crewroom` on Linux. Agents use **your own** Claude and ChatGPT plans, and their work goes to those providers as usual.
- **No packages:** Python's standard library only. The window is Edge or Chrome in app mode, or your default browser.
- **Reading chats:** Crewroom only *reads* the apps' own chat files (`~\.claude\projects`, `~\.codex\sessions`). When you set up a team it writes `TEAM.md` into the project and points `AGENTS.md`/`CLAUDE.md` at it.
- **Tests:** from the Crewroom folder, `python -m unittest tests.test_team`

## Credits
Designed by **Ghaith Saad Jawad**. Built with a Crewroom crew: Claude (code, film) and ChatGPT via Codex (art). The launch video's music is "Pixel Dreams" by DJ Lofi.

MIT licence.

## Building the packages
- Windows: `python packaging/windows/build.py` makes `dist/CrewroomSetup-<version>.exe` (needs [Inno Setup 6](https://jrsoftware.org/isinfo.php); downloads Python's embeddable package once).
- macOS: `python packaging/macos/build.py` makes `dist/Crewroom-<version>-macOS.zip` (needs Pillow for the icon).
- Linux: `python packaging/linux/build.py` makes `dist/crewroom-<version>-linux.tar.gz`.
All three build on any system; the version comes from `teamchat/__init__.py`. Keep the AppId in `packaging/windows/crewroom.iss` unchanged forever: it is what makes a new installer update the installed Crewroom instead of adding a second one.
