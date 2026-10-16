#!/bin/bash
set -e

echo "Initializing LocalStack AWS resources for FloodGuard..."

awslocal sqs create-queue --queue-name floodguard-environment-events --region ap-south-1 || true
awslocal sqs create-queue --queue-name floodguard-events-standard --region ap-south-1 || true
awslocal events create-event-bus --name floodguard-dev-events --region ap-south-1 || true
awslocal s3 mb s3://floodguard-artifacts-dev --region ap-south-1 || true

QUEUE_ARN=$(awslocal sqs get-queue-attributes \
  --queue-url http://localhost:4566/000000000000/floodguard-environment-events \
  --attribute-names QueueArn \
  --region ap-south-1 \
  --query "Attributes.QueueArn" \
  --output text)

awslocal events put-rule \
  --name route-all-to-sqs \
  --event-bus-name floodguard-dev-events \
  --event-pattern '{"source": ["com.floodguard"]}' \
  --region ap-south-1 || true

awslocal events put-targets \
  --rule route-all-to-sqs \
  --event-bus-name floodguard-dev-events \
  --targets "Id"="1","Arn"="$QUEUE_ARN" \
  --region ap-south-1 || true

echo "LocalStack FloodGuard AWS resources successfully initialized!"

