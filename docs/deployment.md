# Deployment Guide

## Pre-Deployment Checklist
1. **AWS Credentials**: Must be explicitly supplied (e.g., via `aws configure` or CI/CD secrets).
2. **Container Images**: The backend and frontend must be fully built and tested on a CI runner with sufficient disk capacity.
3. **Secrets**: 
   - Ensure the Secrets Manager contains a valid password for PostgreSQL.
   - JWT singing secrets, if any, should be injected via environment configurations.
4. **Database Initialization**: 
   - PostGIS extension must be explicitly created (`CREATE EXTENSION postgis;`).
   - Run `alembic upgrade head` against the private RDS endpoint using an authorized bastion host or ECS task.
5. **Cost Drivers**: Idle Fargate tasks, NAT Gateways (in dev), ElastiCache Redis, and RDS PostgreSQL. 

## Pushing to ECR
1. Obtain the login token: `aws ecr get-login-password --region [REGION] | docker login --username AWS --password-stdin [ACCOUNT_ID].dkr.ecr.[REGION].amazonaws.com`
2. Tag appropriately: `docker tag floodguard-backend:prod [ACCOUNT_ID].dkr.ecr.[REGION].amazonaws.com/floodguard-dev-backend:[COMMIT_SHA]`
3. Push: `docker push [ACCOUNT_ID].dkr.ecr.[REGION].amazonaws.com/floodguard-dev-backend:[COMMIT_SHA]`

## Terraform Application
```bash
cd infra/terraform/environments/dev
terraform init
terraform plan -out=tfplan
terraform apply "tfplan"
```

## Runtime Configuration Mapping
- `DATABASE_URL` -> Resolved using the RDS endpoint output + the Secret Manager string.
- `REDIS_URL` -> Resolved using the ElastiCache primary endpoint.
- `SQS_ENVIRONMENT_QUEUE_URL` -> Extracted from Terraform outputs.
- `EVENTBRIDGE_BUS_NAME` -> Extracted from Terraform outputs.
- `NEXT_PUBLIC_API_BASE_URL` -> Relative path routing via the ALB (requests forwarded to `/api/v1`).


## AWS Bootstrap & Current Status (Local Verification only)
- AWS CLI is not installed.
- Terraform is not installed.
- Vulnerability scanner (Trivy) is not installed.
All AWS deployment steps (Terraform plan/apply, ECS rollout, Database migrations) are currently BLOCKED pending credentials.
