# CI/CD Pipeline & Automated Deployment (Phase 28)

## Overview
FloodGuard uses GitHub Actions for continuous integration and continuous deployment. The pipeline is split into distinct workflows to maintain clear separation of responsibilities:
1. **Quality Gate** (`quality.yml`): Fast automated tests, formatting, and linting.
2. **Container Build & Scan** (`container-build.yml`): Building production images, SBOM generation, and vulnerability scanning.
3. **Terraform Validation** (`terraform.yml`): Formatting and static validation of Terraform configurations.
4. **Deploy to Development** (`deploy-dev.yml`): Manual, approved deployment to the development environment.

## Trigger Behavior
- **Push & Pull Requests (`main`)**: Triggers the `Quality Gate`, `Container Build`, and `Terraform Validation` workflows. This ensures code is linted, tested, and can be containerized, but does not deploy anything.
- **Manual Dispatch (`workflow_dispatch`)**: Triggers the `Deploy to Development` workflow. It requires specifying a commit SHA to deploy and explicitly opting into Terraform infrastructure deployment.

## AWS OIDC Authentication
We use GitHub Actions OpenID Connect (OIDC) to assume an AWS IAM Role (`github-actions-dev-role`) dynamically, without needing long-lived AWS credentials stored as GitHub Secrets.
**Prerequisites:**
- The AWS account must have a GitHub OIDC Identity Provider configured.
- The `github-actions-dev-role` must be created, establishing a trust relationship with the GitHub repository and scoping the Subject claim (`sub`) to specific branches or environments.
*Note: As of Phase 28, AWS credentials and OIDC roles are not yet provisioned. Deployment steps are marked BLOCKED.*

## Build, Scan, and ECR Stages
The container build workflow uses Docker BuildKit to build production images using `backend/Dockerfile.prod` and `frontend/Dockerfile.prod`. We use `aquasecurity/trivy-action` to scan the images for critical vulnerabilities. The scanner is configured to fail the workflow if an exploitable critical vulnerability is found.

Images are published to Amazon ECR. Each image is tagged immutably with the Git SHA (`${{ github.sha }}`) to guarantee traceablility.

## Terraform Validation and Planning
The `terraform.yml` workflow enforces formatting (`terraform fmt -check`) and validates syntax without applying changes.
The deployment workflow generates a Terraform plan (`terraform plan`) and, if approved by the deployer via the input prompt, applies it (`terraform apply`). The state remains securely managed by an S3 backend.

## Development Deployment & Rollback
Deployment is handled exclusively by `deploy-dev.yml`.
- The pipeline assumes the IAM role and validates credentials.
- It pushes the immutable container images.
- It runs database migrations via an explicit ECS Task using `alembic upgrade head`.
- Once migrated, it updates the ECS services for frontend and backend to use the new image.
- It monitors the deployment health until the tasks stabilize.
- Finally, it executes the smoke test suite.

### Rollback
To rollback, trigger the `Deploy to Development` workflow and provide the `version_sha` of the previously known-good deployment.
- Re-deploying an older SHA restores the old frontend and backend images.
- Database migrations are *not* automatically rolled back. Schema changes are backward compatible by design. If a schema rollback is strictly necessary, it requires manual database intervention.

## Secrets and Environment Protection
- No AWS access keys are committed.
- Task Definitions use AWS Secrets Manager and Parameter Store ARNs; the ECS tasks themselves resolve the secrets at runtime.
- The CI pipeline does not echo or log secrets.

## Known Limitations
- **OIDC/Deployment Blocker:** AWS credentials are not configured, so ECR pushes, Terraform plans, ECS updates, and Smoke Tests are blocked from fully executing. They exist as mock commands in the CI workflow.
- **Production Scope:** There is no production deployment configured. The workflows only target `dev`.

