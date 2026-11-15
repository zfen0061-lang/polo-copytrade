$ErrorActionPreference='Stop'
$demoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$demoPython=Join-Path $demoRoot '.venv\Scripts\pythonw.exe'
if(-not (Test-Path -LiteralPath $demoPython)){throw 'Run setup.cmd first.'}
$demoUser=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$demoTaskName='PoloCopyTrade-DemoWorkspace'
$existing=Get-ScheduledTask -TaskName $demoTaskName -ErrorAction SilentlyContinue
if($existing -and @($existing.Actions|Where-Object {$_.WorkingDirectory -ne $demoRoot}).Count){throw 'Another installation owns this Demo task.'}
$demoAction=New-ScheduledTaskAction -Execute $demoPython -Argument '-m backend.demo_connect --preview --no-browser' -WorkingDirectory $demoRoot
$demoPrincipal=New-ScheduledTaskPrincipal -UserId $demoUser -LogonType Interactive -RunLevel Limited
$demoSettings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $demoTaskName -Action $demoAction -Principal $demoPrincipal -Settings $demoSettings -Description 'Manual-start Futures Demo workspace. No keys on disk, no automatic trading start or restart.' -Force | Out-Null
Start-ScheduledTask -TaskName $demoTaskName
Write-Output 'Credential-free Demo workspace started independently of the browser. Orders still require explicit Demo start.'
