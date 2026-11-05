# GitHub Actions Azure release setup

This is the release procedure for the existing development environment. It uses the deployed topology, not the historical Container Apps proposal: a Linux App Service API, a frontend Container App, and two `restart_policy = Never` ACI workers.

Nothing in this document authorizes a Terraform apply or a deployment. The initial identity setup and every release run require the normal human review process.

## Current inactive release boundary

The release controller, atomic submission admission, transactional submission outbox, and fenced
dispatcher logic are implemented. The API's automatic dispatcher trigger is opt-in and best effort:
it runs one bounded pass only after a new job commits, using the separate private dispatcher database
login. It never changes a successful `201` into an error. The scheduled/manual GitHub Actions workflow
remains the durable recovery mechanism for pending intents when an automatic pass is disabled, misses,
or fails.

The dispatcher migration is a separate database operation; it is already applied for this target
release and this workflow must not rerun it. A reviewed operator must grant the dispatcher database
login membership in `image_to_lego_outbox_dispatcher` and configure the private dispatcher URL.
Older deployed worker images must not be replaced before the reviewed bootstrap sequence has
completed.

## Automatic submission-outbox dispatch

Keep `OUTBOX_AUTO_DISPATCH_ENABLED=false` until the private dispatcher login and Service Bus sender
access have been verified. No credential value belongs in source control.

For local development, set these values in `backend/.env` (which remains untracked):

```text
OUTBOX_AUTO_DISPATCH_ENABLED=true
OUTBOX_DISPATCHER_DATABASE_URL=postgresql+asyncpg://<dispatcher-login>:<password>@<host>/<database>
AZURE_SERVICE_BUS_NAMESPACE=<namespace>.servicebus.windows.net
AZURE_SERVICE_BUS_GENERATION_QUEUE=generation
AZURE_SERVICE_BUS_QUEUE=conversion
```

The existing `DefaultAzureCredential` chain uses an Azure CLI login locally when available; it does
not require managed identity. Run `az login`, use an identity with **Azure Service Bus Data Sender** on
the namespace or the two queues, then submit a job and inspect application logs for the bounded
dispatcher result. A pending outbox row or a safe logged failure is recoverable through the GitHub
Actions workflow; do not retry by calling fal.ai or sending a queue message by hand.

For App Service, add the same nonsecret queue settings and keep
`OUTBOX_AUTO_DISPATCH_ENABLED=false` until the controlled release has verified the new image. Set
`OUTBOX_DISPATCHER_DATABASE_URL` to an App Setting containing a Key Vault reference to
`dispatcher-database-url`, not the ordinary `DATABASE_URL`. Enable the App Service managed identity,
grant it **Key Vault Secrets User** for that secret and **Azure Service Bus Data Sender** for both
queues. `DefaultAzureCredential` selects the managed identity in App Service; Azure CLI is neither
configured nor required there. Verify by creating one job, confirming its `201` response and an
outbox dispatcher log result, then confirm the worker receives the identifier-only message. The GitHub
Actions dispatcher remains available for recovery and manual verification without any API credential
change.

## Controlled API-only dispatcher release

`.github/workflows/deploy-api-outbox-dispatcher.yml` is separate from `ci.yml` and is available only
through `workflow_dispatch` on `main`. It does not read the global compute-release flags and it does
not modify either ACI worker, the frontend Container App, Service Bus, Terraform, or database schema.
The existing `ci.yml` worker-release controller and every one of its safety checks remain unchanged.
The existing **Dispatch submission outbox** workflow remains the fallback dispatcher during and after
this release.

Before the first controlled release, configure these App Service settings without placing any secret
value in GitHub or source control:

```text
OUTBOX_AUTO_DISPATCH_ENABLED=false
OUTBOX_DISPATCHER_DATABASE_URL=@Microsoft.KeyVault(SecretUri=https://<vault>.vault.azure.net/secrets/dispatcher-database-url/)
```

The dedicated Key Vault reference must remain in place for every later release and rollback; never
replace it with `DATABASE_URL` or a literal connection string. Choose an approved full commit SHA
reachable from `main`. The workflow checks out that exact SHA, runs backend linting, type checking,
and tests, then uses the existing GitHub OIDC identity's `AcrPush` permission to publish the backend
image itself when its SHA tag is absent. If that immutable tag already exists, it is reused and is
never overwritten. The workflow resolves the ACR digest after publication or reuse and deploys that
digest, not the tag. Image publication always completes before submissions are paused.

The read-only preflight confirms the existing App Service image and settings. It fails closed unless
`OUTBOX_DISPATCHER_DATABASE_URL` still references `dispatcher-database-url`, the single-reference
Azure API reports `properties.status` as `Resolved`, the API identity has Key Vault and both
queue-sender roles, and the GitHub OIDC identity has both the App Service deployment role and
`AcrPush`. `OUTBOX_AUTO_DISPATCH_ENABLED` may already be `true` after a successful run; requiring it
to be false would prevent a later approved release.

Only after image publication and those read-only checks pass, the workflow sets
`JOB_SUBMISSIONS_ENABLED=false`, changes only the App Service container image, and verifies `/health`
plus the configured digest. It checks the Key Vault reference again, then enables
`OUTBOX_AUTO_DISPATCH_ENABLED=true` for a dispatcher-capable target and verifies health after the
setting recycle before reopening submissions. All other App Service settings, including the private
Key Vault reference, are preserved. A failed run intentionally leaves submissions paused once it has
paused them; its job summary gives the recovery procedure and it never guesses at recovery or rolls
back a database migration.

To roll back, keep submissions paused, inspect the workflow summary and App Service logs, then run
the same API-only workflow on `main` with `rollback=true` and the previously recorded known-good
40-character backend SHA. A rollback requires that exact ACR tag to exist, reuses its resolved
digest, and never builds or overwrites it. It repeats every preflight check and reopens submissions
only after the old image is healthy and the dispatcher secret is resolved. When the rollback target
does not contain the automatic-dispatch implementation, the workflow explicitly sets
`OUTBOX_AUTO_DISPATCH_ENABLED=false` before that final health check. If a run leaves submissions
paused, do not set `JOB_SUBMISSIONS_ENABLED=true` manually: repair the failed prerequisite and rerun
the approved release or rollback until the workflow has verified health and reopened admissions. If
the automatic dispatcher is unavailable, leave it false and manually run **Dispatch submission
outbox**; do not send queue messages directly or retry fal.ai.

The existing all-compute workflow is intentionally inactive until repository variable
`AZURE_DEPLOYMENTS_ENABLED=true` is
set during the first controlled activation. `AZURE_COMPUTE_DEPLOYMENTS_ENABLED` must also be `true`.
Before either variable is enabled, main-branch merges run validation only and make no Azure mutations.

## One-time Azure setup

From `infra/terraform/shared`, initialize the existing shared backend and review a normal plan. It must add only the GitHub deployment identity, its main-branch OIDC credential, and the role assignments in `github_actions.tf`; it must not replace or change existing shared resources. A reviewed operator applies that plan manually.

```powershell
Set-Location infra/terraform/shared
Copy-Item backend.shared.dev.hcl.example backend.shared.dev.hcl
Copy-Item dev.tfvars.example dev.tfvars
# Set github_oidc_subject to the value verified below before planning.
# Populate the already-approved values and preserve the existing shared state key.
terraform init -backend-config=backend.shared.dev.hcl
terraform plan -var-file=dev.tfvars -out "$env:TEMP\image-to-lego-github-oidc.tfplan"
# Review the saved plan. It must contain only the identity, federation credential, and RBAC additions.
terraform apply "$env:TEMP\image-to-lego-github-oidc.tfplan"
```

The saved plan can contain sensitive state data; keep it outside the repository and remove it according to the project's state-handling procedure.

The workflow does not use a GitHub Environment, so its subject is the
main-branch form, not an `environment:` form. GitHub switched repositories
created or migrated after 2026-07-15 to immutable owner/repository IDs. Do not
infer the format from the first commit. Before the first plan, an administrator
must run:

```powershell
gh api repos/regan-tan/image-to-lego --jq '{created_at: .created_at, owner_id: .owner.id, repository_id: .id}'
gh api repos/regan-tan/image-to-lego/actions/oidc/customization/sub
```

This repository was created on 2026-10-06, so it uses the immutable form. Its
verified value is:

```text
repo:regan-tan@108611909/image-to-lego@1406660565:ref:refs/heads/main
```

`infra/terraform/shared/dev.tfvars.example` contains this exact value.
Terraform deliberately has no default for this value, so a different
repository cannot accidentally receive this credential.

It receives `AcrPush` on `itl2b70703f`, resource-scoped deployment roles for the App Service, frontend Container App, and both ACI groups, read-only metadata access to the App Service plan, runtime identities, and two Service Bus queues, plus `Managed Identity Operator` only on the two runtime worker identities. It does not receive Key Vault, Blob, Service Bus data, or Supabase permissions.

Set these GitHub **repository variables** from the Terraform outputs; none are secrets:

| Variable | Value |
| --- | --- |
| `AZURE_DEPLOYMENT_CLIENT_ID` | `terraform output -raw github_deployment_client_id` |
| `AZURE_TENANT_ID` | `terraform output -raw github_deployment_tenant_id` |
| `AZURE_SUBSCRIPTION_ID` | `terraform output -raw github_deployment_subscription_id` |

Do not create an Azure credential for each collaborator. Anyone authorized to merge to `main` can trigger the same repository-scoped OIDC workflow, while Azure authorizes only this deployment identity.

## Worker bootstrap prerequisite

ACI has no revision mechanism. Updating a running ACI group restarts its containers, so this workflow never does it automatically. Before enabling worker releases, complete the bootstrap inventory and conversion-only smoke test in the [Terraform lifecycle runbook](azure-terraform-lifecycle.md). Confirm both live groups use the checked-in `app.workers.aci_bootstrap` command and all required nonsecret environment names.

Only after that reviewed evidence exists, set GitHub repository variable `ACI_WORKER_RELEASES_ENABLED` to `true`. Until then, the deployment fails before publishing images or changing compute. This is deliberate: it prevents the workflow from replacing adopted worker configuration whose command or secure settings have not been verified.

Apply the committed `20261101000000_worker_release_gate.sql` and
`20261102000000_durable_worker_release_coordination.sql` migrations separately. The latter
adds the gate-aware protocol but does not enable it in GitHub Actions. A future controller login
must have only membership in `github_release_coordinator`; do not use the application database
secret for release coordination.

If that controller's heartbeat expires, it is fenced: it cannot renew, resume, transition, or
reopen the gate. A separately authenticated recovery controller must call
worker_release_recover, receive a newer token, and proceed from `blocked`. Expiry itself never
admits work or reopens the gate.

Automatic release remains disabled. The durable protocol now closes the receive-to-lease-claim
race for gate-aware workers, but old worker images do not observe it. Do not use a controller
until an operator has proved every active worker image contains this protocol and completed the
conversion-only smoke test. A stopped ACI instance alone is not proof that provider work is safe.

## Intentional compute downtime

Keep GitHub repository variables `AZURE_COMPUTE_DEPLOYMENTS_ENABLED=false` and
`AZURE_DEPLOYMENTS_ENABLED=false` until the first controlled activation. Pushes to `main` continue to
run all CI validation and finish with an explicit **Azure deployment intentionally disabled** summary;
they do not log in to Azure, build/publish ACR images, or change compute.

After a reviewed Terraform restoration and resource inventory, set `AZURE_COMPUTE_DEPLOYMENTS_ENABLED=true`. If this variable is true and a required compute resource is missing, the release fails before publishing an image. A manual rollback/redeployment (`workflow_dispatch`) also fails while the variable is false, so it cannot be mistaken for a completed release.

## API, frontend, and worker release boundary

The current backend image contains both the API and workers. Queue version `1` is accepted by
both old-compatible and current gate-aware workers; the current workers also accept the legacy
unversioned message. Future incompatible queue or artifact changes require an explicit version
and a coordinated release. The workflow still does **not** automatically deploy API/frontend
changes separately from workers.

The safe current policy is to validate every merge and keep Azure deployment disabled. Eventual
activation requires the durable coordinator described in ADR-008, verified gate-aware workers,
and a workflow implementation that uses its fenced controller transitions. Do not replace this
with a queue-depth or ACI-state check.

## Automated release behavior

Every push to `main`, including a merge by any authorized collaborator, runs the validation relevant to its changed areas. Documentation-only and Terraform-only pushes do not request an Azure application deployment. A backend or frontend change can continue to a complete release only when the following gates succeed:

1. Logs into Azure with GitHub OIDC.
2. Requires `AZURE_COMPUTE_DEPLOYMENTS_ENABLED=true`. When it is false, the workflow records that CI completed without an Azure deployment, image publication, or resource change. A manual rollback/redeployment fails in this mode.
3. Verifies that all five Terraform-managed compute resources still exist. If compute was deliberately destroyed or is unavailable while releases are enabled, it fails before publishing an image or changing a resource.
4. Pauses submissions, then requires zero nonterminal jobs, worker attempts, unresolved provider submissions, undelivered outbox records, and active or scheduled messages on both worker queues. It verifies the dispatcher job, reviewed sender identities, bootstrap contract, and recoverable immutable image before stopping an idle running worker. It then repeats the complete database and queue snapshot before replacing it. Missing or ambiguous evidence is a failed prerequisite, not a successful release skip.
5. Builds and pushes backend and frontend images tagged with the full commit SHA. Existing tags are rejected rather than overwritten, then their ACR digests are recorded in the workflow summary.
6. Updates the App Service container image, both ACI workers with the full Terraform bootstrap contract (managed identities, ACR identity, Key Vault settings, restart policy, commands, and environment), and the frontend Container App image. If any mutation fails, the run reports the completed components as a partial release rather than claiming success.
7. Checks API `/health`, frontend HTTPS availability, and that each replacement worker reaches `Running`; it reports image tags, digests, and URLs.

The deployment job has its own non-cancelling concurrency group. A newer merge waits rather than interrupting a release already changing Azure resources. The workflow does not run Terraform apply and does not run Supabase migrations.

## Failure and rollback

If the post-deployment check fails, the workflow stops and preserves the emitted SHA/digest evidence. It does not guess at a rollback and it never rolls back database migrations.

To redeploy a previously verified image, run **CI → Run workflow** on `main` and enter its recorded 40-character `release_sha`. The workflow verifies that both corresponding ACR images already exist, then uses the same stopped-worker and `JOB_SUBMISSIONS_ENABLED=false` gates before changing compute. Do not select a pre-bootstrap worker image such as `dev-20261029-205014`.

If a lease query, queue count, sender inventory, worker bootstrap contract, compute inventory, or submissions gate cannot be proven, the release fails closed before image publication. Follow the lifecycle runbook to reconcile the condition; do not bypass the guard or infer safety from queue depth.
