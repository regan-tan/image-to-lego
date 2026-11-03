# ADR-009: Fenced release controller remains inactive

## Status

Accepted as an offline-tested foundation. Azure mutation is not activated.

## Decision

The controller owns a PostgreSQL release ID, controller ID, and fencing token. It enters `draining`, waits for independently supplied quiescence evidence, then transitions through `quiescent`, `deploying`, and `verifying`. Only a successful readiness check may transition to `open`. Any exception, timeout, cancellation, or lost heartbeat attempts to record `blocked`; it never reopens the gate.

The controller does not hold a database transaction while polling or deploying. PostgreSQL functions own locking and fencing. Deployment, queue/provider inspection, and readiness are injected interfaces so normal tests use deterministic fakes and cannot contact Azure or fal.ai.

Workers query the durable gate after every empty receive. A non-open gate makes an idle worker exit within `WORKER_RELEASE_DRAIN_POLL_SECONDS`; active attempts finish before the loop can make that check. A database failure is a worker failure, not evidence of draining.

## Activation blockers

`JOB_SUBMISSIONS_ENABLED` is not durable submission coordination: an in-flight, multi-instance API request can insert a job and publish after the setting is changed. The current insert-then-publish path is also not atomic. Therefore the GitHub workflow hard-codes `RELEASE_CONTROLLER_AZURE_MUTATIONS_ENABLED=false`; setting `AZURE_COMPUTE_DEPLOYMENTS_ENABLED=true` alone cannot mutate Azure.

Before activation, implement and test a durable submission gate covering authorization, durable insertion, and publication recovery; a reviewed Azure adapter that inventories active/locked/scheduled/dead-letter messages, provider IDs, worker attestation and image digests; and an ACI `Never` bootstrap/readiness protocol. Unknown provider submission, partial deployment, unavailable database, incompatible image, or unclear worker state must remain `blocked` for an operator using a fresh fenced controller.

The database-only publication outbox and dispatcher logic are implemented and tested offline. The
dispatcher reserves an intent, then calls fenced `begin_send` immediately before Service Bus
publication; it cannot start a send once draining has committed. It records confirmed delivery
separately from a known pre-acceptance failure, and treats a timeout or expired post-send claim as
`attention_required`. Release quiescence counts only begun/uncertain publications, not pending
intents, so safely unsent work can resume after reopening the gate.

There is deliberately no scheduled dispatcher runtime, live dispatcher credential, or reconciliation
operation yet. **Do not deploy the current API changes without a functioning dispatcher:** accepted
jobs create durable pending intents and will remain queued until one is configured. A later rollout
must provide reliable dispatcher scheduling, private database-role membership, verified graceful
publisher shutdown, and controller reconciliation that resolves every begun or attention-required
intent before a release may proceed.

## Implementation status

Implemented and tested offline:

- release coordination and fail-closed controller logic;
- atomic submission admission;
- transactional outbox persistence; and
- fenced dispatcher logic.

Not yet operational:

- reliable scheduled dispatcher;
- live dispatcher database credentials and `image_to_lego_outbox_dispatcher` role membership;
- real Azure worker readiness evidence;
- production migration rollout;
- actual Azure adapters for the release controller; and
- controlled deployment activation.

## Roles and rollout

Workers receive only `image_to_lego_worker`, which can claim work and query drain status. A future controller must use only `github_release_coordinator`; browser roles receive neither role. Apply migrations manually, deploy gate-aware worker images while submissions are paused, verify their attestation and compatibility, then conduct an explicitly approved simulation. No migration, rollback, worker recreation, or release-gate reopening is automated by this foundation.
