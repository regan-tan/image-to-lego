# Production database credential separation

This is a manual production runbook. It does not execute SQL or change Azure.
Run SQL as a reviewed database administrator, never an application login. Values
in `<angle brackets>` are runbook inputs, never values to commit or paste into
command history.

## Verified runtime-permission matrix

API and worker transactions call `set_config('app.current_user_id', ..., true)`.
Existing owner-scoped `FOR ALL` RLS policies on projects, jobs, artifacts, and
both run tables apply to workers too; no permissive worker policy is required.
The fenced worker-release function checks the message owner before costly work.

| Runtime | Login / secret | Direct table privileges | Capability roles | Credit role after migration |
| --- | --- | --- | --- | --- |
| API | existing `image_to_lego_api` / `api-database-url` | Preserve production grants: projects `SELECT, INSERT, UPDATE, DELETE`; artifacts, jobs, reconstruction_runs, conversion_runs `SELECT, INSERT, UPDATE` | `image_to_lego_submission` | `image_to_lego_credits_api` |
| Generation | new `image_to_lego_generation_worker` / `generation-worker-database-url` | `SELECT` projects, jobs, artifacts, reconstruction_runs; `UPDATE` jobs; `INSERT` artifacts | `image_to_lego_worker` | `image_to_lego_credits_worker` |
| Conversion | new `image_to_lego_conversion_worker` / `conversion-worker-database-url` | `SELECT` projects, jobs, artifacts, conversion_runs; `UPDATE` jobs; `INSERT` artifacts | `image_to_lego_worker` | `image_to_lego_credits_worker` |
| Dispatcher | existing `image_to_lego_dispatcher_login` / `dispatcher-database-url` | none | explicitly `SET LOCAL ROLE image_to_lego_outbox_dispatcher` | none |

All four require `USAGE` on `public`. Workers need no sequence grant because
worker-created artifacts use UUIDs supplied by code. No runtime login needs
object ownership, `BYPASSRLS`, `CREATEROLE`, `CREATEDB`, `REPLICATION`, or
`image_to_lego_credits_admin`.

`image_to_lego_worker` grants execution of `worker_release_try_acquire_attempt`
and `worker_release_is_draining`. The credit worker role grants only
`credit_refund_failed_job`, `credit_reconcile_expired_jobs`, and
`credit_fail_dead_lettered_job`. The dispatcher remains function-only, with
its current `NOINHERIT`/explicit-`SET ROLE` contract. Do not remove API worker
privileges until production evidence proves the API no longer relies on them.

Tracing the worker-only paths confirms the table grants above are complete:
each worker selects its job, project, source/output artifacts, and its own run
row; updates only `jobs`; and inserts only its resulting artifact. Both invoke
the two worker-release functions; while idle or processing a dead letter they
invoke the three credit-worker functions after Phase 2. They never directly
read or write credit, outbox, or worker-release tables. The `FOR ALL` RLS
policies authorize those direct operations only after the repository sets the
transaction-local verified owner ID. The release and credit functions are
`SECURITY DEFINER`; no policy adjustment or direct table grant is needed.

## Prerequisite inventory — mandatory no-go gate

Role names do not prove runtime identity. Connect through every currently
configured production credential (or the protected diagnostic connection) and
record these non-secret results:

```sql
select session_user, current_user, rolinherit, rolbypassrls, rolsuper
from pg_roles where rolname = session_user;

select member.rolname as login, role.rolname as member_of,
       membership.inherit_option, membership.set_option
from pg_auth_members membership
join pg_roles role on role.oid = membership.roleid
join pg_roles member on member.oid = membership.member
where member.rolname in (
  'image_to_lego_api', 'image_to_lego_generation_worker',
  'image_to_lego_conversion_worker', 'image_to_lego_dispatcher_login'
)
order by login, member_of;

select grantee, table_name, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and grantee in ('image_to_lego_api', 'image_to_lego_generation_worker',
                  'image_to_lego_conversion_worker', 'image_to_lego_dispatcher_login')
order by grantee, table_name, privilege_type;
```

Stop if an application login is an object owner, `rolbypassrls`/`rolsuper` is
true, the current API login cannot be proven, dispatcher separation is absent,
or production grants differ materially from the matrix. The repository cannot
establish those production facts locally.

## Phase 1: create and grant worker logins

Run once; `CREATE ROLE` deliberately fails if a role exists, requiring review
rather than a silent mutation. Generate distinct high-entropy passwords in the
approved password manager. The following is ordinary SQL and may be run in the
Supabase SQL Editor or `psql`; it does not contain a password.

```sql
create role image_to_lego_generation_worker
  login inherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls
  connection limit 3;

create role image_to_lego_conversion_worker
  login inherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls
  connection limit 3;

grant usage on schema public
  to image_to_lego_generation_worker, image_to_lego_conversion_worker;

grant select on public.projects, public.jobs, public.artifacts, public.reconstruction_runs
  to image_to_lego_generation_worker;
grant update on public.jobs to image_to_lego_generation_worker;
grant insert on public.artifacts to image_to_lego_generation_worker;

grant select on public.projects, public.jobs, public.artifacts, public.conversion_runs
  to image_to_lego_conversion_worker;
grant update on public.jobs to image_to_lego_conversion_worker;
grant insert on public.artifacts to image_to_lego_conversion_worker;

grant image_to_lego_worker to image_to_lego_generation_worker
  with inherit true, set false, admin false;
grant image_to_lego_worker to image_to_lego_conversion_worker
  with inherit true, set false, admin false;
```

Run the following two commands only in an interactive **`psql` client** after
connecting as the database administrator. `\password` is a psql meta-command,
not SQL: it must not be pasted into the Supabase SQL Editor. It prompts without
printing the password, avoiding source, SQL logs, command history, Terraform
state, and terminal output.

```text
\password image_to_lego_generation_worker
\password image_to_lego_conversion_worker
```

`INHERIT TRUE` is required because worker code does not issue `SET ROLE`.
`SET FALSE` prevents arbitrary capability switching. Do not grant workers direct
access to outbox/release/credit tables or grant the dispatcher table/credit access.

### Worker connection limit and pooler verification

Each ACI worker receives one message at a time (`max_message_count=1`) and has
one process. A lease-renewal task may use a second session while the job path has
a transaction open; idle/dead-letter work is serial. Thus the observed design
needs at most two simultaneous connections per worker login, and `CONNECTION
LIMIT 3` leaves one connection for a short-lived readiness/diagnostic check.

`create_async_engine(..., pool_pre_ping=True)` does not set `pool_size` or
`max_overflow`, so SQLAlchemy's AsyncAdaptedQueuePool defaults remain 5 and 10.
That is a capacity ceiling, not observed worker concurrency, but it must not be
treated as a reason to run multiple worker processes under the same login. Before
cutover, verify that exactly one generation ACI and one conversion ACI are
running and query `pg_stat_activity` during a lease renewal. Stop if either login
reaches three connections or if the Supabase pooler client limit cannot admit the
three permitted connections.

Use a direct connection (if the environment has approved IPv6/IPv4 reachability)
or the Supabase **shared session pooler** copied from the Connect dialog. The
current SQLAlchemy/asyncpg configuration is not approved for the shared
transaction pooler on port 6543: it has not disabled asyncpg's prepared-statement
cache or changed to `NullPool`. A move to that mode requires a separate reviewed
code change and test.

## Phase 2: only after the credit migration succeeds

Apply `20261123000000_credits.sql` exactly once through the approved migration
workflow. Do not rerun the historical security-permissions migration. Once
remote history records the credit migration, run:

```sql
grant image_to_lego_credits_api to image_to_lego_api
  with inherit true, set false, admin false;
grant image_to_lego_credits_worker to image_to_lego_generation_worker
  with inherit true, set false, admin false;
grant image_to_lego_credits_worker to image_to_lego_conversion_worker
  with inherit true, set false, admin false;
```

Never grant `image_to_lego_credits_admin` to API, workers, dispatcher, browser
roles, or deployment diagnostics.

## Validation

Using each new worker login, all booleans below must be true; `rolsuper` and
`rolbypassrls` must be false; the last query must return no rows.

```sql
select session_user, current_user, rolsuper, rolbypassrls
from pg_roles where rolname = session_user;

select has_table_privilege(session_user, 'public.projects', 'SELECT') as projects_select,
       has_table_privilege(session_user, 'public.jobs', 'SELECT') as jobs_select,
       has_table_privilege(session_user, 'public.jobs', 'UPDATE') as jobs_update,
       has_table_privilege(session_user, 'public.artifacts', 'SELECT') as artifacts_select,
       has_table_privilege(session_user, 'public.artifacts', 'INSERT') as artifacts_insert,
       has_function_privilege(session_user,
         'public.worker_release_try_acquire_attempt(uuid,uuid,text,uuid,integer)', 'EXECUTE') as can_acquire,
       has_function_privilege(session_user,
         'public.worker_release_is_draining()', 'EXECUTE') as can_check_drain;

-- Run as generation login: true; run as conversion login: false.
select has_table_privilege(session_user, 'public.reconstruction_runs', 'SELECT')
  as reconstruction_runs_select;
-- Run as conversion login: true; run as generation login: false.
select has_table_privilege(session_user, 'public.conversion_runs', 'SELECT')
  as conversion_runs_select;

select table_name, privilege_type
from information_schema.role_table_grants
where grantee = session_user
  and table_name in ('submission_outbox', 'worker_release_state', 'worker_release_audit',
                     'credit_accounts', 'credit_policy', 'credit_transactions');
```

After Phase 2, test that API can execute only `credit_admit_job` and
`credit_ensure_account`; each worker only the three listed credit worker
functions; browser roles cannot select credit tables or execute private functions.
Test existing RLS without modifying it:

```sql
begin;
select set_config('app.current_user_id', '<owned-test-user-uuid>', true);
select count(*) from public.jobs;
rollback;
```

The count must contain only that owner's rows. Repeat for a different owner and
verify no cross-owner data is visible.

### Supabase custom-role connection URLs and secret-safe test

Use the exact host and project reference copied from the Supabase **Connect**
dialog; do not infer a pooler host from the region. The application expects an
async SQLAlchemy URL, so the Key Vault value must begin with
`postgresql+asyncpg://`.

For a direct connection, the custom login name is the PostgreSQL role name:

```text
postgresql+asyncpg://image_to_lego_generation_worker:<percent-encoded-password>@db.<project-ref>.supabase.co:5432/postgres?ssl=require
```

For the dedicated pooler, if the production project has that feature and its
network path is approved, retain that login name but use the Connect-dialog
endpoint on port `6543`:

```text
postgresql+asyncpg://image_to_lego_generation_worker:<percent-encoded-password>@db.<project-ref>.supabase.co:6543/postgres?ssl=require
```

For the shared **session** pooler on port 5432, the custom login name must add
the project reference, while the host must be copied exactly from the dialog:

```text
postgresql+asyncpg://image_to_lego_generation_worker.<project-ref>:<percent-encoded-password>@<pooler-host>:5432/postgres?ssl=require
```

Construct an equivalent URL for conversion and API roles. Percent-encode the
password exactly once as a URI user-info component before inserting it. Reserved
characters such as `@`, `:`, `/`, `?`, `#`, `%`, `&`, space, and `=` must be
encoded; for example `p@ss=word` becomes `p%40ss%3Dword`. Do not encode the
whole URL, encode it twice, or use an unencoded password copied from a password
manager. Record the final URL only in its protected Key Vault secret or a
short-lived protected file; never paste it into SQL, Terraform, CI variables,
or the shell command line.

For a connection test, create a temporary restricted-permission `pgpass` file
outside the repository with exactly
`<host>:<port>:postgres:<user>:<raw-password>` on one line, set `PGPASSFILE` to
that file, and run a query that prints no credential:

```powershell
# PowerShell: create this file outside the repository and remove it immediately after the test.
$env:PGPASSFILE = '<protected-pgpass-file>'
psql 'host=<copied-host> port=<copied-port> dbname=postgres user=<custom-role-or-custom-role.project-ref> sslmode=require' `
  -X --set=ON_ERROR_STOP=1 --command 'select session_user, current_user;'
Remove-Item -LiteralPath $env:PGPASSFILE
Remove-Item Env:PGPASSFILE
```

The result must identify the intended custom role. Use the raw password only in
the protected pgpass file; the application URL stores its percent-encoded form.
Do not use this test against a transaction-pooler URL until the separately
required asyncpg configuration change is reviewed.

## Key Vault cutover

Terraform agrees on these secret names and secret-scoped assignments:

| Managed identity | Allowed secret(s) |
| --- | --- |
| `id-image-to-lego-api-dev` | `api-database-url` |
| `id-image-to-lego-generation-dev` | `generation-worker-database-url`, `fal-key` |
| `id-image-to-lego-conversion-dev` | `conversion-worker-database-url` |
| `id-image-to-lego-outbox-dispatcher-dev` (if enabled) | `dispatcher-database-url` |

The first shared-Terraform cutover plan must **add** the four API/worker
secret-scoped assignments while retaining the three existing vault-scoped
assignments. The legacy assignments are protected with `prevent_destroy` and
are intentionally retained as rollback access. Stop if this phase plans a
Key Vault role-assignment delete, replacement, or update. Removing the three
broad assignments is a later, separately reviewed Terraform change after the
API and both workers have restarted successfully with their dedicated secrets.

The commands below are for **PowerShell 7 (`pwsh`)**, matching the repository's
operational scripts. The backtick is PowerShell's line continuation; do not copy
these commands into Bash. Use protected files containing one URL and do not
pass a URL or password on the command line. Substitute only non-secret
placeholders.

```powershell
az keyvault secret set --subscription <subscription-id> --vault-name <vault-name> `
  --name api-database-url --file <protected-api-url-file> --output none
az keyvault secret set --subscription <subscription-id> --vault-name <vault-name> `
  --name generation-worker-database-url --file <protected-generation-url-file> --output none
az keyvault secret set --subscription <subscription-id> --vault-name <vault-name> `
  --name conversion-worker-database-url --file <protected-conversion-url-file> --output none
```

Keep `dispatcher-database-url` unchanged. Before removing a broad assignment,
inspect effective Key Vault access:

```powershell
az role assignment list --all --include-inherited `
  --scope /subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.KeyVault/vaults/<vault-name> `
  --query "[?roleDefinitionName=='Key Vault Secrets User'].{principal:principalName,scope:scope}" -o table
```

Set App Service `DATABASE_URL` to the API reference and verify `Resolved`:

```powershell
$apiDatabaseReference = '@Microsoft.KeyVault(SecretUri=https://<vault-name>.vault.azure.net/secrets/api-database-url/)'
az webapp config appsettings set -g <resource-group> -n app-image-to-lego-api-dev-2b70703f `
  --settings "DATABASE_URL=$apiDatabaseReference" `
  --output none
az rest --method get --url 'https://management.azure.com/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.Web/sites/app-image-to-lego-api-dev-2b70703f/config/configreferences/appsettings/DATABASE_URL?api-version=2022-03-01' `
  --query properties.status -o tsv
```

The versionless trailing slash in the Key Vault URI is intentional. It is an
App Service Key Vault reference, not a shell-escaped URL; PowerShell receives
the reference as one `DATABASE_URL=...` setting argument. The expected status
is `Resolved` before restarting the API.

Recreate workers from the reviewed immutable image, with their assigned
identities and respectively `DATABASE_URL_SECRET_NAME=generation-worker-database-url`
and `DATABASE_URL_SECRET_NAME=conversion-worker-database-url`. The CI release
workflow holds the exact ACI create contract. Verify names/settings and startup
only—never print secret values. Verify dispatcher still uses only its secret.

## Coordinated release and recovery

1. Record images, Key Vault-reference status, worker state, active/scheduled/dead-letter
   queue counts, active attempts, non-terminal jobs, and outstanding outbox records.
2. Set `JOB_SUBMISSIONS_ENABLED=false`; use the durable release gate to drain/reconcile
   attempts and outbox sends. Old APIs must not admit uncharged jobs during migration.
3. Create worker logins/secrets, validate grants/RLS, and add secret-scoped Key Vault access while
   preserving broad vault access for rollback. Deploy and restart the gate-aware API image with
   `JOB_SUBMISSIONS_ENABLED=false` and its dedicated API secret. Do not start the credit-aware
   worker images yet: they reconcile credits while idle and require the Phase 2 database roles.
4. Apply the credit migration once, verify remote history, then grant Phase 2 credit roles.
5. Deploy the matching generation and conversion worker images with their dedicated secrets, and
   re-deploy the matching API image if needed. While paused, smoke-test health, Key Vault-reference resolution,
   worker startup, authentication, owner-scoped credit read/badge, and that both submission
   endpoints return the expected paused response without creating a job or outbox record.
6. The current release gate is global: it has no user, project, or test-job allowlist. Therefore
   a charged end-to-end generation/conversion smoke test cannot occur while general submissions
   remain paused. Do not bypass it with direct table inserts, manual queue messages, or an
   administrator credit function. Either accept the paused non-submission checks and reopen only
   after them, or obtain separate approval for a short, monitored global reopening window. During
   that window, perform one disposable authorized test account flow, then close the gate again and
   reconcile its job, credit charge/refund, lease, outbox, and queues before final reopening.
7. Re-enable submissions for users only when all checks pass. Remove broad Key Vault access only
   after each runtime has restarted successfully using its own secret.
8. Remove obsolete API worker memberships only in a later reviewed release after live evidence.

If any runtime cannot start or connect, leave submissions paused and restore only that
runtime's own prior image/reference—never another runtime's credential. If migration fails,
stop, retain the exact error/history, and make a reviewed forward repair. Do not rerun
`20261122000000_security_definer_function_permissions.sql` or alter migration history.

## GO / NO-GO

**NO-GO** until prerequisite inventory proves each actual login, RLS attributes, existing
grants, and dispatcher path. **GO** only after those checks, credit migration history, dedicated
secret resolution, permission tests, and paused-release smoke tests all pass.
