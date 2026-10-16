# AWS Bootstrap Prerequisites

The `aws` CLI is currently not installed, and no AWS credentials are provided. To unblock the AWS Development Deployment (Phase 28/29 onwards), the following bootstrap prerequisites must be met:

## 1. Install AWS CLI & Terraform
Install the necessary infrastructure tools on your local development machine:
- **macOS:** 
  ```sh
  brew install awscli hashicorp/tap/terraform
  ```
- **Linux:** 
  ```sh
  # Install AWS CLI
  curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && unzip awscliv2.zip && sudo ./aws/install
  
  # Install Terraform
  wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
  echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
  sudo apt update && sudo apt install terraform
  ```

## 2. Configure AWS Credentials
Run `aws configure` to securely set up your development credentials. This should correspond to a user with permissions to bootstrap an AWS OIDC provider and deploy IAM roles.
Alternatively, set the following environment variables (do NOT commit these or paste them in chat):
```sh
export AWS_ACCESS_KEY_ID="your_access_key"
export AWS_SECRET_ACCESS_KEY="your_secret_key"
export AWS_REGION="us-east-1"
```

## 3. GitHub OIDC Provider & Role
Before GitHub Actions can deploy FloodGuard, an OIDC provider must be created in your AWS account.
1. Create an Identity Provider in AWS IAM for `token.actions.githubusercontent.com`.
2. Create an IAM Role (e.g., `github-actions-dev-role`) and attach the necessary deployment permissions (ECS, ECR, RDS, ElastiCache, S3).
3. Set the Trust Policy of the role to allow `sts:AssumeRoleWithWebIdentity` only for your specific GitHub repository and the `dev` environment.

Once these prerequisites are met, Terraform can be applied live, and the GitHub deployment workflow can succeed.
