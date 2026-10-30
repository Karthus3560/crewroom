# Remove what install.ps1 added: the "team" skill and the Desktop shortcut. Double-click uninstall.cmd to run it.
# A skill that was there before Crewroom (SKILL.md.bak) is put back. Your data (%LOCALAPPDATA%\TeamChat) is kept;
# delete that folder yourself if you want it gone.
param([string]$UserHome = $env:USERPROFILE, [string]$Desktop = [Environment]::GetFolderPath('Desktop'))
foreach ($dir in @("$UserHome\.claude\skills\team-chat", "$UserHome\.agents\skills\team-chat")) {
    if (Test-Path "$dir\SKILL.md.bak") { Move-Item -Force "$dir\SKILL.md.bak" "$dir\SKILL.md"; Write-Host "Restored your earlier skill in $dir" }
    elseif (Test-Path $dir) { Remove-Item -Recurse -Force $dir; Write-Host "Removed $dir" }
}
$lnk = Join-Path $Desktop 'Crewroom.lnk'
if (Test-Path $lnk) { Remove-Item -Force $lnk; Write-Host "Removed $lnk" }
Write-Host 'Crewroom is uninstalled. Your data is still in %LOCALAPPDATA%\TeamChat.'
