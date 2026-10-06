# Intended architecture

Status: **Foundation plus the first authenticated profile slice implemented; production integrations are not implemented.**

```mermaid
flowchart LR
    Web["React / Vite SPA<br/>Supabase Auth implemented"] -->|"Bearer access token<br/>REST /api/v1"| API["FastAPI API<br/>health + profile implemented"]
    API -->|"JWKS signature verification<br/>implemented"| Supabase["Supabase Auth<br/>identity source"]
    API -->|"metadata<br/>not implemented"| SupabaseDb["Supabase PostgreSQL<br/>migration only"]
    API -->|"artifacts<br/>not implemented"| Blob["Azure Blob Storage<br/>not implemented"]
    API -->|"provider adapter<br/>not implemented"| Fal["fal.ai / TRELLIS<br/>not implemented"]
    API -->|"durable jobs<br/>not implemented"| Bus["Azure Service Bus<br/>not implemented"]
    Bus -->|"at-least-once delivery"| Worker["Python conversion worker<br/>entry point only"]
    Worker -->|"LDraw, BOM, GLB/OBJ<br/>not implemented"| Blob
```

## Dependency boundaries

Runtime dependencies point inward:

```text
API route -> application service -> repository/provider protocol -> infrastructure adapter
```

- Route handlers translate HTTP input/output and remain free of SQL and provider-specific code.
- Services own validation, business rules, and orchestration.
- Purpose-specific repositories isolate PostgreSQL persistence. There is no generic repository base class.
- The reconstruction protocol owns provider-neutral request/status models. A future fal.ai adapter must translate TRELLIS responses at this boundary.
- Binary content belongs in Azure Blob Storage; PostgreSQL stores artifact metadata and blob names only.
- CPU-intensive mesh conversion runs in an independently deployed worker image, never in a request handler or FastAPI `BackgroundTasks`.

## Job delivery and idempotency

Azure Service Bus is the intended durable transport. Delivery will be at least once, so a worker must treat duplicate messages as normal. The database uniqueness constraint on `(project_id, type, idempotency_key)` establishes the first idempotency boundary. A production implementation must also make artifact publication and job-state transitions retry-safe before messages are completed.

## Trust boundaries

Supabase Auth issues browser identities. The SPA uses the Supabase client for email/password and OAuth flows, including browser session persistence and token refresh. FastAPI independently verifies the access token's JWKS signature, issuer, audience, and expiry, and treats the verified `sub` as the current user ID for `GET /api/v1/profile`. Authentication does not differ by sign-in provider. This verification requires Supabase asymmetric signing keys; ES256 is preferred and RS256 is also accepted. All application tables have RLS enabled and intentionally have no permissive browser policies. Production credentials will be supplied at runtime through managed configuration/Key Vault; they must never be embedded in images or frontend bundles.

