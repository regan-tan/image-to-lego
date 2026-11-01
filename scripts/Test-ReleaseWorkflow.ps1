[CmdletBinding()]
param(
    [string]$WorkflowPath
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($WorkflowPath)) {
    $WorkflowPath = Join-Path $PSScriptRoot "..\\.github\\workflows\\ci.yml"
}

if (-not (Test-Path -LiteralPath $WorkflowPath -PathType Leaf)) {
    throw "Release workflow was not found: $WorkflowPath"
}

$workflow = Get-Content -LiteralPath $WorkflowPath -Raw
$requiredFragments = @(
    "id-token: write",
    "github.event_name == 'push' && github.ref == 'refs/heads/main'",
    "group: azure-development-deployment",
    "cancel-in-progress: false",
    "JOB_SUBMISSIONS_ENABLED must remain false",
    "ACI_WORKER_RELEASES_ENABLED",
    "DEPLOYMENT_DATABASE_URL",
    "worker_release_active_attempt_count",
    "az servicebus queue show",
    "QueueSendersVerified",
    "does not match the reviewed bootstrap contract",
    "az acr repository show",
    "Refusing to overwrite existing",
    "az webapp config container set",
    "az container create",
    "az containerapp update",
    "Partial release",
    "API health check did not succeed",
    "Database migrations: not run by this workflow"
)

foreach ($fragment in $requiredFragments) {
    if (-not $workflow.Contains($fragment)) {
        throw "Release workflow is missing required safety control: $fragment"
    }
}

if ($workflow -match "terraform\s+apply") {
    throw "Image deployment must not run Terraform apply."
}

if ($workflow -match "supabase\s+db\s+push|supabase\s+migration|alembic\s+upgrade") {
    throw "Database migrations must remain separate from automatic image deployment."
}

$migrationPath = Join-Path $PSScriptRoot "..\supabase\migrations\20261101000000_worker_release_gate.sql"
$migration = Get-Content -LiteralPath $migrationPath -Raw
foreach ($fragment in @("SECURITY DEFINER", "REVOKE ALL", "github_release_gate")) {
    if (-not $migration.Contains($fragment)) {
        throw "Worker release gate migration is missing: $fragment"
    }
}

$sharedVariablesPath = Join-Path $PSScriptRoot "..\infra\terraform\shared\variables.tf"
$sharedExamplePath = Join-Path $PSScriptRoot "..\infra\terraform\shared\dev.tfvars.example"
$sharedVariables = Get-Content -LiteralPath $sharedVariablesPath -Raw
$sharedExample = Get-Content -LiteralPath $sharedExamplePath -Raw
$verifiedSubject = "repo:regan-tan@108611909/image-to-lego@1406660565:ref:refs/heads/main"
if (-not $sharedVariables.Contains('variable "github_oidc_subject"') -or -not $sharedExample.Contains($verifiedSubject)) {
    throw "The shared Terraform OIDC subject is not the verified immutable repository subject."
}

Write-Output "Release workflow safety checks passed."
