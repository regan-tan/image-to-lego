# Future Azure CI/CD plan

This document is a plan only. The repository does not provision Azure resources or deploy workloads.

## Proposed release flow

```text
merge to main
  -> required CI succeeds
  -> GitHub OIDC login to Azure
  -> build API/worker image tagged with the git SHA
  -> push immutable image to Azure Container Registry
  -> apply reviewed PostgreSQL migrations
  -> deploy API Azure Container App revision
  -> deploy worker Azure Container App revision
  -> smoke test API /health
  -> promote, or roll back to the prior healthy revisions
```

The API and worker use the same image but different startup commands. Deployment configuration should set independent scaling, health, and resource policies for each Container App.

## Security and release rules

- GitHub Actions must authenticate with Azure using OIDC/federated identity.
- Long-lived Azure client secrets must not be stored in GitHub.
- The federated identity and deployment permissions must be scoped to this project's resource group.
- Production images must use immutable git-SHA tags. A mutable convenience tag must never be the deployment source of truth.
- Database migrations require review, backup/recovery consideration, and a single controlled execution before compatible application revisions are promoted.
- Key Vault references or managed identities should supply secrets at runtime; credentials must not be build arguments or image layers.
- Smoke tests must be read-only and rollbacks must select a previously verified immutable image/revision.

