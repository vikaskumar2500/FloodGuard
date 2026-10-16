# Observability Architecture
- **Logs**: Structured JSON with PII/secret redaction.
- **Metrics**: Bounded cardinality, covering HTTP, Routing, ML, SQS.
- **Tracing**: Custom mock trace implementation simulating OpenTelemetry with correlation ID across services.
- **Health**: Split core vs degradable dependencies (`/api/v1/internal/health`).
