# Setting up your agents

Crewroom doesn't come with an AI of its own: your team members are the coding agents on your computer, each
signed in with **your own** account and plan. You need at least one. This guide shows, for each agent, how to
install it, sign in, check that it works, and add it to a Crewroom team.

| Agent | What it brings | Account it uses | Command |
|---|---|---|---|
| [Claude Code](#claude-code) | Code, writing, reviews; reads your notes mid-task | Claude (Pro, Max, Team) | `claude` |
| [Codex](#codex) | Code, shell checks, builds, **image generation** | ChatGPT (Plus, Pro, Business) | `codex` |
| [Cursor Agent](#cursor-agent) | Code and refactors with many models; **Auto** picks one per task | Cursor | `agent` |
| [Antigravity CLI](#antigravity-cli) | Google's agent: Gemini, plus Claude and GPT-OSS models | Google account (free tier included) | `agy` |

After installing or signing in to an agent, open Crewroom, click the **bottom-left corner → Setup check**, and
press **Check again**: every agent it finds gets a green tick. Agents are found automatically; there is nothing
to configure in Crewroom.

> **Windows tip:** after installing a command-line tool, open a **new** PowerShell window before using it, so it
> picks up the updated PATH. Run installs and sign-ins in a normal PowerShell window from the Start menu, not
> inside another app's terminal.

---

## Claude Code

**Install** (pick one):
- The **Claude app** from [claude.ai/download](https://claude.ai/download): open it once and switch to the **Code** tab. Crewroom uses the Claude Code that comes with it.
- Or Claude Code on its own:
  - Windows (PowerShell): `irm https://claude.ai/install.ps1 | iex`
  - macOS / Linux: `curl -fsSL https://claude.ai/install.sh | bash`

**Sign in:** in the Claude app, or run `claude` once and follow the browser sign-in.

**Check:** `claude --version`

**In Crewroom:** Claude members edit files. Tick **Can run commands** on a member to let it run checks, builds and
renders too (common destructive commands such as `git push`, `rm -rf` and `Remove-Item` are refused).
Notes you send while a Claude member works reach it between steps.

---

## Codex

**Install** (pick one):
- The **Codex app** from [chatgpt.com/codex](https://chatgpt.com/codex). Crewroom uses the Codex that comes with it, and its chats show in the app.
- Or the Codex CLI: `npm install -g @openai/codex` (needs [Node.js](https://nodejs.org)).

**Sign in:** in the Codex app, or run `codex login`.

**Check:** `codex --version`

**In Crewroom:** Codex members work in Codex's own workspace sandbox and can generate images with your ChatGPT
plan. Notes you send while a Codex member works reach it mid-task.

---

## Cursor Agent

The Cursor editor alone isn't enough: Crewroom needs Cursor's **command-line agent**, a separate small install.

**Install:**
- Windows (PowerShell): `irm 'https://cursor.com/install?win32=true' | iex`
- macOS / Linux: `curl https://cursor.com/install -fsS | bash`

It installs a command called `agent` (also `cursor-agent`), in `%LOCALAPPDATA%\cursor-agent` on Windows and
`~/.local/bin` on macOS and Linux.

**Sign in** (separate from the Cursor app's sign-in, needed once):

```
agent login
```

It opens your browser; approve with the same account you use in Cursor.

**Check:**

```
agent status        (should say: Logged in as you@example.com)
agent models        (lists the models your plan offers)
```

**In Crewroom:**
- Pick **Add a Cursor member** in the team dialog.
- **Model:** leave **Auto** to let Cursor pick a fitting model for each request. Auto is cheapest in its *Cost* setting; Cursor bills its other settings, and any model you pick yourself, at that model's price.
- **Can run commands:** off by default. Cursor members then edit files only; tick it to let them run commands too.
- Notes you send while a Cursor member works reach it **right after** the current request, as a follow-up.

**Troubleshooting:**
- *"Not logged in"*: run `agent login` again.
- *Windows: `'C:\Users\YOUR' is not recognized`*: Cursor's own launcher can't handle a space in your Windows user name. Crewroom doesn't use that launcher, so members still work; in a terminal, run `cursor-agent.ps1` instead.

---

## Antigravity CLI

Google's Antigravity comes in several forms: the **Antigravity 2.0 app**, the **Antigravity IDE**, an SDK, and
the **Antigravity CLI** (`agy`). Crewroom uses the CLI. The desktop apps can't take work from other programs.
The CLI replaced Gemini CLI for personal Google accounts on 18 June 2026, so use `agy` rather than `gemini`.

**Install:**
- Windows (PowerShell): `irm https://antigravity.google/cli/install.ps1 | iex`  (or `winget install Google.AntigravityCLI`)
- macOS / Linux: `curl -fsSL https://antigravity.google/cli/install.sh | bash`

It installs `agy` (in `%LOCALAPPDATA%\agy\bin` on Windows).

**Sign in:** run `agy` once. The first time it opens Google sign-in in your browser (over SSH it prints a link and
a code instead). The free tier includes Gemini Flash models plus Claude Sonnet and Opus and GPT-OSS, with weekly
limits; Google AI Pro and Ultra raise them.

**Check:**

```
agy --version
agy models          (lists the models your account can use)
```

**In Crewroom:**
- Pick **Add an Antigravity member** in the team dialog, and choose a model (for example Gemini 3.8 Flash, or Claude Sonnet 4.6).
- Members edit files; tick **Can run commands** to let them run commands too (in Antigravity's terminal sandbox, with destructive commands refused).
- Notes you send while an Antigravity member works reach it **right after** the current request, as a follow-up.

**Troubleshooting:**
- *"Matches user-configured deny rule"* when you use `agy` yourself: your `~/.gemini/antigravity-cli/settings.json` has `permissions.deny` rules. Remove the ones you don't want. Crewroom members are not affected: Crewroom grants file access for its own runs only, without changing that file.
- *Gemini CLI says your account isn't supported*: expected since June 2026 for personal accounts; use `agy`.

---

## The `team` skill

The Crewroom installer gives each agent the **team** skill, so you can say things like *"ask Codex to make an
icon and tell me when it's done"* in a chat you have open yourself:

| Agent | Where the skill goes |
|---|---|
| Claude Code | `~/.claude/skills/team-chat` |
| Codex, Antigravity | `~/.agents/skills/team-chat` |
| Cursor | `~/.cursor/skills/team-chat` |

Start a **new** chat after installing: chats that were already open don't see new skills. Codex, Cursor and
Antigravity say who they are with `--as codex`, `--as cursor` or `--as antigravity`; the skill tells them to.

Installed an agent after Crewroom? Run the Crewroom installer again (on Windows, run CrewroomSetup.exe again) so
the skill reaches it too.
