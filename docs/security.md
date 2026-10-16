# Security Architecture

## Authentication & Authorization
The application uses JWT Bearer Tokens for authentication.
- **Short-lived access tokens**: Default 60 minutes.
- **Role-based Access Control (RBAC)**: Users are mapped to roles (`USER`, `OPERATOR`, `ADMIN`, `SYSTEM`).
- **Permission Model**: FastAPI dependencies (`require_permission`, `require_role`) enforce granular permissions.
- **Password Hashing**: passlib with bcrypt.

## SSE Security
Server-Sent Events for live route updates require a short-lived SSE stream token.
- Users authenticate via `POST /api/v1/routes/{route_id}/stream-token` to receive a 5-minute scoped token.
- Subscriptions are then made to `GET /events?token=...`.
- Enforces user-ownership of the route.

## Rate Limiting
A token bucket rate limiter protects critical endpoints:
- Login: 5/min
- Incidents: 10/min
- Assistant: 20/min
- Routing: 60/min

## Security Headers & CORS
- Configured exact origins for CORS.
- Added `SecurityHeadersMiddleware` setting `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, and `X-Frame-Options`.

## Audit & Secrets
- Privileged operations (like DLQ replay) should be logged with actor ID.
- Passwords, AWS credentials, and JWT secrets are never logged.

## Known Limitations
- No automatic refresh tokens implemented (only access tokens).
- Secrets management uses env vars instead of AWS SSM.
- Internal service identity is loosely defined for workers.
