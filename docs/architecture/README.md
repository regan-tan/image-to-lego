# Intended architecture

Status: **Authenticated profile, project metadata, direct source-image upload, and queued image-to-3D
reconstruction are implemented. Conversion, browser 3D inspection, and production deployment are not.**

```mermaid
flowchart LR
    Web["React / Vite SPA<br/>Auth + project/upload UI"] -->|"Bearer access token<br/>metadata REST /api/v1"| API["FastAPI API<br/>profile + projects + uploads"]
    API -->|"JWKS signature verification<br/>implemented"| Supabase["Supabase Auth<br/>identity source"]
    API -->|"owner-scoped metadata<br/>implemented"| SupabaseDb["Supabase PostgreSQL<br/>projects + artifact lifecycle"]
    API -->|"single-blob create-only SAS + declared-metadata confirmation<br/>implemented"| Blob["Azure Blob Storage<br/>private source images"]
    Web -->|"direct HTTPS PUT<br/>binary never enters API"| Blob
    API -->|"job/run + identifier-only message"| Bus["Azure Service Bus<br/>generation queue"]
    Bus -->|"at-least-once delivery"| Worker["Python generation worker"]
    Worker -->|"submit/status/result"| Fal["fal.ai / TRELLIS"]
    Worker -->|"validated source + canonical GLB"| Blob
```

## Dependency boundaries

Runtime dependencies point inward:

```text
API route -> application service -> repository/provider protocol -> infrastructure adapter
```

- Route handlers translate HTTP input/output and remain free of SQL and provider-specific code.
- Services own validation, business rules, and orchestration.
- Purpose-specific repositories isolate PostgreSQL persistence. There is no generic repository base class.
- The reconstruction protocol owns provider-neutral request/status models. The fal.ai adapter translates TRELLIS queue responses at this boundary.
- Binary content belongs in Azure Blob Storage; PostgreSQL stores artifact metadata and blob names only.
- CPU-intensive mesh conversion runs in an independently deployed worker image, never in a request handler or FastAPI `BackgroundTasks`.

## Job delivery and idempotency

Azure Service Bus is the durable generation transport. Delivery is at least once, so the generation
worker treats duplicate messages as normal. The database uniqueness constraint on `(project_id, type,
idempotency_key)` establishes the API idempotency boundary. Once persisted, `provider_job_id` prevents
normal duplicate delivery from submitting another paid fal request. A unique partial index makes output
artifact publication idempotent for each reconstruction job.

The API creates the durable job/run before publishing. This slice intentionally does not add a
transactional outbox: a failed initial publish marks the new job failed and returns 503. If a worker
crashes after claiming a provider submission but before persisting its ID, later delivery treats the
running, ID-less job as ambiguous: it waits while the claim is fresh and then fails it unconfirmed rather
than risking duplicate paid work. The design does not claim distributed exactly-once delivery.

## Trust boundaries

Supabase Auth issues browser identities. The SPA uses the Supabase client for email/password and OAuth flows, including browser session persistence and token refresh. FastAPI independently verifies the access token's JWKS signature, issuer, audience, and expiry, and treats the verified `sub` as the current user ID for `GET /api/v1/profile`. Authentication does not differ by sign-in provider. This verification requires Supabase asymmetric signing keys; ES256 is preferred and RS256 is also accepted. All application tables have RLS enabled and intentionally have no permissive browser policies. Production credentials will be supplied at runtime through managed configuration/Key Vault; they must never be embedded in images or frontend bundles.

Project and artifact transactions derive ownership only from the verified JWT `sub`. The API sets
that UUID in the transaction-local `app.current_user_id` PostgreSQL setting, and RLS policies on
`projects` and `artifacts` enforce the same ownership boundary. The API database role must not own
the tables or have `BYPASSRLS`.

## Source-image lifecycle

```mermaid
sequenceDiagram
    participant Browser
    participant API
    participant DB as PostgreSQL
    participant Blob as Azure Blob Storage

    Browser->>API: Upload metadata, size, MIME type, SHA-256, project ID
    API->>DB: Validate owner + rolling quota; insert pending artifact
    API-->>Browser: Single-blob create-only SAS (10 minutes)
    Browser->>Blob: PUT bytes directly with MIME and SHA-256 metadata
    Browser->>API: Complete upload
    API->>Blob: Confirm existence and expected declared properties
    API->>DB: pending -> ready
```

Pending uploads expire after 24 hours by default. This slice represents that expiry in metadata but
does not implement scheduled cleanup. SAS URLs are ephemeral and are not stored in PostgreSQL.
`ready` means the direct upload is present with the expected client-declared metadata and can enter
downstream server-side validation. It does not mean the API has cryptographically verified the Blob
bytes. Before a paid fal submission, the generation worker downloads a bounded copy, recomputes
SHA-256, and verifies the JPEG/PNG/WebP signature against the artifact MIME type. It gives fal only a
short-lived, read-only, blob-scoped SAS. Its configured lifetime must cover the maximum reconstruction
runtime plus a five-minute pickup buffer so queued provider work does not normally lose source access.
On success the worker bounds the provider model download and
copies the verified GLB to the application's private canonical Blob path; fal URLs are never canonical
state. Blob SAS access requires
HTTPS; production browser origins must use HTTPS, while local development may use
`http://localhost:5173` in the Blob CORS allowlist.

