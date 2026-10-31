[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ApprovedResourceId,

    [Parameter(Mandatory)]
    [ValidateSet("true", "false")]
    [string]$ExpectedCurrentValue,

    [Parameter(Mandatory)]
    [ValidateSet("true", "false")]
    [string]$DesiredValue,

    [Parameter(Mandatory)]
    [string]$ApprovalReference,

    [switch]$Apply
)

$ErrorActionPreference = "Stop"

$resourceGroupName = "rg-image-to-lego-dev"
$webAppName = "app-image-to-lego-api-dev-2b70703f"

$actualResourceId = az webapp show `
    --resource-group $resourceGroupName `
    --name $webAppName `
    --query id `
    --output tsv
if ($LASTEXITCODE -ne 0) {
    throw "Could not read the approved App Service target."
}
if ($actualResourceId -ne $ApprovedResourceId) {
    throw "App Service target does not match ApprovedResourceId."
}

$actualValue = az webapp config appsettings list `
    --resource-group $resourceGroupName `
    --name $webAppName `
    --query "[?name=='JOB_SUBMISSIONS_ENABLED'].value | [0]" `
    --output tsv
if ($LASTEXITCODE -ne 0) {
    throw "Could not read JOB_SUBMISSIONS_ENABLED."
}
if ($actualValue -ne $ExpectedCurrentValue) {
    throw "JOB_SUBMISSIONS_ENABLED does not match ExpectedCurrentValue."
}

if (-not $Apply) {
    Write-Output "JOB_SUBMISSIONS_OPERATION_READY approval=$ApprovalReference current=$actualValue desired=$DesiredValue"
    return
}

az webapp config appsettings set `
    --resource-group $resourceGroupName `
    --name $webAppName `
    --settings "JOB_SUBMISSIONS_ENABLED=$DesiredValue" `
    --output none
if ($LASTEXITCODE -ne 0) {
    throw "Could not set JOB_SUBMISSIONS_ENABLED."
}

$verifiedValue = az webapp config appsettings list `
    --resource-group $resourceGroupName `
    --name $webAppName `
    --query "[?name=='JOB_SUBMISSIONS_ENABLED'].value | [0]" `
    --output tsv
if ($LASTEXITCODE -ne 0 -or $verifiedValue -ne $DesiredValue) {
    throw "JOB_SUBMISSIONS_ENABLED was not verified after the App Service restart."
}

Write-Output "JOB_SUBMISSIONS_OPERATION_APPLIED approval=$ApprovalReference value=$verifiedValue"
