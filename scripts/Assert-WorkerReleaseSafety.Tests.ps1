[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$gate = Join-Path $PSScriptRoot "Assert-WorkerReleaseSafety.ps1"

function Assert-GateSucceeds {
    param([string]$ExpectedAction, [hashtable]$Parameters)

    $result = & $gate @Parameters
    if ($result -ne $ExpectedAction) {
        throw "Expected $ExpectedAction but received '$result'."
    }
}

function Assert-GateFails {
    param([hashtable]$Parameters)

    $failed = $false
    try {
        & $gate @Parameters | Out-Null
    } catch {
        $failed = $true
    }
    if (-not $failed) {
        throw "Expected the worker release gate to fail."
    }
}

$idleParameters = @{
    JobSubmissionsEnabled    = "false"
    ActiveWorkerAttempts     = 0
    ActiveQueueMessages      = 0
    ScheduledQueueMessages   = 0
    QueueSendersVerified     = $true
    BootstrapContractMatches = $true
}

$parameters = $idleParameters.Clone(); $parameters.WorkerState = "Running"
Assert-GateSucceeds -ExpectedAction "update" -Parameters $parameters
$parameters = $idleParameters.Clone(); $parameters.WorkerState = "Stopped"
Assert-GateSucceeds -ExpectedAction "recreate" -Parameters $parameters
$parameters = $idleParameters.Clone(); $parameters.WorkerState = "Running"; $parameters.ActiveWorkerAttempts = 1
Assert-GateFails -Parameters $parameters
$parameters = $idleParameters.Clone(); $parameters.WorkerState = "Running"; $parameters.ScheduledQueueMessages = 1
Assert-GateFails -Parameters $parameters
$parameters = $idleParameters.Clone(); $parameters.WorkerState = "Running"; $parameters.BootstrapContractMatches = $false
Assert-GateFails -Parameters $parameters
$parameters = $idleParameters.Clone(); $parameters.WorkerState = "Running"; $parameters.QueueSendersVerified = $false
Assert-GateFails -Parameters $parameters

Write-Output "Worker release safety gate tests passed."
