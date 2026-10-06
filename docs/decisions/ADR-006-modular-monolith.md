# ADR-006: Pragmatic modular monolith

## Status

Accepted

## Context

The project has distinct HTTP, business, persistence, provider, and CPU-worker concerns, but one small team and one product domain. Premature service boundaries would add deployments and distributed failure modes.

## Decision

Use a monorepo and modular Python application with dependency direction `route -> service -> repository/provider -> infrastructure`. Run the API and conversion worker as separate processes from the same backend image. Use purpose-specific protocols only where an external or persistence boundary exists.

## Alternatives considered

- Microservices, which add network contracts, distributed observability, and deployment coordination too early.
- A layered monolith without module boundaries, which makes SQL and provider details prone to leaking into routes.
- Generic repository and service base classes, which obscure domain-specific operations without demonstrated reuse.

## Rationale

This structure keeps changes local and testable while preserving the option to extract a component only after operational evidence justifies it.

## Trade-offs / consequences

Modules share a release cadence and require review discipline to maintain boundaries. The worker is operationally independent but not a separate service codebase. Extraction remains possible but is not free.

