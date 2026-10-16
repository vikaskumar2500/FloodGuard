# Production Readiness Guidelines

This document outlines the requirements and release gates that FloodGuard must pass before any promotion to Production.

## Release Gates

### Gate A: Source and Static Quality
- Passes syntax checks (`python -m compileall`).
- Passes backend linting and formatting (`ruff check` and `ruff format`).
- Passes frontend linting (`eslint`) and formatting (`prettier`).
- Passes frontend type checking (`tsc --noEmit`).
- Terraform is formatted (`terraform fmt`) and structurally valid (`terraform validate`).
- No secrets are exposed in code.

### Gate B: Automated Correctness
- Unit test suites (Frontend and Backend) pass successfully.
- Security tests confirm password hashing and RBAC.
- Contract tests for ML Model data passing confirm structural integrity.
- ML models correctly gracefully fallback to Deterministic bounds on failure.

### Gate C: Build and Supply Chain
- `Dockerfile.prod` produces immutable images tagged with the exact Git SHA.
- `trivy` container scanning results in zero CRITICAL exploitable vulnerabilities.
- SBOMs are generated and uploaded as workflow artifacts.

### Gate D: Infrastructure
- `terraform plan` produces a predictable output with no unauthorized destructive actions.
- Least Privilege IAM roles are strictly enforced.
- Network exposure correctly utilizes private subnets for RDS and ElastiCache.
- HTTPS configuration verified; ALB drops raw HTTP traffic securely.

### Gate E: Deployed Runtime
- ALB successfully routes traffic to ECS services.
- The `health` endpoints reflect dependencies (PostgreSQL/Redis) accurately.
- SSE broadcast endpoints securely authenticate the client.
- `alembic` migrations successfully bootstrap the live database.
- Browser E2E/Smoke Tests pass against the live AWS endpoint.

### Gate F: Operational Recovery
- Automated deployments safely rollback upon failing a health check.
- SQS Poison Messages correctly land in a Dead Letter Queue (DLQ).
- Redis cached states handle expiration natively and do not stall the API.
- RDS Point-In-Time recovery is functional.
- Runbooks are followed for disaster recovery.

## Security Posture
- GitHub Actions dynamically assumes an OIDC role to prevent token leakage.
- Database Credentials, JWT Secrets, and API Keys reside in AWS Secrets Manager.
- Frontend CORS only permits configured domains.
- Incident reports have rate limits and verification logic.

## Accepted Limitations
- **ML Synthetic Constraint:** The ML evaluation pipeline uses synthetic data. Model inferences are accurate based on simulations but require a phase of "Shadow" mode using live historical data to validate real-world physics.
- **Process-Local State:** SSE clients currently tie to specific backend ECS processes. The service shouldn't scale horizontally (>1 instance) without an external Redis pub/sub mechanism implemented.

## Deployment Prerequisites
- **Staging Prerequisites:** AWS credentials provided, `dev` environment thoroughly vetted.
- **Production Prerequisites:** ACM Certificates bound to the domain name, RDS instances scaled out, multi-region/AZ configured, and full disaster recovery drills verified.

## Release Approval Process
1. A Pull Request validates Gate A, B, and C.
2. The PR is reviewed and merged to `main`.
3. An operator triggers `Deploy to Development` (validates Gate D and E).
4. QA and Engineering verify Gate F operations in Development.
5. Explicit GitHub Environment approval grants Staging deployment.
6. Only after Staging is verified is a Production deployment formally scheduled.

