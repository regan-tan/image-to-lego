# Credit system deployment and recovery

The credit migration is a prerequisite for the API and both workers. It creates a protected,
fixed policy of 10 starter credits, reconstruction cost 2, conversion cost 1, two active jobs per
type, and rolling 24-hour limits of 10 reconstructions and 30 conversions. Starter allocation is
lazy: the first authenticated credit read or job admission creates the account and one starter-ledger
entry atomically.

## Privileged manual database work

Run the committed Supabase migration through the team's reviewed migration workflow. Do **not** run
the following against production from an application container or browser. A database administrator
must grant the private logins used by the deployed processes membership in these no-login roles:

```sql
GRANT image_to_lego_credits_api TO <api_database_login>;
GRANT image_to_lego_credits_worker TO <generation_worker_database_login>;
GRANT image_to_lego_credits_worker TO <conversion_worker_database_login>;
```

Do not grant `image_to_lego_credits_admin` to API, worker, `anon`, or `authenticated` roles. It is
reserved for a reviewed, manual credit top-up procedure. Verify that `anon` and `authenticated` do
not have table or function grants.

The API, generation worker, conversion worker, and dispatcher must now use separate database
logins and Key Vault secrets. The migration-recovery gate, credential provisioning, least-privilege
Key Vault access, staged cutover, and rollback procedure are in
[database credential separation](database-credential-separation.md). In particular, do not apply
this migration until `supabase migration list --linked` proves the local
`20261105130000_dispatcher_login` file matches the version recorded in production.

Before enabling submissions, connect using each private login and verify that the API login can run
only `credit_admit_job(uuid, uuid)` and `credit_ensure_account(uuid)`, while worker logins can run
only refund/reconciliation functions. Verify that an authenticated browser role cannot select the
credit tables or execute the functions.

## Safe release order

1. Apply the migration.
2. Grant the memberships above and perform permission checks.
3. Deploy the API and both worker images together.
4. Keep job submissions paused until a test account can read its balance, submit one job, and the
   worker can complete a terminal transition.
5. Re-enable submissions and monitor failed jobs, worker lease expiry reconciliation, and Service
   Bus dead-letter counts.

The existing workers reconcile jobs whose worker lease has expired while idle. They also inspect one
dead-letter message while idle, mark its eligible durable job failed, and issue an idempotent refund.
Do not manually refund a job before confirming it is terminal; late worker attempts are fenced by the
expired lease and cannot publish a success after reconciliation.

Credit ledger rows retain immutable job ID, project ID, job type, amount, and balance-after metadata
without a foreign key to the job table. Completed projects can therefore be deleted without deleting
rolling-quota or audit history.
