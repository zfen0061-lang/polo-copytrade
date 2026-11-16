param([switch]$NoBrowser)
$ErrorActionPreference='Stop'
$realRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$realPython=Join-Path $realRoot '.venv\Scripts\python.exe'
$realPythonWindowless=Join-Path $realRoot '.venv\Scripts\pythonw.exe'
try {
    if(-not (Test-Path -LiteralPath $realPython)){throw 'Run setup.cmd first.'}
    # Only start tasks belonging to this installation. Their HTTP servers start
    # without arming trading; this launcher never calls an execution endpoint.
    $realData=Join-Path $realRoot 'data\real-v2\studio.sqlite3'
    $sourceData=Join-Path $realRoot 'data\studio.sqlite3'
    $expectedRealArguments='-m backend.server --real-v2 --port 8767 --data "'+$realData+'" --source-data "'+$sourceData+'"'
    $hasRealTask=$false
    foreach($entry in @(
        @{Name='PoloCopyTrade-ReadOnlyMonitor';Arguments=('-m backend.supervisor --data "'+$sourceData+'"')},
        @{Name='PoloCopyTrade-RealWorkspace';Arguments=$expectedRealArguments}
    )) {
        $task=Get-ScheduledTask -TaskName $entry.Name -ErrorAction SilentlyContinue
        if($task) {
            $actions=@($task.Actions)
            if($actions.Count -ne 1 -or $actions[0].WorkingDirectory -ne $realRoot -or
               $actions[0].Execute -ne $realPythonWindowless -or $actions[0].Arguments -ne $entry.Arguments) {
                throw ('The saved task belongs to a different installation: '+$entry.Name)
            }
            if($entry.Name -eq 'PoloCopyTrade-RealWorkspace'){$hasRealTask=$true}
            if($task.State -ne 'Running'){Start-ScheduledTask -TaskName $entry.Name}
        }
    }
    $sha=[System.Security.Cryptography.SHA256]::Create()
    try {
        $workspaceId=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($realData.ToLowerInvariant())))).Replace('-','').ToLowerInvariant().Substring(0,16)
    } finally {$sha.Dispose()}
    function Get-RealWorkspaceReady {
        try {$reply=Invoke-WebRequest 'http://127.0.0.1:8767/api/real-v2/state' -UseBasicParsing -TimeoutSec 2}
        catch {return $false}
        $state=$reply.Content | ConvertFrom-Json
        if($reply.Headers['Server'] -notlike 'PoloCopyTrade/*' -or $state.workspace_id -ne $workspaceId -or
           $state.endpoint -ne 'https://fapi.binance.com' -or $state.connection_role -ne 'dedicated_trading') {
            throw 'Port 8767 belongs to a different workspace. No browser was opened.'
        }
        return $true
    }
    if(-not (Get-RealWorkspaceReady)) {
        if(-not $hasRealTask) {
            Start-Process -FilePath $realPythonWindowless -ArgumentList '-m backend.real_connect --no-browser' -WorkingDirectory $realRoot -WindowStyle Hidden
        }
        $ready=$false
        for($attempt=0;$attempt -lt 30;$attempt++) {
            if(Get-RealWorkspaceReady){$ready=$true;break}
            Start-Sleep -Milliseconds 300
        }
        if(-not $ready){throw 'The production workspace could not be opened. Check data\real-v2\workspace.log.'}
    }
    Write-Output 'Verified production workspace: http://127.0.0.1:8767/ (no execution start requested)'
    if(-not $NoBrowser){Start-Process 'http://127.0.0.1:8767/'}
} catch {
    if(-not $NoBrowser) {
        $popup=New-Object -ComObject WScript.Shell
        $null=$popup.Popup($_.Exception.Message,0,'Polo CopyTrade',16)
    }
    throw
}
