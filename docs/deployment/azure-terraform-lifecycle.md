# Azure Terraform lifecycle: tested deployment and safe reconciliation

## Status and scope

The following is the **tested development deployment**, not proof that Terraform can recreate it:

| Component | Tested live resource | Terraform target |
| --- | --- | --- |
| API | Linux custom-container App Service `app-image-to-lego-api-dev-2b70703f` on B1 plan `ASP-rgimagetolegodev-8295` | `azurerm_service_plan.api`, `azurerm_linux_web_app.api` |
| Generation | Stopped ACI `aci-image-to-lego-generation-dev`, 1 vCPU/2 GB, `Never` restart | `azurerm_container_group.generation_worker` |
| Conversion | Stopped ACI `aci-image-to-lego-conversion-dev`, 1 vCPU/2 GB, `Never` restart | `azurerm_container_group.conversion_worker` |
| Frontend | Container App `ca-frontend-image-to-lego-dev`, 0.25 vCPU/0.5 GiB, ingress 8080, min 0/max 1 | `azurerm_container_app.frontend` |

The frontend image is `image-to-lego-frontend:dev-20261030-nginxfix`. Its `API_UPSTREAM` is the tested HTTPS App Service origin recorded in `application-compute/dev.tfvars.example`. Nginx continues to forward `/api` through `frontend/nginx.conf.template`; do not replace this with the obsolete `http://ca-api-image-to-lego-dev` address.

The shared root owns the resource group, artifact Blob Storage, Service Bus queues, ACR, Key Vault, managed identities, role assignments, logging, and Container Apps environment. Its resources use `prevent_destroy`. The compute root reads those dependencies as data sources, so compute-only destroy/recreate cannot delete persistent data or the remote-state container.

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

## Reviewed frontend state handoff (not executed)

Terraform cannot atomically transfer a resource between two remote state backends. The safe sequence avoids any interval where both states own the frontend; it accepts a short state-only interval where neither does. During that interval, run only the destination root's reviewed import plan/apply—never a normal reconciliation apply in either root.

1. Copy `shared/backend.shared.dev.hcl.example` to an ignored local file and set its `key` to the existing shared-state key. Copy `application-compute/backend.application-compute.dev.hcl.example` to an ignored local file without changing its distinct key.
2. Initialize `infra/terraform/shared` against the current shared key, and initialize `infra/terraform/application-compute` against its empty distinct key. Inspect addresses only; do not print state values.
3. In the shared root, confirm that the only frontend state address is `azurerm_container_app.frontend[0]` and that `removed.tf` has `destroy = false`. Terraform rejects indexed `removed.from` addresses, so the required unindexed resource address covers all instances; stop if any instance other than `[0]` exists. Review the plan. It must show detachment without destruction and no unexpected shared update/replacement. The legacy `standard` environment removed block must not detach anything unexpected; if it appears in the plan, stop for a separate inventory review.
4. Only after that plan is approved, apply the shared root's reviewed `removed` block. This is a deliberate state-only handoff action: it must detach the frontend without deleting or changing the live Container App. Do not use `state rm`, `state mv`, or direct import commands. This change does not execute that apply.
5. In the compute root, review the plan produced by the checked-in `imports.tf`. It imports the frontend and the other existing compute resources using the current authenticated subscription ID. An import block does not make an apply import-only: if configuration differs from Azure, Terraform can import and update the frontend in the same apply. The plan must therefore contain only imports and no frontend update or replacement. If it does not, reconcile the configuration with the read-only inventory before continuing.
6. Only when that compute plan is approved as import-only, apply it to record the imports. Then run refresh-enabled plans in both roots. The shared plan must not propose frontend destruction; the compute plan must not propose an unexpected frontend replacement or update. Resolve every difference before any later apply.

If the compute import review fails after step 4, stop. Do not apply either root. The live frontend remains available at its existing public URL because this sequence does not rename, recreate, or delete it. Diagnose the configuration and backend before continuing; any sensitive-state recovery procedure needs separate approval.

## Required imports for existing compute (not executed)

`application-compute/imports.tf` is the reviewed, configuration-driven import record. It contains these exact resource-ID forms, with only the runtime subscription ID supplied by `azurerm_client_config`:

| Terraform address | Resource ID suffix |
| --- | --- |
| `azurerm_service_plan.api` | `/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.Web/serverfarms/ASP-rgimagetolegodev-8295` |
| `azurerm_linux_web_app.api` | `/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.Web/sites/app-image-to-lego-api-dev-2b70703f` |
| `azurerm_container_group.generation_worker` | `/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.ContainerInstance/containerGroups/aci-image-to-lego-generation-dev` |
| `azurerm_container_group.conversion_worker` | `/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.ContainerInstance/containerGroups/aci-image-to-lego-conversion-dev` |
| `azurerm_container_app.frontend` | `/resourceGroups/rg-image-to-lego-dev/providers/Microsoft.App/containerApps/ca-frontend-image-to-lego-dev` |

This is safer than an ad hoc `state rm`/CLI import sequence because the source detachment and destination IDs are committed and reviewable. It is still not atomic across backends, so strict ordering and an import-only plan remain mandatory.

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

The current Terraform configuration deploys images by `backend_image_tag` and `frontend_image_tag`, not by digest. A unique tag is useful release evidence but is not technically immutable unless ACR tag-overwrite controls or an approved operational policy prevent reuse. Before any release plan:

1. Build from an approved, clean, committed source revision and give the backend image a new release tag that will never be reused.
2. Query and record the ACR digest for that exact `repository:tag`; do not print registry credentials.
3. Confirm that the release tag is absent before publication and has not moved after publication.
4. Use the deployed image tags from the read-only inventory for the import-only plan. Do **not** substitute the new backend tag until imports are complete; otherwise Terraform can combine imports with an update.

Stop if the team cannot enforce the never-reuse policy, cannot retain the digest as release evidence, or requires a cryptographic immutability guarantee. The current tag-only variables cannot provide that guarantee; a separately approved Terraform design change to deploy digest references is required.

The API configuration contains a Key Vault reference string for `DATABASE_URL`, never its value, and uses its user-assigned identity for ACR pulls and Key Vault references. Its existing complete application-settings map is intentionally ignored during adoption. A zero-surprise API recreation still requires a reviewed nonsecret inventory of every setting name/value contract, confirmation that the API identity has `AcrPull` and Key Vault secret-read/reference access, and confirmation that the exact secret names exist. Do not copy live credentials into Terraform merely to make the plan quiet.

### Rollback gate for workers

The pre-bootstrap image `dev-20261029-205014` cannot run the new `python -m app.workers.aci_bootstrap ...` command because it does not contain that module. It is therefore not a valid worker rollback image after a worker has been recreated with the new command. Before a first worker recreation, retain and test at least one earlier **bootstrap-capable** backend image and record its tag and digest. Also retain the read-only inventory of the historic worker command and nonsecret environment-name contract.

For an API-only image rollback, use a reviewed plan that restores a previously verified image reference and makes no database migration change. For a worker rollback, stop if the target image lacks `aci_bootstrap.py`, the required historic command/environment contract was not captured, or the Terraform plan changes anything other than the approved compute resources. Never infer the missing old command from a failed worker, and never roll back Supabase migrations automatically.

### Import-only adoption versus recreation

`application-compute/imports.tf` is an adoption configuration. During the state handoff, its plan must contain exactly the five reviewed imports and no changes. After import, use a separate release plan for an explicit image update; do not combine either plan with worker recreation until queue work is drained/accounted for and generation submissions are paused.

The checked-in configuration is not a safe clean-room recreation configuration. If the compute root is destroyed while `imports.tf` remains present, a later plan will attempt to import resource IDs that no longer exist instead of creating them. A future teardown/recreation requires a separate approved change that retires the adoption-only import blocks after state adoption, an App Service setting inventory, verified image references, a bootstrap-capable worker rollback image, and a reviewed destroy plan. Stop if a destroy or recreation plan mentions shared resources, queues, Blob artifacts, Key Vault, ACR, identities, role assignments, logging, the Container Apps environment, or the state container.

For a compute-only teardown, first drain or account for queued work, keep the workers stopped, verify retention of Blob artifacts and Supabase data, and review a compute-root destroy plan. It may delete the App Service plan/site, the two ACI resources, and the frontend after ownership handoff, but it must show no shared resource, queue, artifact store, Key Vault, ACR, identity, role assignment, logging resource, Container Apps environment, or state container. A destroyed ACI loses its configuration and secure values. A **stopped** ACI has not been destroyed, retains its definition, and does not start merely because its `restart_policy` is `Never`.

Recreation is not approved until the live bootstrap command has been inventoried, the bootstrap-enabled backend image has been built and verified, Key Vault/RBAC access is confirmed, and a clean-room deployment has been tested. Recreating an ACI starts a new container group; it is not equivalent to leaving the current stopped group in place. Starting or stopping either worker remains an operational Azure action outside Terraform and outside this change.

Rollback a compute configuration only by a reviewed import/reconciliation or a redeploy of a previously verified image tag/digest pair that satisfies the worker bootstrap gate. Do not roll back database migrations automatically. If a plan shows any replacement or update not explicitly intended, stop and investigate; imported state and live Azure configuration, not this repository alone, determine whether reconciliation is a no-op.

## Cost and data notes

The B1 App Service plan has baseline cost while allocated. ACR, Key Vault, logging ingestion, Blob retention, Service Bus, and fal.ai use remain billable even when both ACI workers are stopped. Keeping stopped ACI resources avoids recreation risk but may still retain associated resource metadata; verify actual billing before deciding to destroy them. Blob artifacts and Supabase data are persistent and are intentionally outside compute teardown.

## Architecture documentation conflict

ADR-004 and portions of `azure-cicd-plan.md` describe a Container Apps API/worker topology. The tested development deployment instead uses App Service plus ACI for API/workers. This runbook records the actual tested layout without silently rewriting an accepted ADR. The team must approve and document that architectural decision before claiming that Terraform recreation is tested or before changing production-oriented topology.
