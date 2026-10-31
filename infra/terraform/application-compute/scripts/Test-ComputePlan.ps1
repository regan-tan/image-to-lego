[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$PlanPath,

    [Parameter(Mandatory)]
    [ValidateSet("reconcile", "destroy", "recreate")]
    [string]$Mode
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) {
    throw "Saved plan was not found: $PlanPath"
}

$planJson = terraform show -json $PlanPath
if ($LASTEXITCODE -ne 0) {
    throw "Terraform could not read the saved plan."
}

try {
    $plan = $planJson | ConvertFrom-Json -ErrorAction Stop
} catch {
    throw "Terraform returned malformed plan JSON."
}

$resourceChangesProperty = $plan.PSObject.Properties["resource_changes"]
if ($null -eq $resourceChangesProperty -or $null -eq $resourceChangesProperty.Value) {
    throw "Terraform plan JSON is missing resource_changes."
}

$expectedAddresses = @(
    "azurerm_service_plan.api",
    "azurerm_linux_web_app.api",
    "azurerm_container_group.generation_worker",
    "azurerm_container_group.conversion_worker",
    "azurerm_container_app.frontend"
)
$expected = [System.Collections.Generic.HashSet[string]]::new([string[]]$expectedAddresses)

$managedChanges = @()
foreach ($change in @($resourceChangesProperty.Value)) {
    $actions = @($change.change.actions)
    if (
        $change.mode -ne "managed" -or
        [string]::IsNullOrWhiteSpace($change.address) -or
        $actions.Count -eq 0
    ) {
        throw "Terraform plan JSON contains an invalid resource change."
    }
    if ($actions -notcontains "no-op") {
        $managedChanges += $change
    }
}

foreach ($change in $managedChanges) {
    if (-not $expected.Contains([string]$change.address)) {
        throw "Plan changes protected or unowned resource $($change.address). Stop."
    }
}

$addresses = @($managedChanges | ForEach-Object address | Sort-Object -Unique)
$actions = @($managedChanges | ForEach-Object { $_.change.actions -join "," } | Sort-Object -Unique)

switch ($Mode) {
    "reconcile" {
        if ($managedChanges.Count -ne 0) {
            throw "Reconciliation plan is not empty: $($addresses -join ', ')."
        }
    }
    "destroy" {
        if (
            $managedChanges.Count -ne $expectedAddresses.Count -or
            (Compare-Object $expectedAddresses $addresses) -or
            ($managedChanges | Group-Object address | Where-Object Count -ne 1) -or
            $actions.Count -ne 1 -or $actions[0] -ne "delete"
        ) {
            throw "Destroy plan must delete exactly the five compute resources and nothing else."
        }
    }
    "recreate" {
        if (
            $managedChanges.Count -ne $expectedAddresses.Count -or
            (Compare-Object $expectedAddresses $addresses) -or
            ($managedChanges | Group-Object address | Where-Object Count -ne 1) -or
            $actions.Count -ne 1 -or $actions[0] -ne "create"
        ) {
            throw "Recreation plan must create exactly the five compute resources and nothing else."
        }
    }
}

Write-Output "PLAN_GATE_OK mode=$Mode resources=$($addresses -join ',') actions=$($actions -join ',')"
