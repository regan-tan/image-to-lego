# Image-to-LEGO — Azure / Terraform / CI-CD Readiness Audit

**Audit basis:** `image-to-lego-main (1).zip`, Azure screenshot supplied 2026-10-28, CS464 proposal guidelines, capstone assessment rubric, and `Design choices - Sheet1.pdf`. This is a source/static review, not a live Azure resource audit or deployed acceptance test.

**Current deployment note:** This historical audit predates the implemented Terraform configuration.
The current Azure for Students subscription cannot provision Static Web Apps in any policy-permitted
region; ADR-007 and `azure-cicd-plan.md` supersede its Static Web Apps recommendation with an Nginx
frontend Azure Container App.

## 1. Scope and evidence

- ZIP contains **295 actual files** (340 ZIP entries including directories).
- `backend`: 107 files, including 25 `test_*.py` modules and a Dockerfile.
- `frontend`: 75 files, including a React/TypeScript SPA and Vitest tests.
- `supabase`: four SQL migrations and configuration.
- `docs`: 13 files including six ADRs and `docs/deployment/azure-cicd-plan.md`.
- `.github/workflows/ci.yml` exists; `infra/` contains **only `README.md`**, not Terraform/Bicep.
- Approximately 25,600 source/config lines across 166 `.py`, `.ts`, `.tsx`, `.sql`, and `.yml` files.

## 2. Implementation map

| Component | Observed code evidence | Readiness interpretation |
| --- | --- | --- |
| Public SPA and protected workspace | `frontend/src/App.tsx`; Supabase client; `/`, `/login`, `/signup`, `/workspace`, `/projects/:projectId`, `/profile` | Implemented; deploy and smoke-test |
| Backend API | `backend/app/main.py`, `backend/app/api/v1/` | Implemented; validate in Container Apps |
| Auth | `backend/app/core/auth.py`, DB RLS migrations | JWT/JWKS verification and tenant ownership checks implemented; JWKS caching deferred |
| DB | `supabase/migrations/*.sql`, SQLAlchemy repositories | Schema and data access implemented; production availability and backup runbook not proven |
| Direct uploads | `backend/app/providers/blob_storage.py`, `frontend/src/api/client.ts` | User-delegation SAS mechanism implemented; deployed CORS and RBAC not proven |
| Generation | `backend/app/workers/generation_worker.py`, fal.ai provider | Queue consumer/provider integration implemented; deployment not proven |
| Conversion | `backend/app/workers/conversion_worker.py`, geometry code | Versioned LEGO serialization, catalog and Build Guide V2 implemented in source |
| Queue | `backend/app/providers/*queue.py` | Azure Service Bus adapters and workers implemented; queues, role assignments and scale rules must be checked |
| Containers | `backend/Dockerfile` | One reusable backend image; use startup command overrides for workers |
| CI | `.github/workflows/ci.yml` | Backend Ruff/mypy/pytest/Docker build and frontend lint/Vitest/build configured; no release automation |
| Terraform | `infra/README.md` | Not implemented |

## 3. Azure screenshot: what is known and unknown

Screenshot shows an **Azure for Students** subscription, existing resource group **`rg-image-to-lego-dev`**, **storage account `storageimgtolego`**, and **Service Bus namespace `image-to-lego-bus-dev-01`** in **Malaysia West**. It is the **Recent resources** view, not an exhaustive resource inventory. It does not establish container creation, two queues, service tiers/roles, storage region/container, running apps, cost balance, or deployed endpoints.

**Immediate safety rule:** do not have Terraform create a duplicate resource group, account or namespace; choose data-source-only reference or deliberate Terraform state import after checking configuration/drift and permissions. Never run an unreviewed apply/destroy.

## 4. Target architecture grounded in repository

Browser → Static Web Apps (React/Vite) + Supabase Auth → FastAPI in Azure Container Apps → Supabase PostgreSQL, private Azure Blob Storage, two Service Bus queues → generation worker (fal.ai TRELLIS) and conversion worker (CPU). One SHA-tagged image in Azure Container Registry runs API and both workers with different commands. Key Vault + managed identity, Log Analytics, GitHub Actions OIDC complete the intended deployment.

**No Azure GPU needed for the initial target architecture:** fal.ai runs the heavy image-to-3D inference. Conversion workers need CPU/memory profiling, not unverified GPU assumptions.

## 5. Important risks and gaps

1. **Existing Azure resources vs Terraform**: untracked manual resources create duplication/drift/destruction risk. Design `data` references or imports (with explicit approval and reviewed plan).
2. **Deployment plan contradicts current intent**: `docs/deployment/azure-cicd-plan.md` explicitly defers Terraform; update it and ADR-004 after the new human-approved decision.
3. **Documentation inconsistencies**: `Design choices` sometimes says Supabase Storage; live code and ADR-005 use Azure Blob Storage. `docs/architecture/README.md` claims conversion integration is not implemented; README/code show it is. Reconcile.
4. **JWKS repeated HTTP fetches**: `backend/app/core/auth.py` calls `fetch_jwks` during bearer verification, without an in-process cache. Add bounded public-key-only cache and unknown-kid refresh before load testing; never cache user tokens.
5. **Message lock duration**: generation/conversion workers use `receive_messages` → await processing → complete/abandon. No automatic lock renewal was evident. Validate workload duration and lock expiration; add safe lock handling/renewal if needed, test duplicate delivery and idempotency.
6. **Deployment permissions**: Azure for Students and SMU tenant may constrain RBAC role-assignment and workload-identity creation. Confirm membership, provider registration, region availability and quota before Terraform implementation.
7. **Blob SAS RBAC**: API/worker identities issuing user-delegation SAS need `generateUserDelegationKey` permission at account or higher scope, in addition to appropriate Blob data access. Cross-origin browser PUT also needs exact-origin CORS.
8. **CI gating**: current change-detection workflow focuses on frontend/backend and `.github/workflows/ci.yml`. Terraform, migration and deployment-only PR changes need appropriate validation and branch-protection gates.
9. **Operational gaps**: health response only indicates the API process; add dependency/readiness and integration smoke tests, without exposing private configuration. Monitor queue backlogs/DLQs, failures, usage and budget.
10. **Backup/rollback**: Supabase Free downtime and lack of automated external DB backup/restore tests must be clearly stated; immutable image/revision rollback does not undo DB migrations.
11. **Region mismatch risk**: Service Bus is in Malaysia West; design plan prefers Southeast Asia near Singapore-based Supabase. Verify actual regions and measure/justify cross-region placement before adding more services.
12. **Costs**: Azure for Students credit is finite. Configure budgets/alerts, maximum replicas, scale-to-zero where suitable, and fal.ai request caps. Do not assume resources or logs are all free.

## 6. Recommended IaC and CI/CD phases

**Phase 0 — Read-only inventory and architecture decision**
- Verify subscription, region/quotas, exact SKU/region/status and IDs of the resource group, storage, namespace and two queues.
- Verify student subscription remaining credits, tenancy and ability to create RBAC/OIDC identities.
- Inspect actual secrets configuration and existing Supabase/fal.ai/Blob connectivity without outputting secrets.
- Decide which existing resources are `data` references and which should be imported and managed.
- Update deployment ADR/plan to explicitly adopt Terraform and record trade-offs.

**Phase 1 — Terraform plan-only**
- Provider/version locks, single `dev` environment, variables/outputs, storage state backend bootstrap, resource-group boundaries.
- Model/lookup existing storage account and Service Bus; add private artifact container, queues if missing, ACR Basic, Container Apps environment, four apps, identities and scoped roles, KV, Log Analytics/budget.
- Ensure no secret values in code, outputs, unencrypted local Terraform state or CI logs.
- Run `terraform fmt`, `validate`, security review, and human-reviewable `plan`; **no automatic apply**.

**Phase 2 — CI/CD**
- Extend existing CI with Terraform checks for infra changes, migration testing, frontend/backend quality and Docker image build.
- Use GitHub OIDC to Azure with least privilege and environment protection for apply/deploy.
- Deploy one git-SHA-tagged backend image to API, generation and conversion Container Apps, then deploy the Nginx frontend image with its public runtime configuration.
- Apply reviewed, backward-compatible database migrations as a separate controlled step.

**Phase 3 — Controlled dev deployment and evidence**
- Manually approve Terraform application and initial deployment.
- Verify HTTPS SPA and deep-link fallback, Supabase redirects, CORS, public API auth, blob SAS direct upload, generation/fal.ai/GLB conversion, LEGO JSON, verified parts and V2 guide.
- Test unauthorized/cross-user data access; worker retry/lock/DLQ; failure and rollback; logging/alerts, budget.

**Phase 4 — Capstone demonstration**
- Collect screenshot/CLI/CI evidence: terraform plan, resource inventory, CI pass and release SHA, 3 running/scalable apps, queue and private Blob, end-to-end outcome, cost and latency charts, logs and rollback.
- Report measured results vs proposed scale assumptions rather than claiming validated capacity without load testing.

## 7. Capstone rubric alignment

The XLSX rubric assesses **11 categories**: Database Design, Scalability, Project Complexity, Code Cleanliness, Backend API Design, Frontend Client Code, Cloud Deployment, Innovation, Documentation, Testing, Teamwork. Excellent cloud deployment requires containerization, automated CI/CD, cloud-native scalability and cost efficiency. A purely local prototype cannot demonstrate that criterion. The proposal PDF separately assigns Executive Summary 15, System Architecture 30, Data & Security 20, Implementation 25, Success Metrics 10; do not confuse these two assessment instruments.

Prioritized evidence: (1) cloud deployment functioning, (2) security and queue/storage authorization, (3) deterministic end-to-end tests including real database, (4) measured latency/cost/scaling and accuracy, (5) documentation/ADRs/ERD, (6) PR ownership/reviews.

## 8. Suggested first task after branch creation

**Only read-only inventory/design, not deployment.** Produce a `docs/deployment/azure-readiness-audit.md` or similar identifying actual services, IAM gaps, Terraform-managed-vs-referenced inventory, revised architecture, projected costs, and a safe phased plan. Confirm access/credits before starting provisioning. No commits, pushes, resource creation, Terraform apply or destructive operations without human approval.

## 9. External verification references

- Azure Container Apps scaling: https://learn.microsoft.com/en-us/azure/container-apps/scale-app
- Azure Container Apps billing: https://learn.microsoft.com/en-us/azure/container-apps/billing
- Azure Student subscriptions: https://azureforeducation.microsoft.com/en-us/Student
- Service Bus feature comparison: https://azure.microsoft.com/en-us/pricing/details/service-bus/
- Microsoft Entra OIDC from GitHub: https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure
- Terraform import: https://developer.hashicorp.com/terraform/cli/import/usage
- Blob user-delegation SAS role requirements: https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-user-delegation-sas-create-dotnet
- SPA fallback: https://learn.microsoft.com/en-us/azure/static-web-apps/configuration
