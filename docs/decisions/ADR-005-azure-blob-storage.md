# ADR-005: Azure Blob Storage for artifacts

## Status

Accepted; source-image upload path implemented

## Context

Source images and generated GLB, OBJ, LDraw, and BOM files are binary artifacts that can be large. PostgreSQL should retain queryable metadata without becoming a file server.

## Decision

Store artifact bytes in Azure Blob Storage and store only metadata, integrity hashes, MIME types, sizes, provenance, and blob names in PostgreSQL. Do not use Supabase Storage.

## Alternatives considered

- PostgreSQL large objects/bytea, which increases database size, backup cost, and delivery load.
- Supabase Storage, which conflicts with the selected Azure deployment and duplicates object-storage boundaries.
- Local container filesystems, which are ephemeral and cannot support independent replicas.

## Rationale

Blob Storage provides durable object semantics, scalable delivery, lifecycle controls, and managed-identity integration while keeping relational backups focused on metadata.

## Trade-offs / consequences

Database and blob writes are not a single transaction, so workflows need cleanup/reconciliation and idempotent naming. Authorization for upload/download must be designed carefully, and stored bytes must be validated at the trust boundary before paid processing.

## Implementation note

The source-image slice uses a 10-minute HTTPS user-delegation SAS scoped to one server-generated
blob name with create-only permission. The browser uploads the binary directly. FastAPI stores a
pending artifact before issuing the SAS and marks it ready only after confirming Blob properties,
including the client-declared SHA-256 metadata. This confirmation does not cryptographically verify
the Blob bytes. Before paid fal submission, the future generation worker must validate actual stored
bytes, including content type, resource bounds, and a recomputed SHA-256. Scheduled cleanup and
generated-model download authorization remain future work.

