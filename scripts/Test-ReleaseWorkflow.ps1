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
    "AZURE_COMPUTE_DEPLOYMENTS_ENABLED",
    'RELEASE_CONTROLLER_AZURE_MUTATIONS_ENABLED: "false"',
    "DEPLOYMENT_DATABASE_URL",
    "worker_release_active_attempt_count",
    "az servicebus queue show",
    "QueueSendersVerified",
    "does not match the reviewed bootstrap contract",
    "secureEnvironmentVariables[].name",
    "has no recoverable immutable backend image",
    "az acr repository show",
    "Refusing to overwrite existing",
    "az webapp config container set",
    "az container create",
    "az containerapp update",
    "Partial release",
    "Deployment prerequisite missing",
    "API health check did not succeed",
    "Database migrations: not run by this workflow"
)

foreach ($fragment in $requiredFragments) {
    if (-not $workflow.Contains($fragment)) {
        throw "Release workflow is missing required safety control: $fragment"
    }
}

$deployJobMatch = [regex]::Match(
    $workflow,
    '(?ms)^  deploy-development:\r?\n(?<body>.*?)(?=^  [A-Za-z0-9_-]+:|\z)'
)
if (-not $deployJobMatch.Success) {
    throw "Could not find the deploy-development workflow job."
}

$deployJob = $deployJobMatch.Groups["body"].Value
if ($deployJob -notmatch '(?m)^    needs: \[changes, backend, backend-image, backend-postgres, frontend, terraform, release-safety\]\r?$') {
    throw "Deploy must wait for the complete validation job set."
}

foreach ($requiredDeployControl in @(
    "always()",
    "needs.changes.result == 'success'",
    "needs.changes.outputs.application == 'true'"
)) {
    if (-not $deployJob.Contains($requiredDeployControl)) {
        throw "Deploy is missing required dependency control: $requiredDeployControl"
    }
}

foreach ($job in @("backend", "backend-image", "backend-postgres", "frontend", "terraform")) {
    $expectedCondition = "needs.$job.result == 'success' || needs.$job.result == 'skipped'"
    if (-not $deployJob.Contains($expectedCondition)) {
        throw "Deploy must allow an unaffected $job job to be skipped without allowing failures."
    }
}

if (-not $deployJob.Contains("needs.release-safety.result == 'success'")) {
    throw "Deploy must require the release-safety job to succeed."
}

function Test-DeploymentEligibility {
    param(
        [string]$EventName,
        [string]$Ref,
        [string]$ChangesResult,
        [string]$ApplicationChanged,
        [string]$BackendResult,
        [string]$BackendImageResult,
        [string]$BackendPostgresResult,
        [string]$FrontendResult,
        [string]$TerraformResult,
        [string]$ReleaseSafetyResult
    )

    if ($EventName -notin @("push", "workflow_dispatch") -or $Ref -ne "refs/heads/main") {
        return $false
    }
    if ($ChangesResult -ne "success" -or $ApplicationChanged -ne "true") {
        return $false
    }
    if ($ReleaseSafetyResult -ne "success") {
        return $false
    }
    foreach ($result in @($BackendResult, $BackendImageResult, $FrontendResult, $TerraformResult)) {
        if ($result -notin @("success", "skipped")) {
            return $false
        }
    }
    if ($BackendPostgresResult -eq "skipped") {
        return $BackendResult -eq "skipped" -and $BackendImageResult -eq "skipped"
    }
    if ($BackendPostgresResult -ne "success") {
        return $false
    }
    return $true
}

function Assert-DeploymentEligibility {
    param([bool]$Expected, [hashtable]$Scenario)

    $actual = Test-DeploymentEligibility @Scenario
    if ($actual -ne $Expected) {
        throw "Unexpected deployment eligibility for scenario: $($Scenario | ConvertTo-Json -Compress)"
    }
}

$eligiblePush = @{
    EventName = "push"; Ref = "refs/heads/main"; ChangesResult = "success"; ApplicationChanged = "true"
    BackendResult = "success"; BackendImageResult = "success"; BackendPostgresResult = "success"; FrontendResult = "skipped"
    TerraformResult = "skipped"; ReleaseSafetyResult = "success"
}
Assert-DeploymentEligibility -Expected $true -Scenario $eligiblePush

$frontendOnlyPush = $eligiblePush.Clone()
$frontendOnlyPush.BackendResult = "skipped"; $frontendOnlyPush.BackendImageResult = "skipped"
$frontendOnlyPush.BackendPostgresResult = "skipped"
$frontendOnlyPush.FrontendResult = "success"
Assert-DeploymentEligibility -Expected $true -Scenario $frontendOnlyPush

$documentationOnlyPush = $eligiblePush.Clone(); $documentationOnlyPush.ApplicationChanged = "false"
Assert-DeploymentEligibility -Expected $false -Scenario $documentationOnlyPush

$failedBackend = $eligiblePush.Clone(); $failedBackend.BackendResult = "failure"
Assert-DeploymentEligibility -Expected $false -Scenario $failedBackend

$failedPostgres = $eligiblePush.Clone(); $failedPostgres.BackendPostgresResult = "failure"
Assert-DeploymentEligibility -Expected $false -Scenario $failedPostgres

$cancelledPostgres = $eligiblePush.Clone(); $cancelledPostgres.BackendPostgresResult = "cancelled"
Assert-DeploymentEligibility -Expected $false -Scenario $cancelledPostgres

$unexpectedSkippedPostgres = $eligiblePush.Clone(); $unexpectedSkippedPostgres.BackendPostgresResult = "skipped"
Assert-DeploymentEligibility -Expected $false -Scenario $unexpectedSkippedPostgres

$cancelledFrontend = $eligiblePush.Clone(); $cancelledFrontend.FrontendResult = "cancelled"
Assert-DeploymentEligibility -Expected $false -Scenario $cancelledFrontend

$failedReleaseSafety = $eligiblePush.Clone(); $failedReleaseSafety.ReleaseSafetyResult = "failure"
Assert-DeploymentEligibility -Expected $false -Scenario $failedReleaseSafety

$cancelledChanges = $eligiblePush.Clone(); $cancelledChanges.ChangesResult = "cancelled"
Assert-DeploymentEligibility -Expected $false -Scenario $cancelledChanges

$manualRollback = $eligiblePush.Clone(); $manualRollback.EventName = "workflow_dispatch"
Assert-DeploymentEligibility -Expected $true -Scenario $manualRollback

function Get-ReleaseMode {
    param([string]$EventName, [string]$ComputeDeploymentsEnabled, [string]$ControllerMutationsEnabled = "false")

    if ($ComputeDeploymentsEnabled -eq "true" -and $ControllerMutationsEnabled -eq "true") {
        return "deploy"
    }
    if ($EventName -eq "workflow_dispatch") {
        return "reject"
    }
    return "disabled"
}

if ((Get-ReleaseMode -EventName "push" -ComputeDeploymentsEnabled "false") -ne "disabled") {
    throw "A push during intentional compute downtime must report a disabled deployment."
}
if ((Get-ReleaseMode -EventName "workflow_dispatch" -ComputeDeploymentsEnabled "false") -ne "reject") {
    throw "A manual rollback during intentional compute downtime must fail."
}
if ((Get-ReleaseMode -EventName "workflow_dispatch" -ComputeDeploymentsEnabled "true") -ne "reject") {
    throw "A repository variable alone must not activate Azure mutations."
}

if ($workflow.Contains('echo "skip=true" >> "$GITHUB_OUTPUT"')) {
    throw "Missing compute must fail the deployment prerequisite instead of reporting a successful skip."
}

$releaseModeMatch = [regex]::Match(
    $workflow,
    '(?ms)^      - name: Check release mode\r?\n(?<body>.*?)(?=^      - name:|\z)'
)
if (-not $releaseModeMatch.Success) {
    throw "Could not find the release-mode workflow step."
}

$releaseMode = $releaseModeMatch.Groups["body"].Value
foreach ($requiredModeControl in @(
    'AZURE_COMPUTE_DEPLOYMENTS_ENABLED',
    'EVENT_NAME',
    'workflow_dispatch',
    'echo "enabled=false"',
    'Azure deployment intentionally disabled',
    'exit 1'
)) {
    if (-not $releaseMode.Contains($requiredModeControl)) {
        throw "Release mode is missing required control: $requiredModeControl"
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

if (-not $migration.Contains("SET search_path = pg_catalog")) {
    throw "Worker release gate must use a fixed pg_catalog search path."
}

$coordinationMigrationPath = Join-Path $PSScriptRoot "..\supabase\migrations\20261102000000_durable_worker_release_coordination.sql"
$coordinationMigration = Get-Content -LiteralPath $coordinationMigrationPath -Raw
foreach ($fragment in @("worker_release_state", "worker_release_try_acquire_attempt", "release_blocked", "worker_release_recover")) {
    if (-not $coordinationMigration.Contains($fragment)) {
        throw "Durable worker release coordination migration is missing: $fragment"
    }
}

$githubActionsPath = Join-Path $PSScriptRoot "..\infra\terraform\shared\github_actions.tf"
$githubActions = Get-Content -LiteralPath $githubActionsPath -Raw
foreach ($roleName in @("Container Apps Contributor", "Azure Container Instances Contributor Role")) {
    if (-not $githubActions.Contains("role_definition_name = `"$roleName`"")) {
        throw "GitHub deployment RBAC is missing the official Azure role name: $roleName"
    }
}
foreach ($invalidRoleName in @("Container App Contributor", "Container Instance Contributor")) {
    if ($githubActions.Contains("role_definition_name = `"$invalidRoleName`"")) {
        throw "GitHub deployment RBAC still uses the invalid Azure role name: $invalidRoleName"
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
