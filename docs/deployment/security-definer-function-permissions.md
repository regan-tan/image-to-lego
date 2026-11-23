# SECURITY DEFINER function permissions

## Scope

`20261122000000_security_definer_function_permissions.sql` is a forward-only
remediation for the 17 postgres-owned internal `SECURITY DEFINER` functions
introduced by the worker-release and submission-outbox migrations. They are not
browser RPCs. The FastAPI repositories call the submission functions, workers
call the worker functions, the dispatcher calls the outbox functions, and the
GitHub release controller calls the release functions.

The migration revokes `EXECUTE` from `PUBLIC`, `anon`, `authenticated`, and
`service_role` for these exact signatures:

| Function | Intended capability role |
| --- | --- |
| `worker_release_active_attempt_count()` | `github_release_gate` |
| `worker_release_try_acquire_attempt(uuid, uuid, text, uuid, integer)` | `image_to_lego_worker` |
| `worker_release_begin(uuid, uuid, integer)` | `github_release_coordinator` |
| `worker_release_transition(uuid, uuid, bigint, text, text)` | `github_release_coordinator` |
| `worker_release_recover(uuid, integer, text)` | `github_release_coordinator` |
| `worker_release_heartbeat(uuid, uuid, bigint, integer)` | `github_release_coordinator` |
| `worker_release_is_draining()` | `image_to_lego_worker` |
| `worker_release_admit_submission()` | `image_to_lego_submission` |
| `submission_outbox_create(uuid, uuid, integer)` | `image_to_lego_submission` |
| `submission_outbox_claim(uuid, integer)` | `image_to_lego_outbox_dispatcher` |
| `submission_outbox_begin_send(uuid, uuid, bigint)` | `image_to_lego_outbox_dispatcher` |
| `submission_outbox_record_delivered(uuid, uuid, bigint)` | `image_to_lego_outbox_dispatcher` |
| `submission_outbox_record_known_failure(uuid, uuid, bigint, text, text, timestamptz)` | `image_to_lego_outbox_dispatcher` |
| `submission_outbox_record_uncertain(uuid, uuid, bigint, text)` | `image_to_lego_outbox_dispatcher` |
| `submission_outbox_release_unstarted_claim(uuid, uuid, bigint)` | `image_to_lego_outbox_dispatcher` |
| `submission_outbox_mark_expired_sends_attention()` | `image_to_lego_outbox_dispatcher` |
| `submission_outbox_publication_counts()` | `image_to_lego_outbox_dispatcher`, `github_release_coordinator` |

It also removes `anon`, `authenticated`, and `service_role` membership in each
capability role and fails the migration if any of those roles still inherits
one. The committed migrations do not grant these functions to `service_role`; this migration nevertheless
explicitly revokes `service_role` to remove any production grant made outside
the committed history. No checked-in caller uses `service_role`, so retaining
such a grant is not justified. It must not substitute for the scoped API,
worker, dispatcher, or release logins.

The release-state and outbox tables have RLS enabled and no browser policies in
their migrations. RLS is not sufficient here because a `SECURITY DEFINER`
function can access those tables as its owner; removing browser `EXECUTE` is the
necessary boundary.

## Future functions

PostgreSQL's function default `PUBLIC EXECUTE` is global for an owner. A
schema-specific default-privilege revoke cannot remove it, while a global revoke
for `postgres` would affect future functions in every schema, including
Supabase-managed schemas. This migration deliberately changes neither default.

Each future application `SECURITY DEFINER` function must instead be followed in
the same migration by an exact `REVOKE EXECUTE ... FROM PUBLIC, anon,
authenticated, service_role` and explicit grants only to its dedicated
capability role. A browser RPC requires a separate, reviewed explicit grant.

## Independent production rollout

This remediation precedes `20261123000000_credits.sql` lexically and has no
credit-table, credit-function, or application-code dependency. Supabase tracks
applied versions in `supabase_migrations.schema_migrations`, but its normal
`db push` applies every pending file in the working directory. Do not run it
from this repository while credits is present.

Prepare a reviewed, throwaway release directory containing the same
`supabase/config.toml` and all migration files through
`20261122000000_security_definer_function_permissions.sql`, but not
`20261123000000_credits.sql`. Record the commit SHA and file checksums in the
change record. From that directory only:

1. Run `supabase migration list --linked` and confirm every earlier version is
   already remote, `20261122000000` is pending, and `20261123000000` is absent
   from the release directory.
2. Run `supabase db push --linked --dry-run`; its plan must contain exactly
   `20261122000000_security_definer_function_permissions.sql`.
3. Have a second reviewer compare the dry-run output and checksums, then run
   `supabase db push --linked` from the same release directory. This applies
   the SQL and records the version through the standard Supabase migration
   system; do not use `migration repair` to mark unapplied SQL as applied.
4. Run `supabase migration list --linked` again. It must show
   `20261122000000` remote and leave `20261123000000` unapplied.

Before release, a database administrator must inventory effective function
privileges and role memberships for `anon`, `authenticated`, `service_role`, each runtime login,
and the five capability roles. Confirm the API login can use
`image_to_lego_submission`, both workers can use `image_to_lego_worker`, the
dispatcher login can explicitly set `image_to_lego_outbox_dispatcher`, and the
release login can use only its GitHub capability role. Stop if a runtime depended
on `PUBLIC` or `service_role` access; grant its least-privilege capability role
in the same reviewed provisioning change before the revoke.

After the single migration commits and its history record is verified, execute a
read-only permission check for every signature in the table using
`has_function_privilege('anon', <signature>, 'EXECUTE')`,
`has_function_privilege('authenticated', <signature>, 'EXECUTE')`, and
`has_function_privilege('service_role', <signature>, 'EXECUTE')`; all must be
false. Check `pg_has_role` for each untrusted role and each capability role; all
membership checks must be false. Then run one non-paid API submission, one
worker lease/drain check, and (if enabled) dispatcher access validation with
their real private logins. Do not deploy the credit migration, modify Azure or
Supabase configuration, or roll back this forward-only migration as part of this
remediation.
