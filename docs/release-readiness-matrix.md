# Master Release Readiness Matrix (Phases 0–28)

| Area | Requirement | Evidence | Status | Severity | Required action | Release-blocking |
|---|---|---|---|---|---|---|
| Architecture and configuration | Valid system architecture, .env setup, config schemas | `app.core.config`, `docker-compose.yml`, Phase 0-1 verification | PASS | N/A | None | No |
| Application startup | Backend/Frontend load correctly | Local quality gate passing, `scripts/smoke_test.py` | PASS | N/A | None | No |
| Route calculation | A* / Dijkstra calculate optimal geometry/ETA | `tests/unit/test_routing.py`, Phase 5 | PASS | N/A | None | No |
| Risk engine | Deterministic bounds limit hazard severity | `tests/unit/test_risk.py`, Phase 6 | PASS | N/A | None | No |
| ML feature parity | Precomputed datasets isolate ML features | `floodguard_ml`, Phase 11-12 evaluation reports | PASS | N/A | None | No |
| ML deterministic fallback | Routing falls back if ML inference times out/errors | `tests/unit/test_ml_routing.py`, caching implementation | PASS | N/A | None | No |
| Environmental data | Ingestion via API to SQS, correctly parsed | `app.api.v1.environment`, Phase 10 | PASS | N/A | None | No |
| Realtime rerouting | SSE invalidates routes upon hazard changes | `lib/realtime/route-lifecycle.ts`, `tests/realtime.test.ts` | PASS | N/A | None | No |
| SSE | Broadcasts to authorized streams | `benchmark_sse.py`, frontend integrations | PASS | N/A | None | No |
| Redis cache | Routes cached to limit graph recalculation | Redis mocks in tests, `benchmark_cache.py` | PASS | N/A | None | No |
| Redis idempotency | SQS prevents repeated updates via leased keys | `app.messaging.sqs.consumer.py` locking tests | PASS | N/A | None | No |
| SQS | Publish/Subscribe reliably connects domains | `test_sqs_consumer.py`, mocked EventBridge | PASS | N/A | None | No |
| EventBridge | Domain fan-out functions properly | `test_eventbridge.py`, local memory tests | PASS | N/A | None | No |
| Retry/DLQ | Failed tasks move to DLQ, can be replayed | `app.messaging.dlq` CLI tools | PASS | N/A | None | No |
| S3 artifacts | Models/Datasets fetch smoothly, cache locally | `test_artifact_storage.py` | PASS | N/A | None | No |
| Bedrock assistant | AI resolves user intents using local tool calling | `test_assistant.py` (simulated tools) | PASS | N/A | None | No |
| Incident verification | Reports verified before adjusting routing | `tests/unit/test_incidents.py` | PASS | N/A | None | No |
| Authentication | JWT issuance, password hashing | `tests/security/test_auth.py` | PASS | N/A | None | No |
| Authorization | Role checks prevent unauthorized hazard updates | RBAC testing | PASS | N/A | None | No |
| Audit logging | Structured logging captures security events | `app.core.logging` JSON layout | PASS | N/A | None | No |
| Observability | Metrics and logs expose system health | Health endpoints, log schemas | PASS | N/A | None | No |
| Database migrations | Alembic tracks schema correctly | Migrations directory verified locally | PARTIAL | Medium | Live RDS test | Yes |
| PostGIS availability | OSM Graph loaded, coordinates calculate | Docker-compose PostGIS tests | PARTIAL | Medium | Live RDS test | Yes |
| Container images | Production Dockerfiles compile cleanly | GitHub workflow `container-build.yml` | PASS | N/A | None | No |
| Container scanning | Trivy action fails on CRITICAL vulns | GitHub workflow `container-build.yml` | PARTIAL | High | Needs live CI run | Yes |
| Terraform | Validates syntax | `terraform fmt`, `init`, `validate` | PASS | N/A | None | No |
| AWS OIDC | GitHub Actions safely assumes role | AWS Role missing | BLOCKED | Critical | Provision OIDC Provider | Yes |
| ECR | Images published | Missing creds | BLOCKED | Critical | Resolve OIDC | Yes |
| ECS | Task definitions update, stabilise | Missing creds/deployment | BLOCKED | Critical | Resolve OIDC | Yes |
| RDS | Live connection, TLS verified | Missing creds | BLOCKED | Critical | Resolve OIDC | Yes |
| ElastiCache | Live connection | Missing creds | BLOCKED | Critical | Resolve OIDC | Yes |
| Browser smoke tests | Runs against deployed ALB URL | Blocked on ECS deployment | BLOCKED | High | Resolve OIDC | Yes |
| Backup and recovery | Procedures documented/tested | Not verified on real RDS | PARTIAL | High | Verify AWS Backups | Yes |
| Rollback | Re-run deployment with old SHA | Defined in CI but untested | PARTIAL | High | Test AWS Rollback | Yes |
| Performance baselines | Benchmarks recorded | Local only | PARTIAL | Medium | Run against AWS | No |
| Operational readiness | Runbooks established | `docs/failure-recovery.md` | PASS | N/A | None | No |
| Cost controls | Infrastructure sized conservatively | `terraform.tfvars.example` | PASS | N/A | None | No |

