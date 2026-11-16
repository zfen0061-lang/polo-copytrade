$ErrorActionPreference='Stop'
$realRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$realPython=Join-Path $realRoot '.venv\Scripts\pythonw.exe'
if(-not (Test-Path -LiteralPath $realPython)){throw 'Run setup.cmd first.'}
$realUser=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$realTaskName='PoloCopyTrade-RealWorkspace'
$existing=Get-ScheduledTask -TaskName $realTaskName -ErrorAction SilentlyContinue
if($existing -and @($existing.Actions|Where-Object {$_.WorkingDirectory -ne $realRoot}).Count){throw 'Another installation owns this production workspace task.'}
$realData=Join-Path $realRoot 'data\real-v2\studio.sqlite3'
$realSource=Join-Path $realRoot 'data\studio.sqlite3'
$realArguments='-m backend.server --real-v2 --port 8767 --data "'+$realData+'" --source-data "'+$realSource+'"'
$realAction=New-ScheduledTaskAction -Execute $realPython -Argument $realArguments -WorkingDirectory $realRoot
$realPrincipal=New-ScheduledTaskPrincipal -UserId $realUser -LogonType Interactive -RunLevel Limited
$realSettings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $realTaskName -Action $realAction -Principal $realPrincipal -Settings $realSettings -Description 'Manual-start production workspace. Always disarmed on startup; no automatic execution restart.' -Force | Out-Null
Start-ScheduledTask -TaskName $realTaskName
Write-Output 'Independent production workspace started. Execution remains OFF until a reviewed local user start.'
