<p align="center"><img src="docs/assets/share-cover.png" alt="Crewroom: your AI team, together" width="860"></p>

# Crewroom

**Your AI team, together.** Crewroom turns Claude Code and OpenAI Codex into one team on your Windows PC. They hand work to each other, results land in one chat, and you lead.

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

## Install (Windows 10/11)
1. You need:
   - **Python 3.10+** from [python.org](https://www.python.org/downloads/). Tick *Add python.exe to PATH*.
   - at least one agent, signed in with your own plan: the **Claude** app ([claude.ai/download](https://claude.ai/download); open it once and switch to the **Code** tab) and/or the **Codex** app ([chatgpt.com/codex](https://chatgpt.com/codex)).
2. Download the latest **[Crewroom zip](https://github.com/Karthus3560/crewroom/releases/latest/download/crewroom-windows.zip)**. Right-click it, choose **Extract All**, and keep the folder somewhere permanent, for example `Documents\Crewroom`.
3. Double-click **`install.cmd`**. It adds the `team` skill to Claude and Codex and puts a **Crewroom** shortcut on your Desktop. If Windows says *"Windows protected your PC"*, click **More info → Run anyway**. It's an unsigned script, and you can read it first.
4. Open **Crewroom**, press **＋ New**, pick a folder, hire your crew.

Then just tell an agent: *"ask Codex to make 6 cozy icons for this app and tell me when they're done."*

To remove it, double-click `uninstall.cmd`. Your data in `%LOCALAPPDATA%\TeamChat` is kept.

**Moved the folder or updated Python?** Double-click `install.cmd` again.
**Window says "can't reach this page"?** See `%LOCALAPPDATA%\TeamChat\logs\server.log`. Another program may be using port 47800.

## Good to know
- **Privacy:** it runs on your machine. The app listens on `127.0.0.1:47800` only, and your mailbox stays in `%LOCALAPPDATA%\TeamChat`. Agents use **your own** Claude and ChatGPT plans, and their work goes to those providers as usual.
- **No packages:** Python's standard library only. The window is Microsoft Edge in app mode, or your default browser.
- **Reading chats:** Crewroom only *reads* the apps' own chat files (`~\.claude\projects`, `~\.codex\sessions`). When you set up a team it writes `TEAM.md` into the project and points `AGENTS.md`/`CLAUDE.md` at it.
- **Tests:** from the Crewroom folder, `python -m unittest tests.test_team`

## Credits
Designed by **Ghaith Saad Jawad**. Built with a Crewroom crew: Claude (code, film) and ChatGPT via Codex (art). The launch video's music is "Pixel Dreams" by DJ Lofi.

MIT licence.
