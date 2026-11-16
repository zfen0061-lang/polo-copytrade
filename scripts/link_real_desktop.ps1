param([switch]$Plan)
$ErrorActionPreference='Stop'
$realRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$realLauncher=Join-Path $realRoot 'scripts\open_real_workspace.ps1'
$realIcon=Join-Path $realRoot 'frontend\polo.ico'
$desktopPath=[Environment]::GetFolderPath('Desktop')
$shortcutPath=Join-Path $desktopPath 'Polo CopyTrade.lnk'
$shellPath=Join-Path $PSHOME 'powershell.exe'
$shortcutArguments='-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "'+$realLauncher+'"'
if(-not (Test-Path -LiteralPath (Join-Path $realRoot '.venv\Scripts\python.exe'))){throw 'Run setup.cmd first.'}
if(-not (Test-Path -LiteralPath $realLauncher)){throw 'The production workspace launcher is missing.'}
if($Plan) {
    [pscustomobject]@{Shortcut=$shortcutPath;Target=$shellPath;Arguments=$shortcutArguments;Url='http://127.0.0.1:8767/';EnablesTrading=$false} | ConvertTo-Json
    return
}
# Run by the user. Preserve the old shortcut so the change is reversible.
if(Test-Path -LiteralPath $shortcutPath) {
    $backupPath=Join-Path $desktopPath ('Polo CopyTrade.previous-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')+'.lnk')
    Copy-Item -LiteralPath $shortcutPath -Destination $backupPath
}
$shellObject=New-Object -ComObject WScript.Shell
$shortcut=$shellObject.CreateShortcut($shortcutPath)
$shortcut.TargetPath=$shellPath
$shortcut.Arguments=$shortcutArguments
$shortcut.WorkingDirectory=$realRoot
if(Test-Path -LiteralPath $realIcon){$shortcut.IconLocation=$realIcon+',0'}
$shortcut.WindowStyle=7
$shortcut.Description='Polo CopyTrade - dedicated production workspace (8767); opening does not enable orders'
$shortcut.Save()
if(-not (Test-Path -LiteralPath $shortcutPath)){throw 'The desktop shortcut could not be saved.'}
Write-Output 'Desktop shortcut updated: Polo CopyTrade -> http://127.0.0.1:8767/'
Write-Output 'No keys changed. No order placed. Start automatic following explicitly in the dashboard.'
