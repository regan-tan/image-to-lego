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
    "Could not pause new job submissions.",
    "Deployment must leave job submissions disabled.",
    "ACI_WORKER_RELEASES_ENABLED",
    "AZURE_COMPUTE_DEPLOYMENTS_ENABLED",
    'AZURE_DEPLOYMENTS_ENABLED: ${{ vars.AZURE_DEPLOYMENTS_ENABLED }}',
    "DEPLOYMENT_DATABASE_URL",
    "psql_database_url",
    "postgresql+asyncpg://",
    "worker_release_active_attempt_count",
    "NonterminalJobs",
    "UnresolvedProviderSubmissions",
    "OutstandingOutboxPublications",
    "az servicebus queue show",
    "QueueSendersVerified",
    "does not match the reviewed bootstrap contract",
    "secureEnvironmentVariables[].name",
    "has no recoverable immutable backend image",
    "update_in_place",
    "az acr repository show",
    "bootstrap-898adc56df2e",
    "09df7acff2a193c94af7c67a8657da9bd87d2aaa",
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

if (-not $workflow.Contains("false &&")) {
    throw "The ordinary CI deployment job must be disabled until a separately reviewed release mechanism is approved."
}
if ($workflow.Contains("JOB_SUBMISSIONS_ENABLED=true")) {
    throw "The ordinary CI workflow must never reopen job submissions."
}

if ($workflow.Contains("az role assignment list --all --include-inherited --scope")) {
    throw "Service Bus sender verification must not combine --all with a scoped inherited role lookup."
}

if ($workflow.Contains("Microsoft.App/jobs/caj-itl-outbox-dispatcher-dev") -or $workflow.Contains("az containerapp job")) {
    throw "The Express Container Apps environment cannot depend on a Container Apps Job."
}

if (-not $workflow.Contains('github_deployment_principal_id="$(az identity show --resource-group "$AZURE_RESOURCE_GROUP" --name id-image-to-lego-github-deployment-dev')) {
    throw "Service Bus sender verification must include the GitHub deployment identity."
}
if (-not $workflow.Contains('dispatcher_principal_id="$(az identity show --resource-group "$AZURE_RESOURCE_GROUP" --name id-image-to-lego-outbox-dispatcher-dev')) {
    throw "Service Bus sender verification must include the existing dispatcher identity."
}
if (-not $workflow.Contains('generation:$api_principal_id:$generation_principal_id:$dispatcher_principal_id:$github_deployment_principal_id') -or
    -not $workflow.Contains('conversion:$api_principal_id:$conversion_principal_id:$dispatcher_principal_id:$github_deployment_principal_id')) {
    throw "Both Service Bus queues must include the API, worker, existing dispatcher, and GitHub deployment sender identities."
}

if (-not $workflow.Contains('postgresql+asyncpg://*) psql_database_url="postgresql://${DEPLOYMENT_DATABASE_URL#postgresql+asyncpg://}"')) {
    throw "The release workflow must safely adapt the async SQLAlchemy URL for psql."
}

if (-not $workflow.Contains("sudo apt-get install --yes postgresql-client")) {
    throw "The release workflow must install the psql client it uses."
}

if ($workflow -notmatch 'az role assignment list --scope "\$subscription_resource/Microsoft\.ServiceBus/namespaces/\$namespace/queues/\$queue_name" --include-inherited') {
    throw "Service Bus sender verification must inspect inherited assignments at each queue scope."
}

if ($workflow -notmatch "roleDefinitionName=='Azure Service Bus Data Sender'" -or -not $workflow.Contains('[[ "$actual_ids" == "$wanted_ids" ]]')) {
    throw "Service Bus sender verification must require the exact reviewed sender identities."
}

if ($workflow.Contains('-c \"select public.worker_release_active_attempt_count()')) {
    throw "Database quiescence SQL must be quoted for Bash rather than passed as escaped literal quotes."
}

foreach ($requiredQuiescenceControl in @(
    'quiescence_counts="$(psql ',
    '"$psql_database_url"',
    '-c "select public.worker_release_active_attempt_count()',
    '" || {',
    'Could not query database quiescence counts.',
    'read -r active_attempts nonterminal_jobs unresolved_provider_submissions outstanding_outbox_publications <<< "$quiescence_counts"'
)) {
    if (-not $workflow.Contains($requiredQuiescenceControl)) {
        throw "Database quiescence query is missing required control: $requiredQuiescenceControl"
    }
}

if ($workflow -notmatch '\$worker_image_tag" == "bootstrap-898adc56df2e" && "\$RELEASE_SHA" != "\$initial_worker_handoff_sha"') {
    throw "Only the explicitly verified bootstrap image may bypass the normal full-SHA worker image check."
}

if ($workflow -notmatch '(?s)quiescence_counts="\$\(psql .*?\)" \|\| \{.*?read -r active_attempts') {
    throw "Database quiescence queries must fail closed before their counts are parsed."
}

$dispatcherWorkflowPath = Join-Path $PSScriptRoot "..\.github\workflows\dispatch-outbox.yml"
if (-not (Test-Path -LiteralPath $dispatcherWorkflowPath -PathType Leaf)) {
    throw "Submission-outbox dispatcher workflow was not found: $dispatcherWorkflowPath"
}
$dispatcherWorkflow = Get-Content -LiteralPath $dispatcherWorkflowPath -Raw
foreach ($fragment in @(
    'cron: "*/5 * * * *"',
    'workflow_dispatch:',
    "if: github.ref == 'refs/heads/main'",
    'group: submission-outbox-dispatcher',
    'cancel-in-progress: false',
    'timeout-minutes: 10',
    'AZURE_TOKEN_CREDENTIALS: AzureCliCredential',
    'DATABASE_URL: ${{ secrets.DEPLOYMENT_DATABASE_URL }}',
    'AZURE_SERVICE_BUS_NAMESPACE: image-to-lego-bus-dev-01.servicebus.windows.net',
    'AZURE_SERVICE_BUS_GENERATION_QUEUE: generation',
    'AZURE_SERVICE_BUS_QUEUE: conversion',
    'azure/login@v2',
    'uv run --frozen python -m app.outbox.run --max-messages 20 --max-runtime-seconds 45'
)) {
    if (-not $dispatcherWorkflow.Contains($fragment)) {
        throw "Submission-outbox dispatcher workflow is missing required control: $fragment"
    }
}

# Background workers must have no inbound IP; Azure CLI does not accept '--ip-address None'.
$aciCreationLines = [regex]::Matches($workflow, '(?m)^\s+az container create[^\r\n]*')
if ($aciCreationLines.Count -ne 2) {
    throw "Expected one Azure Container Instances create command per worker."
}
foreach ($command in $aciCreationLines) {
    foreach ($requiredArgument in @(
        '--cpu 1', '--memory 2', '--restart-policy Never', '--location malaysiawest',
        '--assign-identity', '--acr-identity', '--registry-login-server',
        '"APP_ENV=production"', '"AZURE_STORAGE_ACCOUNT_URL=https://storageimgtolego.blob.core.windows.net"',
        '"AZURE_STORAGE_CONTAINER=artifacts"', '"AZURE_SERVICE_BUS_NAMESPACE=image-to-lego-bus-dev-01.servicebus.windows.net"',
        '"AZURE_SERVICE_BUS_QUEUE=conversion"', '"AZURE_SERVICE_BUS_GENERATION_QUEUE=generation"',
        '"AZURE_CLIENT_ID=$'
    )) {
        if ($command.Value -notlike "*$requiredArgument*") {
            throw "ACI update must explicitly preserve its reviewed configuration: $requiredArgument"
        }
    }
    if ($command.Value -match '--ip-address\s+') {
        throw "ACI workers must not receive an inbound IP argument."
    }
}
if ($aciCreationLines[0].Value -notlike '*--command-line "python -m app.workers.aci_bootstrap generation"*' -or
    $aciCreationLines[1].Value -notlike '*--command-line "python -m app.workers.aci_bootstrap conversion"*') {
    throw "ACI bootstrap commands must be quoted as one argument to Azure CLI."
}

# Worker replacement is an in-place ARM PUT so the resource-scoped ACI RBAC
# assignment remains continuously applicable. A delete/recreate cycle would
# require a wider parent scope or a new role assignment before recreation.
foreach ($required in @(
    'Use ARM''s PUT update through `az container create`; do not delete a',
    'verify_new_worker_image "$AZURE_GENERATION_WORKER_NAME"',
    'verify_new_worker_image "$AZURE_CONVERSION_WORKER_NAME"'
)) {
    if (-not $workflow.Contains($required)) {
        throw "ACI replacement must preserve the resource and verify the new image: $required"
    }
}
if ($workflow -match 'az container (delete|stop)') {
    throw "Worker replacement must not stop or delete a resource before an in-place update."
}
$aciCreationLines = [regex]::Matches($workflow, '(?m)^\s+az container create[^\r\n]*')
if ($aciCreationLines.Count -ne 2) {
    throw "Expected exactly two ACI worker create commands."
}
foreach ($command in $aciCreationLines) {
    if ($command.Value -notlike '*"APP_ENV=production"*') {
        throw "ACI worker update must retain the verified production app environment."
    }
}

foreach ($required in @(
    '[[ "$action" == "update_in_place" ]]',
    'DATABASE_URL_SECRET_NAME=generation-worker-database-url',
    'DATABASE_URL_SECRET_NAME=conversion-worker-database-url',
    '"FAL_KEY_SECRET_NAME=fal-key"',
    '"AZURE_TOKEN_CREDENTIALS=ManagedIdentityCredential"'
)) {
    if (-not $workflow.Contains($required)) {
        throw "ACI in-place update is missing required credential or state guard: $required"
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

    # The historical all-components deployment job is intentionally disabled.
    # A qualified SHA can only be prepared by the separate manual workflow.
    return $false
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
Assert-DeploymentEligibility -Expected $false -Scenario $eligiblePush

$frontendOnlyPush = $eligiblePush.Clone()
$frontendOnlyPush.BackendResult = "skipped"; $frontendOnlyPush.BackendImageResult = "skipped"
$frontendOnlyPush.BackendPostgresResult = "skipped"
$frontendOnlyPush.FrontendResult = "success"
Assert-DeploymentEligibility -Expected $false -Scenario $frontendOnlyPush

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
Assert-DeploymentEligibility -Expected $false -Scenario $manualRollback

function Get-ReleaseMode {
    param([string]$EventName, [string]$ComputeDeploymentsEnabled, [string]$DeploymentsEnabled = "false")

    if ($ComputeDeploymentsEnabled -eq "true" -and $DeploymentsEnabled -eq "true") {
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
if ((Get-ReleaseMode -EventName "workflow_dispatch" -ComputeDeploymentsEnabled "true" -DeploymentsEnabled "true") -ne "deploy") {
    throw "Activation must allow the controlled first deployment."
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
    'AZURE_DEPLOYMENTS_ENABLED',
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

$prepareWorkflowPath = Join-Path $PSScriptRoot "..\.github\workflows\prepare-credit-initial-release.yml"
if (-not (Test-Path -LiteralPath $prepareWorkflowPath -PathType Leaf)) {
    throw "Initial credit release preparation workflow was not found."
}
$prepareWorkflow = Get-Content -LiteralPath $prepareWorkflowPath -Raw
foreach ($fragment in @(
    "workflow_dispatch:",
    "release_sha:",
    "git merge-base --is-ancestor",
    "docker push",
    "No App Service, ACI worker, Container App, Key Vault, Service Bus, or database resource was changed."
)) {
    if (-not $prepareWorkflow.Contains($fragment)) {
        throw "Initial credit release preparation is missing: $fragment"
    }
}
if ($prepareWorkflow -match "JOB_SUBMISSIONS_ENABLED=true|az webapp|az container create|az containerapp update|supabase\s+migration") {
    throw "The image-preparation workflow must not deploy runtimes, migrate the database, or reopen submissions."
}
if (-not $prepareWorkflow.Contains("Refusing to reuse") -or
    -not $prepareWorkflow.Contains('"$repository@$digest"')) {
    throw "Image preparation must record digests and refuse unproven existing SHA tags."
}

$apiReleaseWorkflowPath = Join-Path $PSScriptRoot "..\.github\workflows\deploy-api-outbox-dispatcher.yml"
$apiReleaseWorkflow = Get-Content -LiteralPath $apiReleaseWorkflowPath -Raw
foreach ($fragment in @(
    "expected_backend_digest:",
    "expected_backend_digest is required when reusing an existing SHA tag.",
    "Existing SHA tag does not match the approved backend digest."
)) {
    if (-not $apiReleaseWorkflow.Contains($fragment)) {
        throw "API release must pin a reused SHA tag to its approved digest: $fragment"
    }
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
