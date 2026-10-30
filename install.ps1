# Crewroom installer (Windows). Double-click install.cmd, or: powershell -ExecutionPolicy Bypass -File install.ps1
# It changes nothing outside these places:
#   %USERPROFILE%\.claude\skills\team-chat   and   %USERPROFILE%\.agents\skills\team-chat   (the "team" skill;
#   an existing SKILL.md there is kept as SKILL.md.bak)
#   a "Crewroom" shortcut on your Desktop
# Your data stays in %LOCALAPPDATA%\TeamChat. Double-click uninstall.cmd to remove the skill and the shortcut.
# Moved this folder or updated Python? Run it again.
param([string]$UserHome = $env:USERPROFILE, [string]$Desktop = [Environment]::GetFolderPath('Desktop'))  # override both to test safely
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'                    # paths with Arabic or other non-Latin letters survive the pipe
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Root = $PSScriptRoot
Write-Host ''
Write-Host '  Crewroom installer' -ForegroundColor DarkYellow
Write-Host ''

if ($Root.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host '  This folder is temporary (it looks like you opened the zip without extracting it).' -ForegroundColor Red
    Write-Host '  Right-click the zip, choose "Extract All", move the folder somewhere permanent (e.g. Documents), and run install.cmd there.'
    exit 1
}

# 1. Python 3.10+ (the py launcher first, then python on PATH)
$python = $null
$launcher = $null
$ErrorActionPreference = 'Continue'                # a warning on stderr must not hide a working Python
foreach ($c in @(@{ exe = 'py'; args = @('-3') }, @{ exe = 'python'; args = @() })) {
    if (-not (Get-Command $c.exe -ErrorAction SilentlyContinue)) { continue }
    $v = & $c.exe @($c.args) -c "import sys; print(sys.executable); print(sys.version_info >= (3, 10))" 2>$null
    if ($LASTEXITCODE -eq 0 -and $v -and $v.Count -ge 2 -and $v[1] -eq 'True') {
        $python = $v[0].Trim(); $launcher = (@($c.exe) + $c.args) -join ' '; break
    }
}
$ErrorActionPreference = 'Stop'
if (-not $python) {
    Write-Host '  Python 3.10 or newer is needed. Get it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run this again.' -ForegroundColor Red
    exit 1
}
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { $pythonw = $python }
Write-Host "  Python:   $python"

# 2. The "team" skill for Claude Code and Codex, pointing at this folder
$skill = Get-Content -Raw -Encoding UTF8 (Join-Path $Root 'skill\team-chat\SKILL.md')
$skill = $skill.Replace('{{TEAM_COMMAND}}', "$launcher `"$Root\team.py`"")  # 'py -3' or 'python', whichever this PC has
$utf8 = New-Object System.Text.UTF8Encoding $false
foreach ($dir in @("$UserHome\.claude\skills\team-chat", "$UserHome\.agents\skills\team-chat")) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $file = Join-Path $dir 'SKILL.md'
    if ((Test-Path $file) -and ((Get-Content -Raw -Encoding UTF8 $file) -ne $skill)) { Copy-Item -Force $file "$file.bak" }
    [System.IO.File]::WriteAllText($file, $skill, $utf8)
    Write-Host "  Skill:    $dir"
}

# 3. Desktop shortcut
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $Desktop 'Crewroom.lnk'))
$lnk.TargetPath = $pythonw
$lnk.Arguments = "`"$Root\TeamChat.pyw`""
$lnk.WorkingDirectory = $Root
$lnk.IconLocation = "$Root\web\assets\app-icon.ico"
$lnk.Description = 'Crewroom: your AI team, together'
$lnk.Save()
Write-Host "  Shortcut: $Desktop\Crewroom.lnk"

# 4. Which agents can this PC run? (the folder is passed as an argument, so any characters in it are safe)
$found = & $python -c "import sys; sys.path.insert(0, sys.argv[1]); from teamchat import paths; print('yes' if paths.find_claude() else 'no'); print('yes' if paths.find_codex() else 'no')" $Root
Write-Host ''
if ($found -and $found.Count -ge 2) {
    if ($found[0] -eq 'yes') { Write-Host '  Claude Code: found' -ForegroundColor Green }
    else { Write-Host '  Claude Code: not found. Open the Claude app once and switch to the Code tab, or install Claude Code (claude.ai/code), then sign in.' -ForegroundColor Yellow }
    if ($found[1] -eq 'yes') { Write-Host '  Codex:       found' -ForegroundColor Green }
    else { Write-Host '  Codex:       not found. Install the Codex app (chatgpt.com/codex) or the Codex CLI, then sign in.' -ForegroundColor Yellow }
} else {
    Write-Host '  Could not check for Claude Code and Codex; Crewroom will tell you if one is missing.' -ForegroundColor Yellow
}
Write-Host ''
Write-Host '  Done. Open "Crewroom" on your Desktop.' -ForegroundColor Green
Write-Host ''
