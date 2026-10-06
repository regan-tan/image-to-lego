# Testing strategy

The foundation uses a fast, isolated test pyramid:

- backend unit/API tests run with Pytest and an in-process FastAPI client;
- provider contract tests use the deterministic fake reconstruction provider;
- frontend component tests run with Vitest, React Testing Library, and jsdom; and
- health requests are mocked in frontend tests.

Tests must not call real fal.ai endpoints, production Supabase projects, Azure services, or paid APIs. Future integration tests should use explicit disposable local/test infrastructure and remain separate from the default unit suite. Playwright can be introduced when stable user journeys exist; a large placeholder E2E suite would add no value now.

