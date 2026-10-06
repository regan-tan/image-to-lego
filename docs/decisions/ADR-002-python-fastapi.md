# ADR-002: Python and FastAPI

## Status

Accepted

## Context

The API must coordinate typed HTTP workflows and will share Python geometry/domain code with an independently running conversion worker.

## Decision

Use Python 3.12, FastAPI, Pydantic/pydantic-settings, SQLAlchemy 2.x with asyncpg, HTTPX, and Uvicorn. Manage and lock dependencies with uv. Keep CPU-intensive work outside API request processing.

## Alternatives considered

- Node.js for the API, which would split server and geometry code across languages.
- Django, whose larger batteries-included surface is unnecessary for the planned API.
- Flask, which would require more assembly for typed validation and OpenAPI.

## Rationale

Python fits the geometry pipeline, while FastAPI provides explicit typing, validation, async I/O, and OpenAPI with limited framework ceremony.

## Trade-offs / consequences

Async code requires discipline around blocking operations. Type checking does not replace runtime tests. The worker must be deployed and scaled separately even though it shares the repository and image.

