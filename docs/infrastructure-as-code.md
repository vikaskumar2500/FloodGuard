# Infrastructure as Code (Phase 26)

## Overview
Phase 26 defines the AWS Infrastructure as Code (IaC) for FloodGuard using Terraform. It establishes an automated, secure, and reproducible path to cloud deployment while preserving the existing local Docker Compose environment.

## Terraform Architecture
The infrastructure is organized into a main directory (`infra/terraform`) containing:
1. **Modules**: Logical reusable components (networking, security, database, redis, messaging, ecr, ecs, artifacts, observability, iam).
2. **Environments**: Isolated environments (dev, staging, prod) instantiated from the modules to guarantee structural consistency without cross-environment contamination.

## Environment Strategy
- **dev**: The primary environment for testing deployments. Operates with scaled-down resources (`t4g.micro`, minimal compute).
- **staging/prod**: Skeletons exist but are not provisioned automatically. Production applies must require strict approval workflows (to be implemented in Phase 28).

## Components
### Networking
- Configured a VPC with public and private subnets across multiple AZs.
- Features an Internet Gateway for public access via the ALB, and a NAT Gateway to permit private application tasks to pull images and access AWS APIs securely.

### Compute (ECS and ECR)
- **ECR**: Repositories for frontend and backend, with push-on-scan enabled.
- **ECS**: Fargate cluster running the FastAPI backend and Next.js frontend.
- **Scaling constraint**: The backend relies on process-local state (`ActiveRouteRegistry`, `RuntimeRiskState`). Therefore, desired count is restricted to `1` by default to avoid inconsistencies across replicas. A distributed registry (e.g., Redis PubSub or similar) is required before enabling autoscaling.

### Database (Amazon RDS PostgreSQL)
- Runs PostgreSQL version 16, which is PostGIS-compatible.
- Placed in private subnets, only accessible by the backend security group.
- Credentials generated dynamically via AWS Secrets Manager.

### Cache (ElastiCache Redis)
- Runs Redis 7.1 in private subnets.
- Only accessible by the backend security group.

### Messaging (SQS & EventBridge)
- EventBridge custom bus `floodguard-dev-events` routes observations and domain events to the primary SQS queue.
- Configured a Dead Letter Queue (DLQ) matching Phase 14-16 parameters (3 retries).

### Storage & AI (S3 & Bedrock)
- **S3 Artifacts**: A strictly private S3 bucket tracks datasets, simulations, and ML model artifacts. Versioning is enabled, and public access is entirely blocked.
- **IAM**: Backend tasks assume an ECS task role explicitly granted `s3:GetObject` on the artifact bucket, `sqs:ReceiveMessage` on the queue, and `bedrock:InvokeModel` (if AI features are enabled).

### Security
- **Least Privilege**: Application runtime roles and task execution roles are strictly separated. The application only possesses permissions for services it explicitly communicates with.
- **Secrets Management**: All sensitive data (like the DB password) is provisioned via AWS Secrets Manager. No passwords reside in Terraform code or state outputs.

## Validation & Workflow
1. Initializing dev: `terraform init`
2. Validating config: `terraform validate`
3. Plan generation: `terraform plan` (BLOCKED locally if AWS credentials are not configured).

## Known Limitations
- Application container sizes, exact startup times, and vulnerability scans remain unmeasured due to local machine capacity exhaustion in Phase 25.
- HTTPS/TLS requires an explicit ACM certificate and valid domain name, both of which have not been supplied in the baseline dev template.
- Application DB migrations (Alembic + PostGIS extension creation) must be executed manually against the RDS instance post-deployment or via a separate automated CD step.

