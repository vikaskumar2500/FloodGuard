# FloodGuard Testing Strategy & Philosophy

## Philosophy
The purpose of FloodGuard testing is not to blindly increase test count, but to build a deterministic, layered, maintainable testing strategy that proves critical invariants. The system should be safe to refactor because critical behavior is protected automatically.

## Test Pyramid
1. **Browser E2E**: Slowest, least numerous, tests the full flagship user journey (login -> calculate route -> inject hazard -> real-time reroute).
2. **Integration Tests**: Moderate speed, test the boundaries against real local PostgreSQL, Redis, and SQS/EventBridge.
3. **Contract Tests**: Fast, test that API schemas and event JSON payloads preserve backward compatibility.
4. **Component / Unit Tests**: Fastest, most numerous. Isolate complex algorithms (e.g. A* vs Dijkstra, ML feature processing, caching logic). Property-based tests go here.

## Categories & Markers
We use Pytest markers to categorize our suites in `pyproject.toml`:
- `unit`: fast deterministic unit tests
- `integration`: requires real external DB/cache (opt in with RUN_INTEGRATION_TESTS=1)
- `contract`: schema and API contract tests
- `e2e`: end-to-end system tests
- `security`: auth and RBAC tests
- `ml`: ML routing and model tests
- `browser`: UI E2E browser tests
- `slow`: tests taking > 2 seconds
- `aws_smoke`: tests interacting with real AWS (opt in with RUN_AWS_SMOKE_TESTS=1)

## Fixtures and Determinism
- Use `function` scope fixtures by default.
- Use explicit random seeds for ML and simulator scenarios.
- Do NOT use exact UUID match assertions unless injecting deterministic UUIDs.
- Fake clock (`monkeypatch` over `time.time`) is used for rate limits and time-dependent logic.
- Redis caching keys are prefixed with test-specific namespaces.

## External Service Policy
Tests run offline without AWS or the public internet by default. External dependencies are handled via:
- Fake/in-memory implementations for SQS/EventBridge in normal unit tests.
- Mock external APIs (OpenMeteo, Bedrock Assistant) using responses recorded from real providers.
- Real AWS services are ONLY tested when explicitly passing `RUN_AWS_SMOKE_TESTS=1` and marked as `aws_smoke`.

## Commands
* `uv run pytest -m "not aws_smoke and not browser and not slow"` - Default fast unit tests
* `./scripts/quality_gate.sh fast` - Fast pull-request development gate (no slow tests, no integration, no browser)
* `./scripts/quality_gate.sh full` - Full CI/CD quality gate
* `npm run test` (in frontend) - Frontend Vitest tests

## Flaky-Test Policy
A flaky test is considered a defect. Do NOT automatically rerun tests to hide flakiness. Flakes (especially around concurrency and messaging delivery) must be isolated, fixed, and repeated locally `10x` to verify stability before merging.

## Quality Gates & Coverage
Quality gates are executed via `scripts/quality_gate.sh`. The gate enforces:
1. Syntax/Compilation
2. Formatting
3. Linting
4. Fast Tests
5. Minimum test coverage
Coverage is diagnostic; the goal is protecting invariants, but a 40% absolute floor is enforced to avoid systemic regressions.
