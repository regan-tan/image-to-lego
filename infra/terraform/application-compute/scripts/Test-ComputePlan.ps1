[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$PlanPath,

    [Parameter(Mandatory)]
    [ValidateSet("reconcile", "destroy", "recovery", "workers")]
    [string]$Mode,

    [string]$ExpectedApiImageTag,

    [string]$TerraformExecutable = "terraform"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) {
    throw "Saved plan was not found: $PlanPath"
}

$planJson = & $TerraformExecutable show -json $PlanPath
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

$allComputeAddresses = @(
    "azurerm_service_plan.api",
    "azurerm_linux_web_app.api",
    "azurerm_container_group.generation_worker",
    "azurerm_container_group.conversion_worker",
    "azurerm_container_app.frontend"
)
$allowed = [System.Collections.Generic.HashSet[string]]::new([string[]]$allComputeAddresses)
$legacyApiImageTag = "dev-20261029-205014"

$managedChanges = @()
foreach ($change in @($resourceChangesProperty.Value)) {
    if ($null -eq $change.change -or $null -eq $change.change.actions) {
        throw "Terraform plan JSON contains an invalid resource change."
    }
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
    if (-not $allowed.Contains([string]$change.address)) {
        throw "Plan changes protected or unowned resource $($change.address). Stop."
    }
}

$expectedChangesByMode = @{
    "reconcile" = @{}
    "destroy" = @{
        "azurerm_service_plan.api" = @("delete")
        "azurerm_linux_web_app.api" = @("delete")
        "azurerm_container_group.generation_worker" = @("delete")
        "azurerm_container_group.conversion_worker" = @("delete")
        "azurerm_container_app.frontend" = @("delete")
    }
    "recovery" = @{
        "azurerm_service_plan.api" = @("create")
        "azurerm_linux_web_app.api" = @("create")
        "azurerm_container_app.frontend" = @("create")
    }
    "workers" = @{
        "azurerm_container_group.generation_worker" = @("create")
        "azurerm_container_group.conversion_worker" = @("create")
    }
}

$expectedChanges = $expectedChangesByMode[$Mode]
if ($managedChanges.Count -ne $expectedChanges.Count) {
    throw "Plan action count does not match the approved $Mode stage."
}

$seenAddresses = [System.Collections.Generic.HashSet[string]]::new()
foreach ($change in $managedChanges) {
    $address = [string]$change.address
    if (-not $seenAddresses.Add($address)) {
        throw "Plan changes $address more than once."
    }
    if (-not $expectedChanges.ContainsKey($address)) {
        throw "Plan changes $address, which is not approved for the $Mode stage."
    }
    $actualActions = @($change.change.actions)
    $expectedActions = @($expectedChanges[$address])
    if (($actualActions -join "`0") -ne ($expectedActions -join "`0")) {
        throw "Plan actions for $address do not match the approved $Mode stage."
    }
}

if ($Mode -eq "recovery") {
    if ([string]::IsNullOrWhiteSpace($ExpectedApiImageTag)) {
        throw "$Mode requires ExpectedApiImageTag from the approved image release record."
    }
    if ($ExpectedApiImageTag -eq $legacyApiImageTag) {
        throw "$Mode cannot use the legacy API image $legacyApiImageTag because it predates the submission gate."
    }
    $apiChange = $managedChanges | Where-Object address -eq "azurerm_linux_web_app.api"
    $imageName = [string]$apiChange.change.after.site_config[0].application_stack[0].docker_image_name
    if (-not $imageName.EndsWith(":$ExpectedApiImageTag", [System.StringComparison]::Ordinal)) {
        throw "$Mode API image does not match ExpectedApiImageTag."
    }
}

$addresses = @($managedChanges | ForEach-Object address | Sort-Object)
$actionCounts = @($managedChanges | Group-Object { $_.change.actions -join "," } | ForEach-Object {
    "$($_.Name):$($_.Count)"
} | Sort-Object)

switch ($Mode) {
    "reconcile" {
        if ($managedChanges.Count -ne 0) {
            throw "Reconciliation plan is not empty: $($addresses -join ', ')."
        }
    }
}

Write-Output "PLAN_GATE_OK mode=$Mode resources=$($addresses -join ',') actions=$($actionCounts -join ',')"
