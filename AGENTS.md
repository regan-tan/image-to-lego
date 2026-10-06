LEGO Builder: Agent Coding Standards

LEGO Builder turns image-derived 3D geometry into a structured LEGO model with a 3D view, exact parts list, LDraw export, and draft instructions. This file defines project-wide rules for every coding agent working in this repository, including Codex, Claude Code, Cursor, Copilot, and similar tools.

This is a university capstone project. The code will be graded. Optimize for correctness, clarity, maintainability, testability, and explainability to a professor.

AGENTS.md is human-owned. Do not modify it unless the human explicitly asks you to.

CRITICAL INSTRUCTIONS
These override convenience, speed, and reasonable-seeming shortcuts.

- Keep the implementation as simple as the requirements allow. Prefer conventional, explicit code over clever, compressed, highly abstract, or framework-heavy code.
- If two approaches satisfy the same requirement, choose the one that is easier to read, explain, test, debug, and maintain.
- The project is already technically complex because of image reconstruction, 3D geometry, LEGO fitting, validation, rendering, and artifact consistency. Do not manufacture extra software complexity to make the project appear more advanced.
- Do not add a dependency, framework, service, abstraction layer, design pattern, database table, cache, queue, worker, retry system, or new architectural boundary unless the current requirement genuinely needs it.
- Reuse the standard library, platform APIs, and existing project dependencies before proposing anything new.
- Do not build speculative infrastructure for hypothetical future requirements.
- Preserve the separation between probabilistic image/3D reconstruction and deterministic LEGO conversion, catalog validation, inventory, export, and artifact-consistency checks.
- Model, parts list, LDraw export, and instructions for a result must refer to the same immutable model revision.
- A rendered/exported result is a digital candidate unless appropriate buildability evidence exists. Never present visual plausibility, connectivity checks, or successful export as proof of physical buildability.
- Never substitute sample data, a committed example, or mocked success for a real user conversion. Fixtures and demos must be labelled explicitly.
- Never bypass authentication, owner checks, integrity checks, file/resource limits, or validation to make development easier.
- Never commit secrets, provider keys, access tokens, credentials, private uploads, or .env contents.
- Inspect the current code and relevant source-of-truth documents before changing behavior. A document describing a proposed feature is not evidence that the feature exists.
- If accepted requirements, architecture, code, tests, or deployment documentation materially conflict, surface the conflict instead of silently choosing one.

GRADING-AWARE ENGINEERING PRIORITIES  
The capstone rubric rewards code cleanliness, architecture, database design, API design, frontend quality, scalability, cloud deployment, innovation, documentation, testing, and teamwork. Treat these as quality dimensions, not reasons to add unnecessary machinery.

- Code cleanliness: readable names, coherent responsibilities, conventional structure, useful comments, and no unnecessary indirection or dead code.
- Architecture: a small number of clear boundaries and understandable data flows.
- Complexity / innovation: show sophistication through the actual image-to-3D-to-LEGO problem, not gratuitous design patterns or services.
- Database: schema, constraints, and indexes should follow real entities and query patterns.
- API: predictable REST-style behavior, validation, authorization, safe failures, and appropriate status codes.
- Frontend: clear user flow, responsive/accessibility-conscious UI, and truthful backend state.
- Scalability: bounded work, idempotency, resource limits, and sensible deployment boundaries before more infrastructure.
- Testing: meaningful automated tests for critical behavior and regressions.
- Documentation: another developer or professor should be able to set up, run, test, and understand the system without reverse-engineering it.
DO NOT RULES
- Do not overengineer.
- Do not add a library when built-ins, platform APIs, or an existing dependency provide a clear solution.
- Do not add a dependency without explicit human approval. Name it, explain why it is needed, why existing options are insufficient, and what maintenance/security cost it adds.
- Do not upgrade dependencies, frameworks, runtimes, or lockfiles incidentally during unrelated work.
- Do not introduce another ORM, HTTP framework, state-management library, geometry library, validation framework, logging framework, or UI system without an approved need.
- Do not create an interface, base class, factory, strategy registry, plugin system, repository layer, or generic wrapper solely because it might be useful later.
- Do not create one-line forwarding helpers that add no meaningful naming, validation, reuse, test seam, or domain concept.
- Do not fragment simple code into many tiny functions/files merely to reduce line count.
- Do not allow a function, component, class, or module to accumulate unrelated responsibilities. Split only at a real responsibility boundary.
- Do not create generic dumping grounds such as helpers, manager, common, or utils when a specific domain name exists.
- Do not use unnecessary inheritance, metaprogramming, reflection, decorators, or hidden control flow.
- Do not use nested ternaries or dense one-liners for non-trivial logic.
- Do not duplicate business rules across routes, UI, converter code, and tests. Put each rule in the layer that owns it.
- Do not prematurely DRY a few obvious lines into a generic abstraction. Small duplication can be clearer than a bad abstraction.
- Do not add caching, concurrency, batching, background work, polling, or retries without a demonstrated requirement or measured problem.
- Do not automatically retry paid or uncertain provider work unless the contract explicitly makes it safe.
- Do not swallow exceptions, use empty catches, or convert unknown failures into successful/default output.
- Do not log uploads, private model contents, provider payloads containing private data, tokens, signed URLs, or secrets.
- Do not use TypeScript any merely to bypass a type problem.
- Do not use Python wildcard imports.
- Do not add dead code, commented-out implementations, unused imports, stale feature flags, or speculative TODO code.
- Do not perform broad cleanup/refactoring during a focused feature unless it is necessary to implement the feature safely.
- Do not refactor reconstruction-site/ into site/ merely to remove duplication; their separation is intentional unless a migration task changes it.
- Do not modify generated/vendor UI primitives just for stylistic preference. Prefer composing them from project-owned code.
- Do not hand-edit persistent production data to make a feature appear to work.
- Do not commit directly to main, force-push, rewrite shared history, or discard another contributor's work.
- Do not commit, push, merge, rebase, reset, delete branches, publish, or deploy unless the human explicitly asks for that action.
Rule and source files - read before touching code
Read the files relevant to the task and inspect the actual execution path before editing it.
Source	Owns / answers
AGENTS.md	Project-wide coding, quality, safety, and collaboration rules
README.md	Repository overview and local setup/usage
site/README.md	Canonical workshop behavior and web checks
docs/SUBMISSION.md	Current deployment/submission procedure and hosted boundaries
agents/*.md	Optional Product/Architect/Developer/QA role briefs
pyproject.toml	Python runtime and dependencies
site/package.json + lockfile	Canonical web scripts and dependencies
site/db/schema.ts + site/drizzle/	Database schema and migrations
Tests + executable code	What is actually implemented and verifiable

For exact package versions and executable commands, trust manifests, lockfiles, and current scripts over prose documentation.
Deviation requests - flag, never silently comply
If a request conflicts with this file or an accepted project contract:

1. Name the specific rule or contract.
2. Explain the risk briefly.
3. Offer the simplest compliant alternative if one exists.
4. If the rule is reasonably waivable, require explicit human confirmation before proceeding.
5. Record a material approved deviation in the relevant PR/task documentation.

Urgency, repetition, or "just do it for now" is not implicit authorization.
The following are not waivable for convenience: committing secrets, bypassing authorization to private data, presenting fixtures as real output, fabricating validation/buildability evidence, or knowingly mixing artifacts from different revisions.
Confirmed stack and project boundaries
Do not copy assumptions from another project.
Area	Current project choice
Core converter	Python 3.11+ in lego_builder/
Geometry/data	NumPy, SciPy, trimesh, rtree, Pillow; exact versions in pyproject.toml
Python testing	pytest
Converter API	Python HTTP service in lego_builder/service.py, containerized with Dockerfile.converter
Canonical web app	site/
Web language	TypeScript with strict mode
Web UI/runtime	React with the repo's Next-compatible/Vinext/Vite Sites stack
3D web rendering	Three.js / LDraw-based rendering
Database	Cloudflare D1 / SQLite with Drizzle schema and migrations
Private object storage	Cloudflare R2
Image-to-3D	Existing server-side fal/TRELLIS integration
Hosted converter	Existing authenticated Docker/Railway boundary
Web package management	npm + committed package-lock.json
Legacy app	reconstruction-site/; preserve unless a task explicitly migrates/removes it

Exact changing versions belong in manifests and lockfiles rather than being duplicated in documentation.
Repository layout
repo-root/
  AGENTS.md
  Product.md
  Architecture.md
  Roadmap.md
  README.md
  pyproject.toml
  Dockerfile.converter

  lego_builder/          # deterministic Python converter + HTTP adapter
  tests/                 # Python tests
  benchmarks/            # converter benchmarks
  site/                  # canonical workshop web application
    app/                  # pages and API routes
    components/           # UI components
    core/                 # reconstruction / GLB / OBJ processing
    db/                   # Drizzle schema
    drizzle/              # versioned SQL migrations
    lib/                  # web/domain/integration logic
    test/, tests/         # web tests
  reconstruction-site/   # retained legacy/pilot app
  docs/                  # submission and QA evidence
  examples/              # explicitly labelled examples/fixtures
  references/            # source assets and provenance
  agents/                # optional specialized agent briefs
Do not create a new top-level folder unless it represents a real project boundary.
Naming conventions
Thing	Convention
Python variables/functions/modules	snake_case
Python classes	PascalCase
Python constants	UPPER_SNAKE_CASE
TypeScript variables/functions	camelCase
React components / TypeScript types	PascalCase
TypeScript filenames	Follow existing convention; prefer descriptive kebab-case
API JSON fields	camelCase unless an external contract requires otherwise
SQL tables/columns	snake_case
Drizzle application properties	camelCase mapping to SQL names
Environment variables	UPPER_SNAKE_CASE

Prefer precise domain names: sourceObjSha256 over hash2, validatePlacement over processData, conversionRequest over item.
Code quality and readability
Simplicity first

- Write for a reviewer who did not author the code.
- Prefer explicit intermediate variables when they clarify geometry, validation, security, or state transitions.
- Prefer a few clear statements over a clever expression.
- Keep side effects obvious. Keep I/O, network, persistence, and provider calls near clear boundaries.
- Preserve existing conventions unless they cause a concrete problem.
- A refactor must make code easier to understand, safer to change, easier to test, or meaningfully less duplicated.
Functions and abstractions
A function should represent one coherent operation.
Create a helper when it is reused, names a meaningful domain operation, isolates a side effect/validation boundary, makes complex logic clearer, or creates a useful test seam. Do not extract a helper merely because a block is a few lines long.
Prefer a small number of cohesive parameters. Many unrelated parameters or boolean flags are a design smell; reconsider the responsibility before adding more.
Use a class when it owns coherent state/lifecycle/behavior. Prefer plain functions and data structures when a class adds no value.
Avoid abstractions before concrete need. A second real implementation/use case is stronger justification than a hypothetical future one.
Control flow and errors
- Use guard clauses when they reduce nesting and keep the happy path clear.
- Make important workflow states explicit rather than scattering boolean flags.
- Use named constants for limits, tolerances, units, timeouts, and non-obvious thresholds.
- Make coordinate systems/units clear where confusion is possible: studs, plates, LDraw units, pixels, source axes, transformed axes.
- Validate at boundaries and fail with a specific actionable error.
- Catch only errors the current layer can translate, recover from, or clean up after.
- Never expose stack traces, credentials, provider response bodies, private URLs, or internal file paths to users.
Comments
Comments explain why, invariants, or non-obvious tradeoffs - not obvious syntax.
Do not add verbose AI-style comments/docstrings to every function. Remove stale comments when behavior changes.
Python rules
- Follow normal PEP 8 conventions and the existing project style.
- Add type hints to public interfaces and non-trivial new logic when they improve understanding; do not add a new typing framework.
- Prefer pathlib.Path for new filesystem logic unless an API requires strings.
- Never use mutable default arguments or wildcard imports.
- Avoid unnecessary global mutable state.
- Keep deterministic converter logic deterministic. Any necessary randomness must be controlled and reproducible.
- Prefer readable NumPy/SciPy code over extremely dense vectorized expressions.
- Optimize only after identifying a real bottleneck; do not replace clear code with a numerical trick solely for elegance.
- Bound file sizes, arrays/grids, fitting attempts, iterations, and expensive work before allocation/processing where practical.
- Use existing pyproject.toml dependencies; do not add a package to replace a small amount of clear standard-library code.
TypeScript and React rules
- Preserve TypeScript strict mode. Fix type problems rather than bypassing them.
- Use explicit domain types at API/storage boundaries.
- Avoid any; isolate unavoidable untyped external data and validate it.
- Separate rendering from substantial fetching, job orchestration, 3D lifecycle management, or transformation logic when those concerns become non-trivial.
- Do not create a hook/component for every tiny expression. Extract around real state, interaction, or rendering responsibilities.
- Reuse existing UI primitives rather than adding another component library.
- Do not add global state management while local/server state is sufficient.
- Keep loading, empty, failure, unauthorized, stale-result, retry, and success states explicit.
- Preserve keyboard accessibility, focus behavior, touch usability, and responsive layouts when changing UI flows.
- Clean up Three.js resources, timers, subscriptions, object URLs, and abortable work when their owning view is replaced/unmounted.
- Never expose server-only credentials in client code or client-visible environment variables.
Architecture rules
- site/ is the canonical workshop for current web work unless the task explicitly targets the legacy pilot.
- reconstruction-site/ is retained legacy/pilot code; do not casually synchronize, merge, or delete it.
- lego_builder/ owns deterministic mesh-to-LEGO conversion and the authenticated converter boundary.
- Keep probabilistic reconstruction separate from deterministic validation/conversion.
- Keep one canonical structured model revision as the source for rendered model, parts quantities, LDraw, and instruction membership.
- Do not create parallel representations of the same result without an explicit conversion boundary and consistency check.
- Prefer existing boundaries over a new microservice. A new service requires a clear operational/security reason and explicit approval.
- Reuse existing provider/integration boundaries; do not build a plugin framework for hypothetical providers.
- Treat external provider output, uploads, LDraw, OBJ/GLB files, and metadata as untrusted input.
- Keep resource limits and failure states explicit around expensive operations.
Image, 3D, and LEGO invariants
- A source image cannot guarantee unseen geometry. Do not claim exact reconstruction of hidden surfaces.
- Probabilistic reconstruction may be uncertain; catalog, integrity, artifact-consistency, and bounded resource checks should be deterministic wherever possible.
- The general OBJ converter must use geometry, not filenames, object names, semantic group names, or a hidden subject-specific template.
- Subject-specific optimization is allowed only when its prerequisites and scope are explicit; never silently route arbitrary objects through it.
- Do not add artificial parts merely to reach a requested piece count.
- Do not add an external stand/support unless the accepted requirement asks for one.
- Emit only supported part IDs, transforms, colors, and validated part/color combinations.
- Do not invent a part/color combination because it looks plausible.
- Preserve provenance needed to prove artifacts belong together, including relevant source/settings hashes and revision identifiers.
- Viewer, LDraw, bill of materials, and instructions must reconcile to the same placements.
- Missing instruction boundaries remain missing; the UI must not fabricate assembly steps to create a complete-looking result.
- Collision, connectivity, insertion feasibility, stability, and physical-build success are different claims. Do not treat one as proof of another.
- New fitting heuristics must state their geometric assumption and include deterministic regression tests.
- New tolerances/repair thresholds must be named, bounded, and justified - never unexplained magic numbers.
- Meaningful converter performance changes should be benchmarked on representative inputs.
Backend and API rules
- Keep route/HTTP handlers focused on request parsing, authentication/authorization, boundary validation, calling the owning domain operation, and shaping the response.
- Do not bury geometry or workflow business logic inside route handlers.
- Reuse existing HTTP/error conventions where they fit.
- Use appropriate status codes and stable, safe error responses.
- Validate content type, payload shape, identifiers, hashes, and size/resource limits before expensive or paid work.
- Preserve idempotency for operations that can create paid work or durable state.
- Authorize owner-private resources at the server/data-access boundary, not only in the UI.
- Use explicit outbound timeouts and bounded response reads.
- Preserve allowlists/fixed-origin rules for remote asset retrieval. Never fetch arbitrary user-supplied URLs from a privileged server context.
- Health endpoints must stay lightweight.
Database and persistence rules
- D1/SQLite schema changes go through Drizzle schema definitions and committed migrations.
- Do not manually mutate shared/production schema or reset a persistent database to make migration easier.
- Design tables from actual entities, ownership, state transitions, integrity requirements, and query patterns.
- Add indexes for real access patterns, uniqueness, ownership, idempotency, or state coordination - not to make the schema look sophisticated.
- Preserve owner scoping on private records.
- Prefer database constraints for invariants the database can enforce reliably.
- Avoid opaque JSON/text for data that current behavior needs to query relationally; conversely, do not normalize stable opaque manifests merely for theoretical purity.
- Avoid N+1 query patterns in new flows.
- Preserve existing data unless an explicitly approved migration plan says otherwise.
Security and data handling
- Never commit secrets, .env contents, tokens, signed private URLs, or user artifacts.
- Keep provider/converter credentials server-side only.
- Validate uploads/provider files for type, size, structure, and resource bounds before deeper processing.
- Prevent path traversal and unsafe archive/file extraction. Do not follow arbitrary OBJ material/texture paths.
- Do not log private payloads or secrets.
- Preserve same-origin/Origin checks where they protect state-changing operations.
- Enforce ownership at every private database/storage access path.
- Do not trust client-provided owner IDs, hashes, file metadata, or completion state without server verification.
- Preserve integrity links between source image, GLB/OBJ, settings, and LDraw result.
- Keep public sample/Admin-local flows separate from private paid-generation flows.
- Automated tests must not call paid providers by default.
Performance and scalability
- Bound input sizes, part counts, geometry work, downloads, request sizes, timeouts, and concurrency.
- Reject clearly invalid/oversized work before expensive allocation.
- Prefer bounded deterministic algorithms over unbounded searches.
- Do not add caching until repeated cost and invalidation rules are understood.
- Do not add concurrency merely to look performant; consider determinism, memory, races, provider limits, and runtime limits first.
- Do not create a queue/worker system when the current synchronous/job model meets the requirement.
- Measure before optimizing and keep reproducible benchmarks for meaningful converter performance changes.
- Keep the converter independently containerizable and do not store durable user state in its ephemeral runtime.
- Avoid duplicate paid reconstruction work; preserve completed stages for recovery/retry.
Testing
Whoever changes behavior owns the relevant tests.
- Test behavior and contracts, not private implementation details.
- A reproducible bug fix should include a regression test.
- A new domain rule should have a focused test at the layer that owns it.
- Do not add meaningless tests that only assert constants, library behavior, or trivial markup.
- Keep normal automated tests deterministic and offline.
- Mock/stub external paid providers and network services.
- Real provider/hosted smoke tests are deliberate manual evidence, not the default suite.
- Avoid fixed sleeps; use deterministic time/state control where practical.
- Fixtures must be labelled and must never be reported as proof of a live generation.
Python / converter
Run relevant tests; for normal repository-wide converter verification:
python -m pytest -q
Test geometry invariants, catalog validity, artifact consistency, provenance/hashes, resource bounds, failures, and regressions relevant to the change.
Canonical web app
From site/, run the relevant checks:
npm test
npm run typecheck
npm run lint
npm run build
Do not claim a check passed if it was not run. If the environment prevents a check, say what could not be run and what was verified instead.
If the task explicitly changes reconstruction-site/, use that package's own scripts; passing site/ does not validate the legacy app.
Frontend quality
- Preserve a clear journey from image input through reconstruction/conversion to Model, Parts, and Instructions.
- Never show success earlier than backend/domain state justifies.
- Keep revision and validation state understandable where relevant.
- Use actionable failure/recovery states.
- Preserve responsive layout and keyboard/touch usability for changed flows.
- Avoid decorative complexity that obscures state or makes the workflow harder to understand.
- Do not rerun paid work merely because a user changes tabs/views.
Documentation
- Keep setup instructions executable and current.
- Product.md owns user-facing acceptance criteria.
- Architecture.md owns durable technical contracts/rationale.
- Roadmap.md owns scope, phase gates, and open direction.
- docs/SUBMISSION.md owns current deployment/submission procedure and evidence boundaries.
- Link rather than duplicate changing facts across documents.
- Distinguish proposed, implemented, locally verified, hosted verified, and physically verified.
- Do not describe future work as implemented or local evidence as hosted evidence.
- Update docs in the same change when public behavior, setup, architecture, API contracts, deployment steps, or durable assumptions change.
- Avoid documentation churn for internal refactors with no contract impact.
Git and collaboration
- Treat main as the stable shared integration branch.
- Work on short-lived feature/personal branches. Codex-created branches may use the existing codex/ prefix; otherwise follow the team's existing convention.
- Inspect git status and the current diff before editing. Preserve unrelated/uncommitted work.
- Never force-push, rewrite shared history, reset/clean away work, or discard another contributor's changes.
- Do not perform Git publication actions unless explicitly requested by the human.
- Keep commits/PRs focused on one coherent unit of work.
- A PR should explain changed behavior, important technical decisions, checks run, and known limitations/risks.
- Do not hide a broad refactor inside a feature PR.
Optional specialized agents
Role briefs under agents/ may be used for substantial work, but delegation must reduce risk or improve independent review rather than create ceremony.
Role	Use when
Product	User behavior, scope, acceptance criteria, UX ambiguity
Architect	Major boundaries, schema/API/provider/deployment/security/geometry decisions
Developer	Approved multi-file implementation
QA	Independent verification of substantial or high-risk behavior

For a small localized fix, one agent may implement and verify directly. Role-specific instructions never override this file.
Definition of Done - agent-checkable
Before presenting a change as ready for human review, confirm all applicable items:

- Requested behavior is implemented without unrelated scope expansion.
- Product/Architecture contracts are followed, or an approved deviation is documented.
- The implementation uses the simplest reasonable design.
- No unnecessary dependency, abstraction, helper, class, file, service, table, cache, queue, retry loop, or framework was introduced.
- No dead/commented-out code, unused imports, stale flags, or speculative scaffolding remains.
- Names communicate domain meaning and non-trivial logic is readable.
- Errors/edge cases are handled at the correct boundary.
- Secrets, private data, authorization, integrity, and resource limits remain protected.
- Database changes have a versioned migration and preserve existing data expectations.
- API changes have validation, authorization, appropriate status codes, and tests.
- Frontend changes include relevant loading/error/empty/accessibility states.
- Geometry/converter changes preserve deterministic invariants and have focused regression tests.
- Model, parts, export, and instruction artifacts still use the same revision where applicable.
- Relevant tests, typecheck, lint, and build checks pass.
- Automated tests do not accidentally invoke a real paid provider.
- Durable behavior/contract documentation is updated where necessary.
- The final diff has been reviewed for accidental complexity and unrelated edits.
- Any check not run is disclosed explicitly.
Professor-readability pass
Before finishing, read the diff as if you had to explain it orally to the professor:

1. Can every new file, class, major function, and dependency be justified in one sentence?
2. Is any abstraction present before there is a concrete need for it?
3. Could the same behavior be implemented more clearly with fewer layers or dependencies?
4. Are important algorithms and constraints understandable from names, structure, tests, and a few useful comments?
5. Do the tests prove important behavior rather than merely exercise code?
6. Does the repository tell a coherent story from architecture to implementation to testing to deployment?

If not, simplify or clarify before presenting the change.
Information routing
Topic	Source of truth
Agent behavior / coding standards	AGENTS.md
User-facing behavior	Product.md
Technical invariants / boundaries	Architecture.md
Scope / gates / open direction	Roadmap.md
Dependencies / executable commands	Manifests, lockfiles, scripts
Database schema	site/db/schema.ts + committed migrations
Implemented behavior	Code + tests
Deployment/submission	docs/SUBMISSION.md + current deployment config
Verification claims	Tests and specifically labelled QA/hosted/physical evidence

When you are unsure
Do not invent a material requirement or new architecture to fill a gap.

- Inspect the owning source of truth and current implementation first.
- For a local, reversible ambiguity, use the simplest option consistent with existing patterns and state the assumption.
- If ambiguity affects product scope, public API, persistent data, provider cost, security/privacy, deployment, canonical artifact meaning, or buildability claims, surface it before making the decision.
- If authoritative sources conflict, state exactly what conflicts and which source owner should resolve it. Do not silently pick one.
- When choosing between a sophisticated solution and a conventional simple one, prefer the conventional simple one.

