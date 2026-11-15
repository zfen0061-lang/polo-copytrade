$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskPython=Join-Path $taskRoot '.venv\Scripts\pythonw.exe'
if(-not (Test-Path -LiteralPath $taskPython)){throw 'Run setup.cmd first.'}
$taskData=Join-Path $taskRoot 'data\studio.sqlite3'
$taskUser=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskName='PoloCopyTrade-ReadOnlyMonitor'
$existing=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if($existing -and (@($existing.Actions|Where-Object {$_.WorkingDirectory -ne $taskRoot}).Count -gt 0)){
  throw 'A task with this name belongs to another installation. It was not replaced.'
}
$action=New-ScheduledTaskAction -Execute $taskPython -Argument ('-m backend.supervisor --data "'+$taskData+'"') -WorkingDirectory $taskRoot
$trigger=New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$principal=New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Read-only signal monitor. Optional Windows user-encrypted connection recovery. No automatic trading.' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Output 'Read-only monitor login task installed and started. No trading is enabled.'
