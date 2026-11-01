# GitHub Actions Azure release setup

This is the release procedure for the existing development environment. It uses the deployed topology, not the historical Container Apps proposal: a Linux App Service API, a frontend Container App, and two `restart_policy = Never` ACI workers.

Nothing in this document authorizes a Terraform apply or a deployment. The initial identity setup and every release run require the normal human review process.

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

Apply the committed `20261101000000_worker_release_gate.sql` migration separately, then create a dedicated login with only membership in `github_release_gate` and store its connection string as the GitHub Actions secret `DEPLOYMENT_DATABASE_URL`. This login can call only the worker-lease aggregate; it cannot read job rows. Do not use the application database secret for this purpose.

When either worker is running, a release intentionally fails after its read-only preflight. Do not stop a worker based on that snapshot: the current protocol has no durable release lock that closes the interval between a queue receive and its database lease claim. This PR can recreate a worker only when it is already stopped under a separately approved maintenance procedure that establishes no active job. Designing that transition safely is an unresolved architecture change, not an operator shortcut.

## Intentional compute downtime

Set the GitHub repository variable `AZURE_COMPUTE_DEPLOYMENTS_ENABLED=false` before a reviewed compute teardown. Pushes to `main` continue to run all CI validation and finish with an explicit **Azure deployment intentionally disabled** summary; they do not log in to Azure, build/publish ACR images, or change compute. This lets collaborators merge reviewed code without a misleading deployment success or unnecessary Azure cost.

After a reviewed Terraform restoration and resource inventory, set `AZURE_COMPUTE_DEPLOYMENTS_ENABLED=true`. If this variable is true and a required compute resource is missing, the release fails before publishing an image. A manual rollback/redeployment (`workflow_dispatch`) also fails while the variable is false, so it cannot be mistaken for a completed release.

## API, frontend, and worker release boundary

The current backend image contains both the API and workers, but the codebase has no version-negotiation or durable worker-draining protocol. A new API can create durable work that an older worker image may not understand, and a running worker can receive a queue message after a preflight snapshot but before claiming its database lease. Therefore this workflow does **not** automatically deploy API/frontend changes separately from workers yet.

The safe current policy is to validate every merge, publish and deploy the complete approved release only when both workers are already stopped and the worker gate is satisfied. A truly automatic split release, or a safe transition from running workers to stopped workers, would require an approved architecture change: a durable release lock checked atomically by worker lease acquisition, worker/API compatibility versioning for durable jobs and artifacts, and regression tests for mixed-version operation. Those controls are not added by this PR.

## Automated release behavior

Every push to `main`, including a merge by any authorized collaborator, runs the validation relevant to its changed areas. Documentation-only and Terraform-only pushes do not request an Azure application deployment. A backend or frontend change can continue to a complete release only when the following gates succeed:

1. Logs into Azure with GitHub OIDC.
2. Requires `AZURE_COMPUTE_DEPLOYMENTS_ENABLED=true`. When it is false, the workflow records that CI completed without an Azure deployment, image publication, or resource change. A manual rollback/redeployment fails in this mode.
3. Verifies that all five Terraform-managed compute resources still exist. If compute was deliberately destroyed or is unavailable while releases are enabled, it fails before publishing an image or changing a resource.
4. Requires `JOB_SUBMISSIONS_ENABLED=false`, no unexpired durable worker lease, and zero active or scheduled messages on both worker queues. It additionally proves the only queue senders are the reviewed API and worker identities, so paused submissions cannot race in a new job. Empty queues alone are never sufficient evidence of safety. A running worker is never updated automatically because ACI updates restart every container and a lease/queue snapshot cannot close the receive-to-claim race. The workflow only deletes and recreates workers that were already stopped or terminal, match the reviewed bootstrap contract, have no secure environment variables, and have an existing immutable release image available for restoration. Missing compute is a failed prerequisite, not a successful release skip.
5. Builds and pushes backend and frontend images tagged with the full commit SHA. Existing tags are rejected rather than overwritten, then their ACR digests are recorded in the workflow summary.
6. Updates the App Service container image, both ACI workers with the full Terraform bootstrap contract (managed identities, ACR identity, Key Vault settings, restart policy, commands, and environment), and the frontend Container App image. If any mutation fails, the run reports the completed components as a partial release rather than claiming success.
7. Checks API `/health`, frontend HTTPS availability, and that each replacement worker reaches `Running`; it reports image tags, digests, and URLs.

The deployment job has its own non-cancelling concurrency group. A newer merge waits rather than interrupting a release already changing Azure resources. The workflow does not run Terraform apply and does not run Supabase migrations.

## Failure and rollback

If the post-deployment check fails, the workflow stops and preserves the emitted SHA/digest evidence. It does not guess at a rollback and it never rolls back database migrations.

To redeploy a previously verified image, run **CI → Run workflow** on `main` and enter its recorded 40-character `release_sha`. The workflow verifies that both corresponding ACR images already exist, then uses the same stopped-worker and `JOB_SUBMISSIONS_ENABLED=false` gates before changing compute. Do not select a pre-bootstrap worker image such as `dev-20261029-205014`.

If a lease query, queue count, sender inventory, worker bootstrap contract, compute inventory, or submissions gate cannot be proven, the release fails closed before image publication. Follow the lifecycle runbook to reconcile the condition; do not bypass the guard or infer safety from queue depth.
