# ADR-008: Durable worker release coordination

## Status

Accepted as an inactive, locally verified foundation. Automatic Azure deployment remains disabled.

## Context

ACI worker replacement can interrupt a message after it has been received but before a
database lease is claimed. Queue depth and ACI status cannot close that race, and an
ambiguous fal submission must never be submitted again merely because a worker restarted.

## Decision

PostgreSQL is the release coordinator. The singleton `worker_release_state` row is locked
before a job row in every lease acquisition and release transition. Its states are `open`,
`draining`, `quiescent`, `deploying`, `verifying`, and `blocked`. A controller receives a
monotonically increasing fencing token when it changes `open` to `draining`; every later
transition and heartbeat must present the same release ID, controller ID, and token. A
controller whose heartbeat expires is fenced immediately: it cannot begin again, transition,
or renew. Only worker_release_recover can issue a newer token, and it moves the gate to
blocked; expiry never reopens admission.

Workers call `worker_release_try_acquire_attempt`. In one short transaction it locks the
release row, rejects a non-open gate as `release_blocked`, or claims the eligible job lease.
The result separately identifies an acquired lease, another live lease, a terminal/duplicate
delivery, and a release block. Database failures propagate; they never become an admission.

On `release_blocked`, a worker exits without completing, abandoning, or dead-lettering the
received message. Its receiver closes and the broker redelivers later. An attempt already
acquired before draining continues normally; workers do not cancel conversion threads or fal
requests. `quiescent` additionally requires every durable attempt marker to be cleared, not
merely that leases have expired, and no reconstruction that is `running` without a persisted
provider ID. A persisted provider ID is safe to resume by
polling, while an unconfirmed submission blocks release progress.

Queue messages now carry version `1`; workers also accept the legacy unversioned shape.
Unknown future versions are rejected safely instead of being interpreted with guessed fields.
Persisted jobs and conversion artifacts remain backward compatible in this foundation.

An expired controller does not reopen the gate. A separately authenticated coordinator may
fence it with `worker_release_recover`, which moves the state to `blocked`, records an audit
row, and increments the token. Only a fenced controller can prove quiescence and later move
from `verifying` back to `open`.

```mermaid
sequenceDiagram
    participant C as Release controller
    participant DB as PostgreSQL gate
    participant W as Worker
    C->>DB: lock gate; OPEN -> DRAINING (fencing token)
    W->>DB: lock same gate; try lease
    DB-->>W: release_blocked
    W-->>W: exit; leave message unsettled
    Note over W: Earlier acquired attempt may finish
    C->>DB: prove no live leases or ambiguous submissions
    DB-->>C: QUIESCENT
    C->>DB: DEPLOYING -> VERIFYING -> OPEN (same token)
```

## Consequences

The release controller and GitHub workflow are deliberately not activated by this ADR. Before
activation, every active worker must run the gate-aware image, the migration must be reviewed
and applied manually, a conversion-only Azure smoke test must succeed, and a controller must
verify worker exit and compatibility evidence. No new Azure resource is created and no test
contacts Azure or fal.ai. This suits Azure for Students by keeping ACI `Never`, avoiding
always-on coordination compute, and retaining intentional compute-downtime support.

If deployment partially succeeds or readiness cannot be proven, the controller must transition
to `blocked`; it must not reopen admission. Recovery is an authenticated, audited operator
procedure using a new fencing token.
