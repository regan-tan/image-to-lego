# ADR-004: Azure cloud platform

## Status

Accepted for future deployment

## Context

The system needs independently scalable containers, a registry, durable messaging, object storage, secret management, and CI/CD authentication.

## Decision

Target Azure Container Apps for the API and worker, Azure Container Registry for images, Azure Service Bus for durable jobs, Azure Blob Storage for artifacts, Azure Key Vault for secrets, and Azure Static Web Apps for the SPA. Use GitHub OIDC for future deployments.

## Alternatives considered

- Kubernetes, whose cluster operations and flexibility exceed this project's needs.
- VM-based deployment, which adds patching and process-management work.
- A multi-cloud design, which increases integration and operational complexity.

## Rationale

The selected managed services cover the required runtime patterns while keeping the architecture understandable for a capstone team.

## Trade-offs / consequences

The design accepts Azure coupling, service quotas, and cloud cost management. Local development needs fakes or emulators where available. Infrastructure and deployment changes require review; this ADR does not provision anything.

