# Threat Model

## Assets
- User Credentials (passwords, tokens)
- Incident Data (reports, verification status)
- Routing Navigation State
- AWS Cloud Resources (SQS, EventBridge, Bedrock, S3)
- ML Models / Artifacts

## Trust Boundaries
- Public Internet <-> FastAPI App
- FastAPI App <-> Postgres Database
- FastAPI App <-> AWS Services

## Attackers
- Unauthenticated Internet users
- Authenticated Users attempting privilege escalation
- Malicious actors attempting to flood the system with fake incidents

## Threats & Mitigations (STRIDE)
1. **Spoofing**: Addressed via JWT Bearer Tokens.
2. **Tampering**: Addressed via signed JWTs (HS256) and TLS (Strict-Transport-Security in prod).
3. **Repudiation**: Privileged actions (like DLQ replay, moderation) can be logged with actor ID.
4. **Information Disclosure**: Secrets redacted from logs, SSE routes protected, CORS restrictive, security headers (nosniff) in place.
5. **Denial of Service**: Token bucket rate limiting added for login, incident submission, assistant queries, and routing.
6. **Elevation of Privilege**: Role-based Access Control (RBAC) enforces explicit permissions (e.g. `require_permission`).

## Residual Risks
- Redis unavailability causing degraded rate-limiting.
- Secrets currently in environment variables (may need AWS Secrets Manager later).
