# ADR-001: PostgreSQL managed by Supabase

## Status

Accepted

## Context

The product needs relational ownership, project, job, run, and artifact metadata plus user authentication. Binary artifacts are large and have different lifecycle and delivery requirements from metadata.

## Decision

Use Supabase-managed PostgreSQL for relational metadata and Supabase Auth for identity. FastAPI is initially the application data-access boundary. Enable RLS on application tables, but add no permissive browser policies until direct client access has a reviewed use case. Do not use Supabase Storage.

## Alternatives considered

- Self-managed PostgreSQL, which adds operational work unsuitable for the capstone.
- MongoDB, which weakens the natural relational model and transaction guarantees.
- Direct browser database access from the outset, which broadens the security surface prematurely.

## Rationale

PostgreSQL provides constraints, transactions, JSONB for bounded settings payloads, and mature async Python support. Supabase adds managed operation and Auth without forcing data access out of the API.

## Trade-offs / consequences

The team depends on Supabase's managed platform and must validate migrations against its PostgreSQL version. RLS still requires deliberate policy design even when the service role is the initial access path. Artifact bytes require a separate storage system.

