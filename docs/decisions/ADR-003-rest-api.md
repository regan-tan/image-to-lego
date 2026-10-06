# ADR-003: REST API

## Status

Accepted

## Context

The SPA needs a stable interface for projects, uploads, job submission/status, artifact metadata, and downloads. The initial team and domain do not require multiple independently evolving graph consumers.

## Decision

Expose a JSON REST API under `/api/v1`, with `/health` retained as an unversioned operational probe. Use resource-oriented endpoints, explicit schemas, conventional status codes, and generated OpenAPI documentation.

## Alternatives considered

- GraphQL, which adds schema/resolver and authorization complexity without a current query-shape need.
- gRPC, which is less convenient for the browser-facing SPA and operational inspection.
- An unversioned API, which leaves fewer options for future compatibility management.

## Rationale

REST maps clearly to the current resources, is easy to test and observe, and is directly supported by FastAPI and browser clients.

## Trade-offs / consequences

Some screens may require multiple requests, and endpoint compatibility must be managed intentionally. Long-running operations return job resources rather than holding requests open.

