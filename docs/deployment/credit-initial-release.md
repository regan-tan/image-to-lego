# Credit initial-release procedure

This is a **paused initial release** for `20261123000000_credits.sql`. It is
not an ordinary deployment procedure and it never reopens
`JOB_SUBMISSIONS_ENABLED`. The normal CI deployment job is intentionally
disabled; do not enable it as part of this release.

## Preconditions

- `JOB_SUBMISSIONS_ENABLED=false` is confirmed in App Service.
- The API is already using the resolved `api-database-url` Key Vault reference.
- Generation and conversion workers remain on their current credentials until
  each is deliberately replaced after the migration.
- The dispatcher remains unchanged, including `dispatcher-database-url` and
  its existing identity/configuration.
- The drain record is clean: no queued/running jobs, active leases, queue
  messages, or undelivered outbox rows.
- Production migration history contains
  `20261122000000_security_definer_function_permissions.sql` and does **not**
  contain `20261123000000_credits.sql`. Compare the complete ordered history
  with `supabase/migrations/`; do not backfill, rename, edit, or rerun either
  migration.

## Prepare an immutable tested image

1. Merge the reviewed release commit normally. Do not deploy from a local
   worktree or a branch-only SHA.
2. Manually run **Prepare credit initial release** from `main`, giving its full
   40-character reachable commit SHA. It runs backend/frontend validation and
   creates or verifies immutable ACR SHA tags. It changes no runtime resource.
3. Record both ACR digests from the workflow summary. SHA tags are only a
   lookup aid; every later component change must use the recorded digest. The
   API workflow requires that digest before it will reuse an existing SHA tag.

## Paused component sequence

1. Reconfirm submissions are false and repeat the drain/queue/outbox snapshot.
2. Keep the drained workers **running but idle**. Do not stop, terminate, or
   delete their ACI groups: ACI only supports an in-place update for a running
   group. The old API remains paused and continues to use `api-database-url`;
   do not deploy the credit-aware API yet. With zero queue messages and no
   nonterminal jobs, the old workers receive no work and make no credit calls.
3. Apply `20261123000000_credits.sql` once through the approved migration
   process. Capture its migration-history row. A failure is a **NO-GO**: leave
   the gate closed, preserve the error/history, and make a reviewed forward
   repair. Never retry a partly applied non-rerunnable migration blindly.
4. Grant the already-provisioned API and worker logins their documented credit
   capability roles. Test each login's intended functions and denied functions;
   test browser-role denial and two-owner RLS isolation.
5. Deploy the credit-aware API image, retaining `DATABASE_URL=api-database-url`
   and the existing dispatcher setting. Verify health, the resolved Key Vault
   reference, authenticated project reads, the owner-scoped credit read, and
   that both submission endpoints remain paused without creating jobs or outbox
   records.
6. Update the generation worker in place only, keeping the gate closed. Do not
   delete its ACI group: its scoped ACI role assignment is attached to that
   resource. Redeploy the complete reviewed group contract—not a partial
   command—so CPU (1), memory (2 GiB), restart policy (`Never`), user-assigned
   identity, ACR identity, all non-secret environment variables, and `fal-key`
   remain intact. Change only the digest-pinned image and
   dedicated `generation-worker-database-url`, validate startup and its three
   credit-worker functions, then drain/reconcile before continuing.
7. Update the conversion worker in place similarly with
   `conversion-worker-database-url`, preserving the same complete contract and
   `AZURE_TOKEN_CREDENTIALS=ManagedIdentityCredential`. Keep the existing
   dispatcher untouched.
8. Verify both workers, the API credit read, Key Vault resolution, migration
   history, zero nonterminal jobs, zero active leases, empty queues, and all
   outbox messages delivered. Submission endpoint tests must still return the
   paused response.

The current global gate has no allowlist, so do not create charged production
smoke jobs while it remains closed. Reopening submissions is a separate human
approval and release decision, outside this procedure.

## Component rollback while submissions are closed

| Component | Safe rollback before credit-bearing jobs | Boundary after jobs are accepted |
| --- | --- | --- |
| API | Restore the prior immutable API image while retaining `JOB_SUBMISSIONS_ENABLED=false` and the API credential reference. | Do not revert to an image that can create uncharged jobs or cannot read credit-aware state. Forward-fix instead. |
| Generation worker | Restore only its previous image/credential after it is stopped and leases are reconciled. | Do not run a pre-credit worker against accepted credit-bearing generation jobs; it cannot safely reconcile refunds. |
| Conversion worker | Restore only its previous image/credential after it is stopped and leases are reconciled. | Same restriction: forward-fix after a charged conversion is accepted. |
| Database migration | No rollback migration is approved. | The migration is non-rerunnable and credit ledger entries may exist; use a reviewed forward migration only. |
| Dispatcher | Leave its identity and `dispatcher-database-url` unchanged; use its existing operational recovery. | Do not change it merely to address credit behavior; unresolved publication state needs its normal reconciliation. |

If a component fails at any point, keep submissions closed. Record image SHA,
digest, migration history, queue/outbox state, and the exact failed check before
attempting its component-specific rollback or a forward repair.
