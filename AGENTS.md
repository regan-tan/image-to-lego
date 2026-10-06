Image to LEGO: Agent Coding Standards


Image to LEGO is a university capstone that turns a user image into a generated 3D model and then into an inspectable, downloadable LEGO model. The intended system combines Supabase Auth/PostgreSQL, FastAPI, Azure Blob Storage, Azure Service Bus, fal.ai/TRELLIS, asynchronous workers, a Python mesh-to-LEGO converter, and a React/TypeScript frontend.
This file applies to every coding agent working in the repository, including Codex, Claude Code, Cursor, Copilot, and similar tools.
The code will be graded by a professor. Optimize for correctness, simplicity, readability, maintainability, testability, security, and explainability - not cleverness or unnecessary architectural sophistication.
AGENTS.md is human-owned. Do not modify it unless the human explicitly asks you to.


CRITICAL INSTRUCTIONS
These override convenience, speed, and reasonable-seeming shortcuts.
- Keep it simple. Use the simplest design that correctly satisfies the current requirement.
- Prefer conventional, explicit code over clever, compressed, highly abstract, or framework-heavy code.
- If two approaches are correct, choose the one that is easier to explain, test, debug, review, and maintain.
- The project is already technically complex because it combines auth, cloud storage, queues, paid AI generation, 3D geometry, LEGO conversion, and a web client. Do not manufacture extra software complexity to make the project look advanced.
- Follow KISS and YAGNI. Apply DRY and SOLID proportionally; they do not justify speculative abstractions.
- Every new dependency, helper, class, interface, layer, service, table, queue, cache, retry mechanism, or top-level file must have a concrete current need.
- Reuse the standard library, browser/platform APIs, and existing project dependencies before proposing a new package.
- Keep important control flow, state transitions, units, limits, and side effects understandable to a reviewer who did not write the code.
- Keep probabilistic image-to-3D work separate from deterministic validation, persistence, and LEGO conversion.
- Long-running, CPU-intensive, or paid work must not execute inside FastAPI request handlers or BackgroundTasks.
- Preserve idempotency around paid generation, queue delivery, conversion work, and durable state changes. Duplicate requests/messages must not create duplicate paid work or corrupt state.
- Never bypass authentication, ownership checks, RLS/security boundaries, quotas, validation, or resource limits to make development easier.
- Never commit or expose secrets, API keys, connection strings, JWTs, SAS tokens/URLs, credentials, private uploads, generated private artifacts, or .env contents.
- Do not claim a planned integration is implemented. Verify executable code and tests.
- If requirements, ADRs, architecture docs, code, tests, or deployment docs materially conflict, surface the conflict instead of silently choosing one.


GRADING-AWARE ENGINEERING PRIORITIES
The grading rubric evaluates database design, scalability, project complexity, code cleanliness, backend API design, frontend code, cloud deployment, innovation, documentation, testing, and teamwork. Treat these as quality dimensions, not reasons to add unnecessary machinery.
- Code cleanliness: readable names, coherent responsibilities, conventional structure, useful comments, no dead code, and adherence to normal language/framework practices.
- Complexity / innovation: demonstrate sophistication through the image -> 3D -> LEGO problem and its real integration/geometry challenges, not gratuitous patterns or microservices.
- Database: clear relational design, constraints, indexes, efficient queries, and secure ownership boundaries.
- API: resource-oriented REST, explicit validation, authorization, idempotency, safe errors, and conventional HTTP semantics.
- Frontend: clear user journeys, responsive/accessibility-conscious UI, and reliable backend integration.
- Scalability: bounded work, queue-backed expensive jobs, independently scalable workers, and measured optimization.
- Cloud: containerized workloads, managed Azure services, secure configuration, cost awareness, and reviewed CI/CD.
- Testing: meaningful automated tests for critical behavior, failures, contracts, and regressions.
- Documentation: another developer or professor should be able to set up, run, test, and explain the system without reverse-engineering it.


DO NOT RULES
- Do not overengineer.
- Do not add a dependency when built-ins, platform APIs, or an existing dependency provide a clear solution.
- Do not add a dependency without explicit human approval. Name it, explain why it is needed, why existing options are insufficient, and its maintenance/security cost.
- Do not upgrade unrelated dependencies, runtimes, frameworks, or lockfiles during a focused feature.
- Do not use pip install for project dependencies; backend dependencies use uv.
- Do not use pnpm or yarn; the frontend uses npm and the committed package-lock.json.
- Do not add another ORM, HTTP framework, state manager, form library, validation library, UI system, queue system, or logging framework without an approved need.
- Do not create generic repository/service base classes, factories, plugin registries, dependency-injection frameworks, or wrappers "for future flexibility."
- Do not create utils, helpers, manager, or common dumping grounds when a domain-specific name exists.
- Do not create one-line forwarding helpers that add no useful naming, validation, reuse, test seam, or domain concept.
- Do not fragment straightforward logic into many tiny functions/files merely to reduce line count.
- Do not let a route, service, component, class, or module accumulate unrelated responsibilities. Split at real responsibility boundaries.
- Do not prematurely DRY similar syntax into a generic abstraction. Small duplication can be clearer than the wrong abstraction; duplicated business rules should be centralized.
- Do not use unnecessary inheritance, metaprogramming, reflection, hidden global state, nested ternaries, or dense one-liners for non-trivial logic.
- Do not hide database/network/storage/queue/paid-provider side effects inside innocently named helpers.
- Do not swallow exceptions, use empty catches, or convert unknown failures into successful/default responses.
- Do not use TypeScript any merely to silence a type problem.
- Do not use Python wildcard imports or mutable default arguments.
- Do not hard-code unexplained quotas, timeouts, retry counts, polling intervals, worker counts, file-size limits, geometry tolerances, or model names. Use named configuration/constants.
- Do not leave dead code, commented-out implementations, unused imports, stale flags, speculative TODO scaffolding, or accidental generated files.
- Do not add caching, extra concurrency, WebSockets/SSE, a transactional outbox, another queue, or another deployable service without a current reviewed need.
- Do not sleep inside workers while waiting for an external AI job. Schedule a later status check and release the worker.
- Do not automatically retry a paid fal submission unless duplicate billing/work is prevented by a verified idempotency contract.
- Do not call real fal.ai, production Supabase, or production Azure services from the normal automated test suite.
- Do not use Supabase Storage for application artifacts; Azure Blob Storage is the accepted artifact store.
- Do not proxy large upload/download bytes through FastAPI when the approved direct-to-Blob pattern applies.
- Do not manually edit a shared/production database schema; use committed migrations.
- Do not expose service-role/database/Azure credentials to the browser.
- Do not use a privileged/BYPASSRLS database identity for ordinary user-scoped reads/writes merely for convenience.
- Do not use HTTP 304 Not Modified as a generic "no change" response. Use it only for a real conditional request with validators such as ETag/If-None-Match.
- Do not commit directly to main, force-push, rewrite shared history, merge, publish, or deploy unless the human explicitly asks for that action.
Sources of truth - read before touching code
Source	Owns / answers
AGENTS.md	Agent behavior, code-quality/security rules, current target workflow guardrails
README.md	Repository overview, implementation status, setup, common commands
docs/architecture/README.md	Architecture boundaries and dependency direction
docs/decisions/ADR-*.md	Accepted architecture decisions and rationale
docs/deployment/azure-cicd-plan.md	Intended Azure deployment/release model
docs/testing/README.md	Test isolation and strategy
backend/pyproject.toml + backend/uv.lock	Backend runtime, dependencies, tooling, locked versions
frontend/package.json + frontend/package-lock.json	Frontend scripts, dependencies, package manager, locked versions
supabase/migrations/	Executable relational schema and schema changes
.github/workflows/ci.yml	Checks actually enforced by CI
Executable code + tests	What is actually implemented and verifiable now

For exact versions and executable commands, trust manifests, lockfiles, and current scripts over prose documentation.
Accepted ADRs are historical records. Do not silently rewrite their rationale to match a new design. Material architecture changes require the team's approved ADR/update process and matching architecture documentation.
Known architecture documentation drift
The latest project design uses a generation queue + generation worker for image-to-3D work and a separate conversion queue + conversion worker for 3D-to-LEGO work. The generation worker, not the public API request handler, owns fal submission/status polling.
Some foundation documentation still describes the API calling the reconstruction provider directly and only the conversion path using Service Bus. Treat that older topology as stale. Before or with implementation of the queued generation path, reconcile the affected architecture documentation/ADR(s); do not leave contradictory sources in the repository.
Deviation requests - flag, never silently comply
If a request conflicts with this file or an accepted architecture/security contract:
1. Name the specific rule/decision.
2. Explain the concrete risk briefly.
3. Offer the simplest compliant alternative.
4. If reasonably waivable, require explicit human confirmation before proceeding.
5. If it changes architecture, public API, persistent data, security, cloud topology, or cost behavior, update the appropriate documentation/ADR in the same change.
Urgency, repetition, or "just do it for now" is not implicit authorization.
Current implementation status
The repository is currently a foundation, not the completed product. It includes:
- FastAPI root and /api/v1 health endpoints;
- domain dataclasses/enums and ApplicationError;
- purpose-specific repository Protocols;
- a provider-neutral reconstruction Protocol and deterministic fake provider;
- service-layer scaffolding for projects, reconstruction, and conversion validation;
- a conversion-worker entry-point scaffold;
- a React/Vite TypeScript health/status page;
- an initial Supabase PostgreSQL migration with RLS enabled and no permissive browser policies;
- backend/frontend tests, lint/type-check configuration, Docker, and GitHub Actions CI; and
- ADRs plus Azure deployment planning.
Authentication, concrete DB repositories, user/project/upload APIs, RLS policies/request identity plumbing, Azure Blob/Service Bus processing, fal.ai/TRELLIS integration, the real mesh-to-LEGO converter, the 3D UI, quotas, and production deployment are not implemented in this foundation unless later code proves otherwise.
Confirmed stack
Area	Project choice
Backend	Python 3.12, FastAPI, Pydantic/pydantic-settings
Persistence	SQLAlchemy 2.x async + asyncpg, Supabase-managed PostgreSQL
Backend HTTP	HTTPX
Backend tooling	uv, Ruff, mypy, pytest, pytest-asyncio
Frontend	React + TypeScript strict mode + Vite
Frontend package manager	npm
Frontend server state	TanStack Query
Frontend validation/forms	Zod; React Hook Form when justified
Browser 3D	Three.js / React Three Fiber / Drei when needed
Identity	Supabase Auth
DB schema workflow	Committed SQL migrations under supabase/migrations/
Binary artifacts	Azure Blob Storage
Durable messaging	Azure Service Bus
Image -> 3D	fal.ai / TRELLIS behind a provider boundary
Cloud target	Azure Container Apps, ACR, Blob, Service Bus, Key Vault, Static Web Apps
CI/CD	GitHub Actions; future Azure auth via OIDC/federated identity
API	JSON REST under /api/v1; unversioned /health probe
Architecture	Pragmatic modular monolith; API and workers run as separate processes from the backend codebase/image


Existing dependencies are not an instruction to import them everywhere. Use a package only where it improves the current solution.
Target workflow and architecture invariants
Authentication
- Browser authentication uses Supabase Auth.
- Browser sends the Supabase access JWT as Authorization: Bearer ... to FastAPI.
- The API verifies signature, issuer, audience, expiry, and required claims before trusting sub as the user ID. Do not merely decode a JWT.
- Refresh-token handling remains between browser and Supabase Auth; do not create a second password/token system in FastAPI.
- Do not hand-roll JWT cryptography; use a vetted mechanism when implemented.
Upload
- Validate upload metadata/type/size and authoritative quota/ownership rules before paid/expensive work.
- The API creates pending metadata and a short-lived, least-privilege Azure Blob upload URL scoped to the intended object.
- The browser uploads bytes directly to Blob Storage; the API should not become the file proxy.
- Track checksum/provenance when used by the workflow.
- Abandoned uploads need a bounded cleanup lifecycle when implemented.
Image -> 3D generation
- Validate ownership, upload readiness, quota/active-job rules, and idempotency before enqueueing.
- Persist/reuse the durable job first, then enqueue an identifier-only generation message.
- Return an asynchronous job resource; do not wait for fal.ai in the HTTP request.
- The generation worker owns fal submission and status checks.
- Provider-specific request/response/status schemas stop at the provider adapter boundary.
- Persist provider task ID/state safely.
- Schedule later status-check messages with bounded backoff; never hold a worker sleeping.
- Duplicate queue messages/status checks are normal and must be harmless.
3D -> LEGO conversion
- Validate source readiness, ownership, settings, quota, and idempotency before enqueueing.
- Persist/reuse the durable conversion/job and enqueue an identifier-only message.
- A conversion worker atomically claims eligible work, downloads the authoritative 3D artifact, runs conversion, uploads result artifacts, and persists result metadata/state.
- Failure becomes a safe terminal state/reason when retries are no longer appropriate.
- Reprocessing a duplicate message must not create inconsistent duplicate artifacts.
Browser progress
Polling is the current simple choice.
- Poll only while work is non-terminal; use a modest bounded interval/backoff and pause/deprioritize when the page is hidden where practical.
- Status polling must never retrigger paid work.
- Return 304 only when implementing proper conditional GET; otherwise return a normal 200 representation.
- Do not add SSE/WebSockets until a real scale/UX requirement justifies them.
Dependency direction
HTTP route -> application service -> purpose-specific repository/provider boundary -> infrastructure adapter
Workers use the same domain/application boundaries with worker-specific orchestration.
- Routes translate HTTP/auth input/output and stay free of raw SQL, Azure SDK calls, Service Bus code, fal-specific parsing, and geometry loops.
- Services own business rules/orchestration spanning boundaries.
- Domain code must not import FastAPI, SQLAlchemy, Azure, Supabase, or fal-specific infrastructure types.
- Repositories remain purpose-specific; do not create a generic CRUD repository base class.
- Interfaces/Protocols belong at real persistence/external boundaries, not around every internal class.
- Prefer the modular monolith over new microservices.
Code quality and readability
Simple, standard code
- Write for a reviewer who did not author the feature.
- Prefer a few explicit statements over a clever expression.
- Use descriptive domain names instead of vague names such as data, item, thing, process, or manager.
- Make I/O and side effects obvious.
- Use guard clauses when they reduce nesting and keep the happy path clear.
- Use named constants/configuration for non-obvious limits, timeouts, units, tolerances, and thresholds.
- A refactor must make code easier to understand, safer to change, easier to test, or meaningfully less duplicated.
Functions and abstractions
Create a helper when it names a domain operation, is reused meaningfully, isolates a side-effect/validation boundary, materially improves clarity, or creates a useful test seam. Do not extract a helper merely because a block is a few lines long.
Review/simplify code when you see:
- a function with multiple unrelated jobs;
- many unrelated parameters or boolean behavior flags;
- deep nesting;
- a God service/component/module;
- duplicated business rules;
- hidden I/O or mutable global state;
- magic values;
- catch-and-ignore error handling;
- N+1 database access;
- broad "utils" modules;
- an abstraction with only a hypothetical future use.
Fewer clear pieces are better than many tiny layers.
Comments
- Explain why, invariants, units, or non-obvious trade-offs; do not narrate obvious syntax.
- Do not add verbose AI-style comments/docstrings to every function.
- Update/remove stale comments when behavior changes.
Naming conventions
Thing	Convention
Python variables/functions/modules	snake_case
Python classes/enums	PascalCase
Python constants	UPPER_SNAKE_CASE
TypeScript variables/functions	camelCase
React components / TypeScript types	PascalCase
Environment variables	UPPER_SNAKE_CASE
JSON fields	camelCase unless an external contract requires otherwise
SQL tables/columns	snake_case


Backend and API rules
- Python runtime is 3.12; keep manifest, lockfile, CI, Docker, and typing assumptions aligned.
- Manage dependencies with uv; do not hand-edit uv.lock.
- Follow PEP 8 plus current Ruff/mypy configuration. mypy strict mode is intentional.
- Prefer dataclasses/enums/plain functions where sufficient; do not create a class solely to hold one stateless function.
- Avoid global mutable state.
- Keep async request paths non-blocking; CPU-heavy conversion belongs in workers.
- Public REST API lives under /api/v1; /health stays a lightweight unversioned operational probe.
- Long operations return asynchronous job resources rather than holding requests open.
- Request/response schemas belong at the HTTP boundary; domain objects should not depend on transport concerns solely for convenience.
- Business validation depending on DB/external state belongs in services, not only Pydantic validators.
- Use safe, stable errors; never expose stack traces, raw provider payloads, SQL details, private URLs/tokens, or internal paths.
- Preserve conventional HTTP semantics. Use 401 for unauthenticated, 403 for authenticated-but-forbidden, 409 for state conflicts where appropriate, 413 for oversized input, 422 for semantic validation, and 429 for quotas/rate limits with Retry-After when meaningful.
- Preserve idempotency for endpoints that create paid or durable asynchronous work.
- CORS is configuration; do not use wildcard production CORS with credentials.
- Outbound HTTP calls need explicit timeouts and bounded response handling.
Database, auth, and security rules
- Supabase Auth is the identity provider; do not create a parallel auth system.
- Never trust client-supplied user IDs for authorization when identity comes from verified JWT sub.
- Every user-owned read/write is scoped to the authenticated user at the API/database boundary.
- RLS is enabled. Do not disable it or add broad browser policies merely to unblock development.
- When API transactions are wired to PostgreSQL RLS, propagate only verified request identity/claims with an approved transaction-scoped mechanism and ensure pooled connections do not leak request context.
- Use least-privilege DB identities; migration, API, and worker responsibilities should not all receive unrestricted privileges.
- Schema changes use committed SQL migrations under supabase/migrations/; never hand-edit shared schema.
- Prefer normalized relational entities and real constraints/foreign keys/uniqueness. Use JSONB for bounded settings payloads, not as a substitute for queryable relational data.
- Add indexes for real ownership/state/idempotency/query patterns, not for appearance.
- Quota/active-job checks that can race must be transactionally safe.
- Worker job claims/state transitions must be atomic under duplicate/parallel delivery.
- Preserve data unless a reviewed destructive migration explains compatibility and recovery.
- User uploads/models are private application data. Do not put real user files/content in tests, fixtures, docs, logs, or commits.
Blob, queue, worker, and provider rules
- Azure Blob Storage stores binary artifacts; PostgreSQL stores metadata/provenance/blob identifiers.
- Use short-lived, narrowly scoped signed access for browser upload/download; never expose account keys or broad container permissions.
- Treat uploads and provider-generated model files as untrusted. Validate size/type/structure/resource bounds before deep processing.
- Database and Blob writes are not one transaction; represent incomplete/failure states honestly and clean them up/reconcile deliberately.
- Queue messages stay small: identifiers plus a message/schema version if needed. PostgreSQL remains the durable source of truth.
- Assume Azure Service Bus at-least-once delivery; workers must tolerate duplicates.
- Atomically claim work before expensive processing and complete a message only after required durable state/artifacts are safe.
- Retry only failures that may succeed later. Retries are bounded; permanent failures become terminal and repeated failures go to dead-letter handling rather than infinite loops.
- Exact retry/delivery/worker-count values belong in configuration/approved design, not scattered magic numbers.
- The generation worker owns the paid fal workflow. Domain/services must not depend on fal-specific JSON shapes.
- Never log FAL_KEY, JWTs, SAS URLs, private source URLs, or full private provider payloads.
- Use deterministic fake providers in normal automated tests; real provider smoke tests are deliberate/manual.
LEGO conversion and 3D rules
The detailed converter is not implemented in the current foundation. Do not invent a complex converter architecture in advance.
When implementing it:
- Keep CPU-intensive conversion out of API request handlers.
- Make coordinate systems/units explicit.
- Name geometry tolerances/algorithm thresholds; do not scatter magic numbers.
- Keep conversion deterministic for identical input/settings/version unless randomness is explicitly required and controlled.
- Bound mesh size, memory, search/fit iterations, target piece counts, and other potentially explosive work.
- Prefer clear algorithms over dense numerical tricks unless profiling proves a bottleneck.
- Do not fabricate pieces merely to hit a requested piece count.
- Keep model, BOM/parts, instructions, previews, and downloadable artifacts traceable to the same conversion/source/settings.
- Collision, connectivity, stability, insertion feasibility, and physical buildability are different claims. Do not claim one proves another.
- New fitting/repair heuristics need a stated assumption and deterministic regression tests.
- Benchmark before claiming a performance optimization.
Frontend rules
- Preserve TypeScript strict, noUnusedLocals, and noUnusedParameters; fix types instead of bypassing them.
- Use npm; do not switch package managers.
- TanStack Query owns server/async state. Do not add global state management while local state + query state are sufficient.
- Use Zod for untrusted API/external data, not every internal object.
- Use React Hook Form only when a form is complex enough to benefit from it.
- Import Three.js/R3F/Drei only where the 3D experience needs them; do not load heavy 3D code into unrelated views.
- Separate substantial fetching/polling/3D lifecycle logic from rendering when it becomes non-trivial; do not create a hook/component for every tiny expression.
- Keep relevant loading, auth, quota, queued, processing, error, retry, empty, and success states explicit.
- Preserve semantic HTML, keyboard/focus behavior, touch usability, and responsive layouts.
- Clean up timers, subscriptions, object URLs, AbortControllers, and Three.js resources.
- Paid work must be triggered by explicit user intent, never by component remounts, render cycles, tab changes, or automatic query retries.
- Do not silently add Prettier or another formatter; use current ESLint/TypeScript conventions unless the team explicitly adopts one.
Rate limits, pagination, and scalability
- Enforce authoritative quotas server-side; frontend limits are UX only.
- Values shown in rough design diagrams are examples until explicitly accepted. Keep limits named/configurable.
- Paid generation should have bounded per-user rate/concurrency protection when implemented.
- Return 429 with useful retry information for time-window quotas.
- Do not implement correctness-critical quotas with in-process counters.
- For small bounded per-user history, offset/page pagination is an intentionally simple choice. Validate bounds and index the ownership/sort query.
- Use cursor/keyset pagination only when the listing's scale/mutation behavior actually requires it.
- Reject invalid/oversized work before provider/storage/CPU expense.
- Scale through stateless API + durable queues + independently scalable workers + Blob + PostgreSQL before adding more services.
- Measure before optimizing. Do not sacrifice readability for speculative micro-optimizations.
- Do not add a cache until repeated cost and invalidation rules are understood.
- Worker min/max concurrency belongs in deployment configuration backed by provider limits, CPU/memory, cost, and measured load.
Testing and required checks
Whoever changes behavior owns the relevant tests.
- Test behavior/contracts, not private implementation details.
- A reproducible bug fix should include a regression test unless technically impossible; explain why if omitted.
- New business/security/state-transition rules require focused tests at the owning layer.
- Cover meaningful failure paths, authorization, idempotency/duplicate delivery, and edge cases relevant to the feature.
- Keep normal tests deterministic, isolated, and offline.
- Mock provider/Azure/network behavior; never call paid/production services by default.
- Do not write meaningless tests that merely restate constants or library behavior.
- Avoid fixed sleeps in tests where state/time can be controlled explicitly.
- Playwright may be added when stable high-value end-to-end user journeys exist; do not create a placeholder E2E suite prematurely.
- Aim for strong coverage of critical behavior, but do not game coverage with low-value assertions or add coverage tooling during an unrelated task without approval.
- Never claim a check passed if it was not actually run.
Backend, from backend/:
uv run ruff check .
uv run mypy app
uv run pytest -q
Use uv run ruff format --check . when checking Python formatting.
Frontend, from frontend/:
npm run lint
npm run test -- --run
npm run build
For backend/container changes, validate docker build -t image-to-lego-api:local backend when the environment permits. If a check cannot run, say so explicitly.
Cloud, documentation, and Git
- Azure is the accepted cloud target. Do not introduce AWS/GCP equivalents without a new architecture decision.
- Intended services are Container Apps, ACR, Service Bus, Blob Storage, Key Vault, and Static Web Apps.
- API and workers may share one backend image with different startup commands, but scale/resources independently.
- Deployment uses immutable/versioned images and GitHub OIDC/federated identity; do not store long-lived Azure client secrets in GitHub.
- infra/ is currently a reserved boundary. Do not add Terraform/Bicep/Pulumi until an explicit infrastructure task selects the approach.
- Keep cloud cost in mind, especially fal calls, idle workers, storage, and unnecessary retries, without building a premature optimization platform.
- Keep README.md setup/status truthful.
- Update architecture docs/ADRs in the same change when public APIs, persistent data, security boundaries, queue topology, deployment, or durable architecture changes.
- Distinguish planned, implemented, locally verified, and deployed/hosted verified behavior.
- Use Mermaid for Markdown sequence/flow diagrams unless the team approves another format.
- Inspect current branch/status/diff before editing and preserve unrelated work.
- Keep PRs focused and follow .github/PULL_REQUEST_TEMPLATE.md.
- Never force-push or rewrite shared history.
- Do not commit/push/merge/rebase/reset/clean/delete branches/deploy unless explicitly requested by the human.
Definition of Done - agent-checkable
Before presenting a change as ready for human review, confirm all applicable items:
- Requested behavior is implemented without unrelated scope expansion.
- Architecture/security contracts are followed or an approved deviation is documented.
- The solution is the simplest reasonable design for the current requirement.
- No unnecessary dependency, abstraction, helper, class, interface, file, service, table, cache, queue, retry loop, or framework was introduced.
- No dead/commented-out code, unused imports, stale flags, speculative scaffolding, or accidental generated files remain.
- Names and structure make non-trivial logic readable.
- Business rules live at the correct layer and are not duplicated across UI/routes/workers/database code.
- Errors/edge cases are handled without hiding failures.
- Identity/ownership/RLS, secrets, quotas, resource limits, and private artifacts remain protected.
- Paid-provider work and queue processing are idempotent where retries/duplicates can occur.
- DB changes use committed migrations and justified constraints/indexes.
- API changes use conventional HTTP semantics, authorization, validation, safe errors, and tests.
- Frontend changes cover relevant user states and remain accessible/responsive.
- Worker changes handle duplicate delivery and terminal failures safely.
- Conversion/geometry changes are bounded/deterministic where intended and have regression tests.
- Relevant lint, type checks, tests, builds, and Docker checks pass, or unrun checks are disclosed.
- Automated tests did not contact real paid/production services.
- Documentation/ADRs were updated where contracts changed.
- The final diff was reviewed for accidental complexity and unrelated edits.
Professor-readability pass
Before finishing a non-trivial change, read the diff as if you had to explain it orally to the professor:
1. Can every new file, class, interface, major function, table, service, and dependency be justified in one sentence?
2. Is any abstraction present before there is a concrete need for it?
3. Could the same correct behavior use fewer layers/dependencies or clearer control flow?
4. Are important state transitions, security decisions, units, limits, retries, and side effects explicit?
5. Would another competent developer understand the code without asking what an AI-generated abstraction is for?
6. Do comments explain the non-obvious reasons instead of narrating syntax?
7. Do tests prove meaningful behavior/failure/authorization/idempotency rather than merely execute lines?
8. Do the code, architecture, and documentation tell the same story?
If not, simplify or clarify before presenting the change.
When you are unsure
- Inspect the relevant source of truth and current implementation first.
- For a small, local, reversible detail, choose the simplest option consistent with existing patterns and state the assumption.
- If ambiguity affects public API, authentication/authorization, persistent data, queue semantics, paid-provider cost, cloud topology, privacy, artifact integrity, or converter meaning, surface it before deciding.
- If authoritative sources conflict, state exactly what conflicts and require them to be reconciled. Do not silently pick a convenient default.
- When a sophisticated solution and a conventional simple solution both meet the requirement, choose the conventional simple solution.