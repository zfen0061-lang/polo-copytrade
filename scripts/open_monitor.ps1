$ErrorActionPreference='Stop'
$monitorRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$monitorPython=Join-Path $monitorRoot '.venv\Scripts\pythonw.exe'
if(-not (Test-Path -LiteralPath $monitorPython)){throw 'Run setup.cmd first.'}
$ready=$false
try{$state=Invoke-RestMethod 'http://127.0.0.1:8765/api/runtime/state' -TimeoutSec 3;$ready=$state.mode -eq 'read_only_monitor' -and $state.backend_healthy}catch{}
if(-not $ready){
  $task=Get-ScheduledTask -TaskName 'PoloCopyTrade-ReadOnlyMonitor' -ErrorAction SilentlyContinue
  if($task -and @($task.Actions|Where-Object {$_.WorkingDirectory -eq $monitorRoot}).Count){Start-ScheduledTask -TaskName $task.TaskName}
  else{Start-Process -FilePath $monitorPython -ArgumentList '-m backend.supervisor' -WorkingDirectory $monitorRoot -WindowStyle Hidden}
}
Start-Process 'http://127.0.0.1:8765'
