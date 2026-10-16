# Release Blockers

This document prioritizes gaps preventing a safe production release.

## 1. AWS OIDC Role Not Provisioned
- **Severity**: Critical Blocker
- **Category**: CI/CD Security & Access
- **Description**: The GitHub Actions OIDC provider and the corresponding deployment role (`github-actions-dev-role`) have not been created in AWS.
- **Evidence**: `deploy-dev.yml` uses this role, but it doesn't physically exist in any targeted account.
- **Impact**: Completely blocks ECR publishing, Terraform applying, and ECS application deployment.
- **Required Action**: Bootstrap AWS OIDC Provider and create the IAM Role with the appropriate trust policy.
- **Status**: OPEN
- **Blocking Gate**: Gate D (Infrastructure), Gate E (Deployed Runtime)

## 2. Terraform Live Deployment Not Verified
- **Severity**: Critical Blocker
- **Category**: Infrastructure
- **Description**: The terraform plan/apply lifecycle has only been statically analyzed (`validate`).
- **Evidence**: `infra/terraform/environments/dev/main.tf` has never executed.
- **Impact**: Cannot prove VPC, Security Groups, ALB, ECS, RDS, and ElastiCache provision safely.
- **Required Action**: Execute `terraform apply` using OIDC.
- **Status**: OPEN
- **Blocking Gate**: Gate D (Infrastructure)

## 3. ECS Application Deployment Not Verified
- **Severity**: Critical Blocker
- **Category**: Deployed Runtime
- **Description**: The application has never run on Amazon ECS Fargate.
- **Evidence**: Docker images built locally but haven't been pushed or executed in AWS.
- **Impact**: Cannot prove IAM Task/Execution roles are sufficient or that Secrets Manager integration resolves correctly at runtime.
- **Required Action**: Push to ECR, update ECS task, and verify service stability.
- **Status**: OPEN
- **Blocking Gate**: Gate E (Deployed Runtime)

## 4. Live RDS Initialization / Migration Not Verified
- **Severity**: Critical Blocker
- **Category**: Database
- **Description**: PostGIS extension installation and Alembic schema migrations haven't run against real AWS RDS PostgreSQL.
- **Evidence**: Local Docker Compose works, but the CI ECS RunTask step is commented/blocked out.
- **Impact**: Without migrations, the backend ECS tasks will instantly crash on boot.
- **Required Action**: Run the deployment pipeline's migration task.
- **Status**: OPEN
- **Blocking Gate**: Gate E (Deployed Runtime)

## 5. Live Application Rollback Untested
- **Severity**: High-priority Blocker
- **Category**: Operational Recovery
- **Description**: Restoring a previous application image version is documented but untested on real AWS API.
- **Evidence**: The pipeline rollback approach assumes `ecs update-service` works seamlessly, without DB conflicts.
- **Impact**: Cannot confidently revert an active incident.
- **Required Action**: Run a deployment, then intentionally trigger the workflow with the prior Git SHA and ensure health recovers.
- **Status**: OPEN
- **Blocking Gate**: Gate F (Operational Recovery)

## 6. End-to-End AWS Browser Smoke Tests Skipped
- **Severity**: High-priority Blocker
- **Category**: Deployed Runtime
- **Description**: Live interactions through ALB -> Frontend -> Backend (including SSE WebSockets) have not been checked.
- **Evidence**: Smoke tests currently mock out AWS or use `localhost`.
- **Impact**: Misconfigured AWS Target Groups, CORS origin mismatches, or Load Balancer drops could break the app silently.
- **Required Action**: Run `scripts/smoke_test.py` or equivalent browser E2E tests against the ALB DNS endpoint.
- **Status**: OPEN
- **Blocking Gate**: Gate E (Deployed Runtime)

