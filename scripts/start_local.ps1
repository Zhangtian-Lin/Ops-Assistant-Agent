[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $workspaceRoot '.venv\Scripts\python.exe'
$modeFile = Join-Path $workspaceRoot 'config\security_mode.yaml'
$policyFile = Join-Path $workspaceRoot 'config\identity_policy.yaml'
$llmFile = Join-Path $workspaceRoot 'config\llm.yaml'
$runtimeDir = Join-Path $workspaceRoot 'data\runtime'
$brokerStdoutLog = Join-Path $runtimeDir 'broker.stdout.log'
$brokerStderrLog = Join-Path $runtimeDir 'broker.stderr.log'
$brokerReadyFile = Join-Path $runtimeDir 'broker.ready'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment was not found: $python"
}

if (-not (Test-Path -LiteralPath $llmFile)) {
    & $python (Join-Path $workspaceRoot 'scripts\configure_llm.py')
    if ($LASTEXITCODE -ne 0) {
        throw 'LLM initialization was not completed; Agent was not started.'
    }
}

function Get-BrokerDiagnostic {
    $parts = @()
    foreach ($logFile in @($brokerStderrLog, $brokerStdoutLog)) {
        if (Test-Path -LiteralPath $logFile) {
            $content = Get-Content -LiteralPath $logFile -Raw
            if ($null -ne $content -and $content.Trim()) {
                $parts += $content.Trim()
            }
        }
    }
    return ($parts -join [Environment]::NewLine)
}

if (-not ((Test-Path -LiteralPath $modeFile) -and (Test-Path -LiteralPath $policyFile))) {
    Write-Host ''
    Write-Host 'Security mode is not initialized.'
    Write-Host '1) Single-user controlled mode'
    Write-Host '2) Multi-user separation mode (operator and approver need different Windows SIDs)'
    $choice = Read-Host 'Select 1 or 2'
    if ($choice -eq '1') {
        & $python (Join-Path $workspaceRoot 'scripts\initialize_security.py') --mode single_user_controlled
    }
    elseif ($choice -eq '2') {
        $operatorSid = Read-Host 'Operator Windows SID'
        $approverSid = Read-Host 'Approver Windows SID'
        & $python (Join-Path $workspaceRoot 'scripts\initialize_security.py') --mode multi_user_separation --operator-sid $operatorSid --approver-sid $approverSid
    }
    else {
        throw 'No valid security mode was selected; Agent was not started.'
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'Security-mode initialization failed; Agent was not started.'
    }
}

$startedBroker = $false
if (Test-Path -LiteralPath $brokerReadyFile) {
    Write-Host 'An existing Broker was found and will be reused.'
}
else {
    Write-Host 'Starting Broker in the background...'
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    Remove-Item -LiteralPath $brokerReadyFile -Force -ErrorAction SilentlyContinue
    $broker = Start-Process -FilePath $python -ArgumentList 'scripts\run_broker.py' -WorkingDirectory $workspaceRoot -WindowStyle Hidden -RedirectStandardOutput $brokerStdoutLog -RedirectStandardError $brokerStderrLog -PassThru
    $startedBroker = $true
    $ready = $false
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        Start-Sleep -Milliseconds 250
        if (Test-Path -LiteralPath $brokerReadyFile) {
            $ready = $true
            break
        }
        if ($broker.HasExited) {
            $diagnostic = Get-BrokerDiagnostic
            throw "Broker exited during startup (exit code $($broker.ExitCode)). $diagnostic"
        }
    }
    if (-not $ready) {
        Stop-Process -Id $broker.Id -ErrorAction SilentlyContinue
        $diagnostic = Get-BrokerDiagnostic
        throw "Broker did not become ready within 5 seconds. $diagnostic"
    }
}

try {
    Write-Host 'Broker is ready. Starting Agent.'
    & $python (Join-Path $workspaceRoot 'agent.py')
}
finally {
    if ($startedBroker -and -not $broker.HasExited) {
        Write-Host 'Stopping the Broker started by this launcher...'
        Stop-Process -Id $broker.Id -ErrorAction SilentlyContinue
    }
}
