# Azure Terraform lifecycle: safe compute teardown and clean-room recreation

## Status and scope

The following is the current development deployment. The five resources have been imported into the separate compute state and a post-import reconciliation plan reported no changes. This is not proof that a deletion-and-recreation drill has occurred.

| Component | Tested live resource | Terraform target |
| --- | --- | --- |
| API | Linux custom-container App Service `app-image-to-lego-api-dev-2b70703f` on B1 plan `ASP-rgimagetolegodev-8295` | `azurerm_service_plan.api`, `azurerm_linux_web_app.api` |
| Generation | Stopped ACI `aci-image-to-lego-generation-dev`, 1 vCPU/2 GB, `Never` restart | `azurerm_container_group.generation_worker` |
| Conversion | Stopped ACI `aci-image-to-lego-conversion-dev`, 1 vCPU/2 GB, `Never` restart | `azurerm_container_group.conversion_worker` |
| Frontend | Container App `ca-frontend-image-to-lego-dev`, 0.25 vCPU/0.5 GiB, ingress 8080, min 0/max 1 | `azurerm_container_app.frontend` |

The frontend image is `image-to-lego-frontend:dev-20261030-nginxfix`. Its `API_UPSTREAM` is derived from `azurerm_linux_web_app.api.default_hostname`, so a recreated App Service hostname is passed to the frontend automatically. Nginx continues to forward `/api` through `frontend/nginx.conf.template`; do not replace this with the obsolete `http://ca-api-image-to-lego-dev` address.

The shared root owns the resource group, Terraform backend storage, artifact Blob Storage, Service Bus queues, ACR, Key Vault, managed identities, role assignments, logging, and Container Apps environment. Its resources use `prevent_destroy`. The compute root reads those dependencies as data sources, so compute-only destroy/recreate cannot delete persistent data or the remote-state container. Supabase is external to Terraform and must be checked separately.

## Before reconciliation

No command below is part of this change. Assign a single operator with Azure read permissions and state-container access, work from a private workstation, and use the current approved AzureRM 4.x provider lock. Terraform state is sensitive infrastructure data: it can contain App Service settings, ACI secure environment values, and provider-computed credentials even where Terraform labels values sensitive. Do not print it, attach it to tickets, copy it into this repository, or store an unencrypted backup in a shared location.

Before changing state, make a read-only inventory of the App Service plan/site, both ACI groups, frontend Container App, their identities, registry configuration, and every application-setting name. Compare that inventory with the configuration. In particular, do not apply the App Service configuration until its complete settings map and its managed-identity/Key Vault reference have been reviewed. The code intentionally ignores existing App Service settings and key-vault-reference identity to avoid changing live authentication during adoption.

The local worker modules consume `DATABASE_URL`, Blob settings, Service Bus settings, and (generation only) `FAL_KEY` from their environment. They do not themselves fetch Key Vault secrets. A repository-wide review found no checked-in ACI YAML, shell entrypoint, deployment script, or Dockerfile command matching the verified live custom bootstrap command. The verified live behavior must therefore be supplied by an out-of-repository ACI command or image content, not by the worker modules alone.

`backend/app/workers/aci_bootstrap.py` is a version-controlled **future-image** bootstrap target. It uses the assigned user-managed identity selected by `AZURE_CLIENT_ID` to request a Key Vault token, retrieves `DATABASE_URL` and (for generation only) `FAL_KEY` by their nonsecret Key Vault secret names, sets them only in the child process environment, and `exec`s the corresponding worker. It does not log, write, or pass secret values through Terraform. Conversion retrieves only `DATABASE_URL`. This script is not present in the currently deployed backend image `dev-20261029-205014`; a new backend image built from this repository revision, published under the image-identity gate below, is an explicit prerequisite for any worker recreation or command change.

Before importing either ACI group, obtain a **read-only, nonsecret** inventory of its live `command` array, the image tag, identity assignment/client-ID selection, registry authentication mode, and the names (not values) of every environment or secure-environment setting used by the bootstrap. In particular, verify the Key Vault URI/secret-name inputs, whether a shell wrapper or an image-internal program is used, and whether any other nonsecret runtime setting is required. Do not collect or print `DATABASE_URL`, `FAL_KEY`, registry passwords, or secure-environment values. Until that inventory matches the new target or an approved exception, the ACI command/environment drift remains ignored for adoption and worker recreation is blocked.

## Bootstrap smoke test for a future backend image (not executed)

Run this test only after a new backend image has been pushed under a **new, never-reused release tag** and its ACR digest has been recorded. The operator needs permission to create/delete a temporary ACI, read its logs, use the conversion identity for ACR pull and Key Vault access, and read the nonsecret Key Vault URI. The existing generation and conversion ACIs must remain stopped and unchanged.

This is deliberately a **conversion-only** test. Its Python program replaces `aci_bootstrap.os.execvp` before it calls `main(["conversion"])`. The bootstrap can therefore acquire a managed-identity token and retrieve only `DATABASE_URL`, but it cannot replace itself with `app.workers.conversion_worker`. It neither selects the generation path nor supplies `FAL_KEY_SECRET_NAME`, so it cannot read `FAL_KEY`, import the generation worker, submit to fal.ai, or consume a Service Bus message. The program prints only the expected command, never a secret.

```powershell
$ErrorActionPreference = "Stop"

$resourceGroup = "rg-image-to-lego-dev"
$acrName = "itl2b70703f"
$keyVaultName = "kv-itl-2b70703f"
$releaseTag = "<new-never-reused-release-tag>"
$smokeGroup = "aci-image-to-lego-bootstrap-smoke-<release-id>"

$acrServer = az acr show --resource-group $resourceGroup --name $acrName --query loginServer --output tsv
$smokeImage = "${acrServer}/image-to-lego-backend:${releaseTag}"
$conversionIdentity = az identity show `
  --resource-group $resourceGroup `
  --name id-image-to-lego-conversion-dev `
  --query "{id:id,clientId:clientId}" `
  --output json | ConvertFrom-Json

# Keep this as one PowerShell string and pass it as one Python argument. Azure CLI
# receives an argument array; no shell in the container evaluates this program.
$smokeProgram = 'from app.workers import aci_bootstrap as b;b.os.execvp=lambda executable,arguments:print("BOOTSTRAP_OK "+" ".join(arguments));b.main(["conversion"])'

az container create `
  --resource-group $resourceGroup `
  --name $smokeGroup `
  --image $smokeImage `
  --os-type Linux `
  --cpu 1 `
  --memory 1 `
  --restart-policy Never `
  --ip-address None `
  --assign-identity $conversionIdentity.id `
  --registry-login-server $acrServer `
  --registry-identity $conversionIdentity.id `
  --command-line python -c $smokeProgram `
  --environment-variables `
    "AZURE_CLIENT_ID=$($conversionIdentity.clientId)" `
    "AZURE_KEY_VAULT_URL=https://$keyVaultName.vault.azure.net/" `
    "DATABASE_URL_SECRET_NAME=database-url"

az container wait `
  --resource-group $resourceGroup `
  --name $smokeGroup `
  --custom "containers[0].instanceView.currentState.state=='Terminated'" `
  --interval 5 `
  --timeout 120

$smokeResult = az container show `
  --resource-group $resourceGroup `
  --name $smokeGroup `
  --query "containers[0].instanceView.currentState.{state:state,exitCode:exitCode,detail:detail}" `
  --output json | ConvertFrom-Json

if ($smokeResult.state -ne "Terminated" -or $smokeResult.exitCode -ne 0) {
  throw "Bootstrap smoke test did not exit successfully. Review the temporary ACI logs without printing secrets."
}

az container logs --resource-group $resourceGroup --name $smokeGroup
```

Expected result: exit code `0` and a `BOOTSTRAP_OK python -m app.workers.conversion_worker` line in the container log. The previous exit-code query must not use `events[-1].count`; that field is an event occurrence count, not a process exit code. Cost is a short-lived 1 vCPU/1 GB ACI execution, one ACR pull, one Key Vault secret read, and log ingestion. Stop if creation, identity authentication, ACR pull, Key Vault read, termination, exit code, or log output differs from the expected result; do not start a worker as a substitute diagnostic.

After an operator has preserved the nonsecret evidence and approved the destructive cleanup, delete only the temporary smoke group and verify that it is gone:

```powershell
az container delete --resource-group $resourceGroup --name $smokeGroup --yes
az container show --resource-group $resourceGroup --name $smokeGroup 2>$null
if ($LASTEXITCODE -eq 0) {
  throw "The temporary bootstrap smoke group still exists."
}
```

The final command must report that the resource was not found. Stop if the name does not exactly match the temporary `$smokeGroup`; never delete either existing worker group. Cleanup stops the temporary ACI billing and removes only its temporary configuration.

## Historical frontend state handoff

This handoff and the five configuration-driven imports are complete. It is retained as history only; do not re-run it against the current state. `application-compute/imports.tf` was intentionally retired after the successful imports so a later recreation creates resources instead of importing deleted IDs.

Terraform cannot atomically transfer a resource between two remote state backends. The safe sequence avoids any interval where both states own the frontend; it accepts a short state-only interval where neither does. During that interval, run only the destination root's reviewed import plan/apply—never a normal reconciliation apply in either root.

1. Copy `shared/backend.shared.dev.hcl.example` to an ignored local file and set its `key` to the existing shared-state key. Copy `application-compute/backend.application-compute.dev.hcl.example` to an ignored local file without changing its distinct key.
2. Initialize `infra/terraform/shared` against the current shared key, and initialize `infra/terraform/application-compute` against its empty distinct key. Inspect addresses only; do not print state values.
3. In the shared root, confirm that the only frontend state address is `azurerm_container_app.frontend[0]` and that `removed.tf` has `destroy = false`. Terraform rejects indexed `removed.from` addresses, so the required unindexed resource address covers all instances; stop if any instance other than `[0]` exists. Review the plan. It must show detachment without destruction and no unexpected shared update/replacement. The legacy `standard` environment removed block must not detach anything unexpected; if it appears in the plan, stop for a separate inventory review.
4. Only after that plan is approved, apply the shared root's reviewed `removed` block. This is a deliberate state-only handoff action: it must detach the frontend without deleting or changing the live Container App. Do not use `state rm`, `state mv`, or direct import commands. This change does not execute that apply.
5. In the compute root, review the plan produced by the checked-in `imports.tf`. It imports the frontend and the other existing compute resources using the current authenticated subscription ID. An import block does not make an apply import-only: if configuration differs from Azure, Terraform can import and update the frontend in the same apply. The plan must therefore contain only imports and no frontend update or replacement. If it does not, reconcile the configuration with the read-only inventory before continuing.
6. Only when that compute plan is approved as import-only, apply it to record the imports. Then run refresh-enabled plans in both roots. The shared plan must not propose frontend destruction; the compute plan must not propose an unexpected frontend replacement or update. Resolve every difference before any later apply.

If the compute import review fails after step 4, stop. Do not apply either root. The live frontend remains available at its existing public URL because this sequence does not rename, recreate, or delete it. Diagnose the configuration and backend before continuing; any sensitive-state recovery procedure needs separate approval.

## Historical import record

The retired `application-compute/imports.tf` used these exact resource-ID forms, with only the runtime subscription ID supplied by `azurerm_client_config`:

| Terraform address | Resource ID suffix |
| --- | --- |
| `azurerm_service_plan.api` | `/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.Web/serverFarms/ASP-rgimagetolegodev-8295` |
| `azurerm_linux_web_app.api` | `/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.Web/sites/app-image-to-lego-api-dev-2b70703f` |
| `azurerm_container_group.generation_worker` | `/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.ContainerInstance/containerGroups/aci-image-to-lego-generation-dev` |
| `azurerm_container_group.conversion_worker` | `/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.ContainerInstance/containerGroups/aci-image-to-lego-conversion-dev` |
| `azurerm_container_app.frontend` | `/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.App/containerApps/ca-frontend-image-to-lego-dev` |

This was safer than an ad hoc `state rm`/CLI import sequence because the source detachment and destination IDs were committed and reviewable. It was not atomic across backends, so the documented ordering was mandatory.

The shared resources are already Terraform-managed under their existing addresses. If a shared resource must ever be adopted into a new state, use its existing state address and a read-only inventory first. Role-assignment IDs are not included here because their GUIDs have not been verified; obtain them through a reviewed read-only inventory rather than guessing IDs.

For a recovery-only shared-state adoption, the following IDs are grounded by the configured names. Do **not** run them against the current shared state, which already owns these resources:

```powershell
terraform import azurerm_resource_group.dev "/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-image-to-lego-dev"
terraform import azurerm_storage_account.artifacts "/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.Storage/storageAccounts/storageimgtolego"
terraform import azurerm_storage_container.artifacts "/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.Storage/storageAccounts/storageimgtolego/blobServices/default/containers/artifacts"
terraform import azurerm_servicebus_namespace.jobs "/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.ServiceBus/namespaces/image-to-lego-bus-dev-01"
terraform import azurerm_servicebus_queue.generation "/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.ServiceBus/namespaces/image-to-lego-bus-dev-01/queues/generation"
terraform import azurerm_servicebus_queue.conversion "/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.ServiceBus/namespaces/image-to-lego-bus-dev-01/queues/conversion"
terraform import azurerm_container_registry.backend "/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.ContainerRegistry/registries/itl2b70703f"
terraform import azurerm_key_vault.runtime "/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.KeyVault/vaults/kv-itl-2b70703f"
terraform import azurerm_log_analytics_workspace.application "/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.OperationalInsights/workspaces/log-image-to-lego-dev"
terraform import azurerm_container_app_environment.development "/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.App/managedEnvironments/cae-image-to-lego-dev"
terraform import azurerm_user_assigned_identity.api "/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-image-to-lego-api-dev"
terraform import azurerm_user_assigned_identity.generation_worker "/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-image-to-lego-generation-dev"
terraform import azurerm_user_assigned_identity.conversion_worker "/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-image-to-lego-conversion-dev"
terraform import azurerm_user_assigned_identity.frontend "/subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-image-to-lego-frontend-dev"
```

## Safe compute lifecycle

An image update is an application release, not a generic Terraform refresh. Before any change, build and verify the backend/frontend images exist in ACR, verify the API has access to its Key Vault reference and managed identity can pull the image, and check Supabase migrations separately. All five migrations, including `20261029000000_worker_job_leases.sql`, are already synchronized; Terraform must not run or repair migrations.

### Image identity and immutability gate

The current Terraform configuration deploys images by `api_backend_image_tag`, `worker_backend_image_tag`, and `frontend_image_tag`, not by digest. A unique tag is useful release evidence but is not technically immutable unless ACR tag-overwrite controls or an approved operational policy prevent reuse. The worker tag is currently `bootstrap-898adc56df2e`; it is separate from the API tag, so selecting it for a future worker recreation cannot update the running API.

`dev-20261029-205014` predates the `JOB_SUBMISSIONS_ENABLED` submission gate and **must not** be used for recovery. The checked-in source contains the gate, but this repository cannot prove that an existing ACR image contains it. Before any recovery plan, build the reviewed source revision, publish it under a previously unused API release tag, and record the ACR repository digest beside the release approval. Then run the focused offline tests that prove both submission endpoints return 503 without calling their repositories or queues. Do not change `api_backend_image_tag` in the adoption configuration or deploy that image before the separately approved compute teardown.

Before any release or recovery plan:

1. Build from an approved, clean, committed source revision and give the backend image a new release tag that will never be reused.
2. Query and record the ACR digest for that exact `repository:tag`; do not print registry credentials.
3. Confirm that the release tag is absent before publication and has not moved after publication.
4. Use the deployed API tag for reconciliation. Change an image variable only in a separately reviewed release or recreation plan.

Stop if the team cannot enforce the never-reuse policy, cannot retain the digest as release evidence, or requires a cryptographic immutability guarantee. The current tag-only variables cannot provide that guarantee; a separately approved Terraform design change to deploy digest references is required.

The API configuration contains a Key Vault reference string for `DATABASE_URL`, never its value, and uses its user-assigned identity for ACR pulls and Key Vault references. Its existing complete application-settings map is intentionally ignored during adoption. A zero-surprise API recreation still requires a reviewed nonsecret inventory of every setting name/value contract, confirmation that the API identity has `AcrPull` and Key Vault secret-read/reference access, and confirmation that the exact secret names exist. Do not copy live credentials into Terraform merely to make the plan quiet.

### Rollback gate for workers

The pre-bootstrap image `dev-20261029-205014` cannot run the new `python -m app.workers.aci_bootstrap ...` command because it does not contain that module. It is therefore not a valid worker rollback image after a worker has been recreated with the new command. Before a first worker recreation, retain and test at least one earlier **bootstrap-capable** backend image and record its tag and digest. Also retain the read-only inventory of the historic worker command and nonsecret environment-name contract.

For an API-only image rollback, use a reviewed plan that restores a previously verified image reference and makes no database migration change. For a worker rollback, stop if the target image lacks `aci_bootstrap.py`, the required historic command/environment contract was not captured, or the Terraform plan changes anything other than the approved compute resources. Never infer the missing old command from a failed worker, and never roll back Supabase migrations automatically.

### Manually approved teardown and recreation

These commands are an operator runbook, not permission to execute them automatically. Save plans outside the repository; do not commit state, plans, CLI output containing settings, or Supabase credentials.

1. Preflight: obtain written approval; keep both workers stopped; pause generation submissions; account for active and dead-letter queue messages; record the current API/frontend URL and nonsecret App Service setting names. Confirm the exact tags exist with `az acr repository show --name itl2b70703f --image image-to-lego-backend:bootstrap-898adc56df2e` and the equivalent frontend query. Record digests without registry credentials.
2. Confirm protected data before any destroy: use read-only `az storage container show`, `az servicebus queue show`, `az keyvault secret show --id <secret-version-id> --query id`, and `az identity show` calls; verify the expected artifact container, queues, secret versions, identities, and role assignments still exist. Use the Supabase dashboard or a read-only SQL connection to record migration versions and artifact/job counts. Never put a connection string in Terraform or this runbook.
3. In `application-compute`, initialize only its existing distinct backend, run `terraform plan -destroy -out <private-destroy-plan>`, then run `scripts/Test-ComputePlan.ps1 -PlanPath <private-destroy-plan> -Mode destroy`. The gate accepts only deletion of the five listed compute resources. Stop if it reports any other address, including the resource group, state storage, Blob artifacts, Key Vault, ACR, Service Bus, identities, role assignments, logging, Container Apps environment, or any data source change presented as managed work.
4. After a second human approves the saved plan, apply that exact saved destroy plan manually. A destroyed ACI loses its configuration and secure values; a stopped ACI retains its definition and does not start because `restart_policy` is `Never`.
5. **Stage 1 — recovery without workers.** Recreate with the same reviewed variable file, including browser-safe `supabase_url` and `supabase_publishable_key`, the existing Key Vault secret names, and the verified image tags, but set `job_submissions_enabled=false`. `api_backend_image_tag` must be the approved unique, newly published tag that contains the submission gate; it must not be `dev-20261029-205014`. Save a plan that is explicitly limited to the non-worker resources:

   ```powershell
   terraform plan `
     -var="api_backend_image_tag=<approved-new-api-tag>" `
     -var="job_submissions_enabled=false" `
     -target=azurerm_service_plan.api `
     -target=azurerm_linux_web_app.api `
     -target=azurerm_container_app.frontend `
     -out <private-recovery-plan>
   scripts/Test-ComputePlan.ps1 `
     -PlanPath <private-recovery-plan> `
     -Mode recovery `
     -ExpectedApiImageTag <approved-new-api-tag>
   ```

   The gate requires exactly three `create` actions: `azurerm_service_plan.api`, `azurerm_linux_web_app.api`, and `azurerm_container_app.frontend`. It also rejects the saved recovery plan unless the API's planned `app_settings` explicitly contains the known string `JOB_SUBMISSIONS_ENABLED = "false"`; a missing, unknown, enabled, or differently typed/value setting fails closed. It rejects either ACI address, so this stage cannot create or start a worker. A fresh API receives only its API identity; the frontend derives its HTTPS API upstream from the recreated App Service hostname. After two people approve the saved plan, apply that exact plan manually.
6. **Verify the pause and queue baseline.** Before considering workers, make an authenticated request for each submission endpoint using a disposable/non-production request body. Both `POST /api/v1/reconstructions` and `POST /api/v1/conversions` must return `503` with `Job submissions are temporarily paused.`; neither may create a durable job or send a message. Confirm the API's deployed image tag and recorded ACR digest are the approved gate-image release. With read-only Service Bus queries, record active, scheduled, and transfer-dead-letter counts for both queues. Generation and conversion active counts must both be zero; scheduled counts must both be zero. Record the conversion dead-letter count separately: the two known expired historical messages are not active work and must not be replayed, completed, or removed in this procedure. Stop if any count changes unexpectedly, a submission is accepted, either ACI exists/runs, the image evidence differs, or the pause setting cannot be verified.
7. **Stage 2 — create workers while submissions remain paused.** Keep `job_submissions_enabled=false` and plan only the two ACI groups:

   ```powershell
   terraform plan `
     -var="api_backend_image_tag=<approved-new-api-tag>" `
     -var="job_submissions_enabled=false" `
     -target=azurerm_container_group.generation_worker `
     -target=azurerm_container_group.conversion_worker `
     -out <private-workers-plan>
   scripts/Test-ComputePlan.ps1 -PlanPath <private-workers-plan> -Mode workers
   ```

   The gate requires exactly two `create` actions: `azurerm_container_group.generation_worker` and `azurerm_container_group.conversion_worker`. This is the first plan allowed to start workers, but the API remains paused. After two people approve the saved plan, apply that exact plan manually. Verify both workers are ready using their non-processing readiness evidence and recheck queue counts. Do not submit a generation job or invoke FAL as part of this stage.
8. **Stage 3 — operationally enable submissions after worker readiness.** `app_settings` is intentionally ignored during adoption to preserve the existing unknown settings map, so Terraform does not own individual App Service settings after creation. Do not force an API replacement merely to change this setting. Use the separate `scripts/Set-JobSubmissions.ps1` operational control. Its default mode is read-only; it is hard-coded to the development App Service, requires the exact approved resource ID and current setting value, and cannot write unless `-Apply` is supplied. It changes only `JOB_SUBMISSIONS_ENABLED`; App Service restarts when this setting changes.

   ```powershell
   # Read-only preflight. Copy the ID from a reviewed az webapp show result.
   scripts/Set-JobSubmissions.ps1 `
     -ApprovedResourceId <approved-api-resource-id> `
     -ExpectedCurrentValue false `
     -DesiredValue true `
     -ApprovalReference <change-ticket>

   # Separately approved write; this restarts the App Service.
   scripts/Set-JobSubmissions.ps1 `
     -ApprovedResourceId <approved-api-resource-id> `
     -ExpectedCurrentValue false `
     -DesiredValue true `
     -ApprovalReference <change-ticket> `
     -Apply
   ```

   Record the script's verified setting result and wait for the restart to complete. Then make authenticated reconstruction and conversion requests with a disposable body and confirm they no longer return the paused 503 response. Recheck active/scheduled queue counts immediately before permitting normal traffic. To re-pause, run the same control with `-ExpectedCurrentValue true -DesiredValue false`, then verify both endpoints again return 503 without creating jobs or messages. Terraform's ignored `app_settings` lifecycle safeguard deliberately preserves this operational value through normal plans; every future clean-room recovery must still explicitly create the API with `job_submissions_enabled=false` in Stage 1.
9. After Stage 3, run an un-targeted refresh-enabled plan and `scripts/Test-ComputePlan.ps1 -PlanPath <private-reconcile-plan> -Mode reconcile`. It must have zero managed changes, proving the complete five-resource deployment reconciles without drift. Roll back only with a separately reviewed plan to known-good image references that pass the worker bootstrap gate; do not roll back Supabase migrations automatically. If a plan shows a resource replacement or update that is not explicitly intended, stop and investigate.

### Targeting limitation

Terraform `-target` is intentionally used here only for recovery sequencing. It is not a normal reconciliation method: it can omit unrelated changes and does not prove the complete graph is converged. Every targeted apply must use its reviewed saved plan, and Stage 3 must be followed by the un-targeted reconciliation in step 9. Targeting cannot prove that the published image contains the gate, that workers are healthy, or that no external sender enqueues a message between queue inspection and activation.

`Test-ComputePlan.ps1` is a local saved-plan inventory test. It reads only Terraform's JSON rendering of a saved plan, prints only resource addresses/actions, and rejects shared or unexpected managed resources. Run its reconciliation mode after import or recreation: `terraform plan -out <private-reconcile-plan>` followed by `scripts/Test-ComputePlan.ps1 -PlanPath <private-reconcile-plan> -Mode reconcile`.

## Cost and data notes

The B1 App Service plan has baseline cost while allocated. ACR, Key Vault, logging ingestion, Blob retention, Service Bus, and fal.ai use remain billable even when both ACI workers are stopped. Keeping stopped ACI resources avoids recreation risk but may still retain associated resource metadata; verify actual billing before deciding to destroy them. Blob artifacts and Supabase data are persistent and are intentionally outside compute teardown.

## Architecture documentation conflict

ADR-004 and portions of `azure-cicd-plan.md` describe a Container Apps API/worker topology. The tested development deployment instead uses App Service plus ACI for API/workers. This runbook records the actual tested layout without silently rewriting an accepted ADR. The team must approve and document that architectural decision before claiming that Terraform recreation is tested or before changing production-oriented topology.
