[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet("false", "true")]
    [string]$JobSubmissionsEnabled,
    [Parameter(Mandatory)]
    [int]$ActiveWorkerAttempts,
    [Parameter(Mandatory)]
    [int]$NonterminalJobs,
    [Parameter(Mandatory)]
    [int]$UnresolvedProviderSubmissions,
    [Parameter(Mandatory)]
    [int]$OutstandingOutboxPublications,
    [Parameter(Mandatory)]
    [int]$ActiveQueueMessages,
    [Parameter(Mandatory)]
    [int]$ScheduledQueueMessages,
    [Parameter(Mandatory)]
    [bool]$QueueSendersVerified,
    [Parameter(Mandatory)]
    [ValidateSet("Running", "Stopped", "Succeeded", "Failed", "Terminated")]
    [string]$WorkerState,
    [Parameter(Mandatory)]
    [bool]$BootstrapContractMatches
)

$ErrorActionPreference = "Stop"

if ($JobSubmissionsEnabled -ne "false") {
    throw "JOB_SUBMISSIONS_ENABLED must remain false."
}

if ($ActiveWorkerAttempts -ne 0) {
    throw "A worker still holds a valid job lease."
}

if ($NonterminalJobs -ne 0 -or $UnresolvedProviderSubmissions -ne 0 -or $OutstandingOutboxPublications -ne 0) {
    throw "Database work is not quiescent."
}

if ($ActiveQueueMessages -ne 0 -or $ScheduledQueueMessages -ne 0) {
    throw "The worker queues are not idle."
}

if (-not $QueueSendersVerified) {
    throw "Queue senders are not limited to the reviewed runtime identities."
}

if (-not $BootstrapContractMatches) {
    throw "The ACI bootstrap contract does not match the reviewed release configuration."
}

switch ($WorkerState) {
    "Stopped" { "recreate" }
    "Succeeded" { "recreate" }
    "Failed" { "recreate" }
    "Terminated" { "recreate" }
    "Running" {
        "stop_and_recreate"
    }
}
