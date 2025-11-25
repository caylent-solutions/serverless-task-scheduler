#!/bin/bash
set -e

#############################################################################
# Deploy Script for Sample ECS Task (Calculator)
#
# This script:
# 1. Creates/updates ECR repository
# 2. Builds Docker image from lambda_handler_calculator.py
# 3. Pushes image to ECR
# 4. Deploys ECS Task Definition and Cluster using SAM
# 5. Outputs the Task ARN and sample configuration for Serverless Task Scheduler
#############################################################################

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values - should match your main samconfig.toml
STACK_NAME="${STACK_NAME:-calculator-ecs-task}"
AWS_REGION="${AWS_REGION:-us-east-2}"
CLUSTER_NAME="${CLUSTER_NAME:-serverless-task-scheduler-cluster}"

# Required parameters - Caylent tagging requirements
OWNER="${OWNER:-}"
ENVIRONMENT="${ENVIRONMENT:-dev}"

# Optional parameters
VPC_ID="${VPC_ID:-}"
SUBNET_IDS="${SUBNET_IDS:-}"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ECS Calculator Task Deployment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI is not installed${NC}"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed${NC}"
    exit 1
fi

if ! command -v sam &> /dev/null; then
    echo -e "${RED}Error: SAM CLI is not installed${NC}"
    exit 1
fi

# Validate required parameters
if [ -z "$OWNER" ]; then
    echo -e "${RED}Error: OWNER environment variable is required (e.g., your.email@caylent.com)${NC}"
    echo -e "${YELLOW}Usage: OWNER=\"your.email@caylent.com\" ./deploy.sh${NC}"
    exit 1
fi

# Get AWS Account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo -e "${RED}Error: Unable to get AWS Account ID. Check your AWS credentials.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ AWS Account ID: ${AWS_ACCOUNT_ID}${NC}"
echo -e "${GREEN}✓ AWS Region: ${AWS_REGION}${NC}"
echo -e "${GREEN}✓ Owner: ${OWNER}${NC}"
echo -e "${GREEN}✓ Environment: ${ENVIRONMENT}${NC}"
echo ""

# Step 1: Deploy CloudFormation stack to create ECR repository
echo -e "${BLUE}Step 1: Creating ECR repository...${NC}"

# First deploy with placeholder image to create repository
sam deploy \
    --template-file template.yaml \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --parameter-overrides \
        "ImageUri=public.ecr.aws/lambda/python:3.13" \
        "ClusterName=${CLUSTER_NAME}" \
        "VpcId=${VPC_ID}" \
        "SubnetIds=${SUBNET_IDS}" \
        "Owner=${OWNER}" \
        "Environment=${ENVIRONMENT}" \
    --capabilities CAPABILITY_IAM \
    --tags "caylent:owner=${OWNER}" "caylent:env=${ENVIRONMENT}" \
    --no-fail-on-empty-changeset

# Get repository URI
REPOSITORY_URI=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='RepositoryUri'].OutputValue" \
    --output text)

if [ -z "$REPOSITORY_URI" ]; then
    echo -e "${RED}Error: Could not retrieve ECR repository URI${NC}"
    exit 1
fi

echo -e "${GREEN}✓ ECR Repository: ${REPOSITORY_URI}${NC}"
echo ""

# Step 2: Build Docker image
echo -e "${BLUE}Step 2: Building Docker image...${NC}"

IMAGE_TAG="latest"
FULL_IMAGE_URI="${REPOSITORY_URI}:${IMAGE_TAG}"

docker build -t "${FULL_IMAGE_URI}" .

if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Docker build failed${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Docker image built: ${FULL_IMAGE_URI}${NC}"
echo ""

# Step 3: Push image to ECR
echo -e "${BLUE}Step 3: Pushing image to ECR...${NC}"

# Login to ECR
aws ecr get-login-password --region "${AWS_REGION}" | \
    docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

if [ $? -ne 0 ]; then
    echo -e "${RED}Error: ECR login failed${NC}"
    exit 1
fi

# Push image
docker push "${FULL_IMAGE_URI}"

if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Docker push failed${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Image pushed to ECR${NC}"
echo ""

# Step 4: Update stack with real image URI
echo -e "${BLUE}Step 4: Updating ECS Task Definition with new image...${NC}"

sam deploy \
    --template-file template.yaml \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --parameter-overrides \
        "ImageUri=${FULL_IMAGE_URI}" \
        "ClusterName=${CLUSTER_NAME}" \
        "VpcId=${VPC_ID}" \
        "SubnetIds=${SUBNET_IDS}" \
        "Owner=${OWNER}" \
        "Environment=${ENVIRONMENT}" \
    --capabilities CAPABILITY_IAM \
    --tags "caylent:owner=${OWNER}" "caylent:env=${ENVIRONMENT}" \
    --no-fail-on-empty-changeset

echo -e "${GREEN}✓ Stack deployed successfully${NC}"
echo ""

# Step 5: Get outputs
echo -e "${BLUE}Step 5: Retrieving stack outputs...${NC}"
echo ""

TASK_DEFINITION_ARN=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='TaskDefinitionArn'].OutputValue" \
    --output text)

CLUSTER_ARN=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='ClusterArn'].OutputValue" \
    --output text)

SECURITY_GROUP_ID=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='TaskSecurityGroupId'].OutputValue" \
    --output text)

# Display results
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}Stack Details:${NC}"
echo "  Stack Name: ${STACK_NAME}"
echo "  Region: ${AWS_REGION}"
echo "  Cluster ARN: ${CLUSTER_ARN}"
echo "  Task Definition ARN: ${TASK_DEFINITION_ARN}"
echo "  Image URI: ${FULL_IMAGE_URI}"
if [ -n "$VPC_ID" ] && [ "$SECURITY_GROUP_ID" != "N/A - No VPC provided" ]; then
    echo "  Security Group: ${SECURITY_GROUP_ID}"
fi
echo ""

# Generate sample configuration
echo -e "${BLUE}Sample Target Configuration for Serverless Task Scheduler:${NC}"
echo ""

if [ -n "$VPC_ID" ] && [ -n "$SUBNET_IDS" ]; then
    # Parse subnet IDs
    IFS=',' read -ra SUBNET_ARRAY <<< "$SUBNET_IDS"
    SUBNET_JSON=$(printf ',"%s"' "${SUBNET_ARRAY[@]}")
    SUBNET_JSON="[${SUBNET_JSON:1}]"

    cat << EOF
{
  "target_type": "ecs",
  "target_alias": "calculator-ecs",
  "target_config": {
    "cluster": "${CLUSTER_ARN}",
    "task_definition": "${TASK_DEFINITION_ARN}",
    "launch_type": "FARGATE",
    "container_name": "calculator",
    "network_configuration": {
      "awsvpcConfiguration": {
        "subnets": ${SUBNET_JSON},
        "securityGroups": ["${SECURITY_GROUP_ID}"],
        "assignPublicIp": "ENABLED"
      }
    }
  }
}
EOF
else
    echo -e "${YELLOW}Note: VPC and Subnet configuration not provided.${NC}"
    echo -e "${YELLOW}You'll need to add network_configuration when creating the target.${NC}"
    echo ""
    cat << EOF
{
  "target_type": "ecs",
  "target_alias": "calculator-ecs",
  "target_config": {
    "cluster": "${CLUSTER_ARN}",
    "task_definition": "${TASK_DEFINITION_ARN}",
    "launch_type": "FARGATE",
    "container_name": "calculator",
    "network_configuration": {
      "awsvpcConfiguration": {
        "subnets": ["subnet-xxxxx", "subnet-yyyyy"],
        "securityGroups": ["sg-xxxxx"],
        "assignPublicIp": "ENABLED"
      }
    }
  }
}
EOF
fi

echo ""
echo -e "${BLUE}Sample Input Payload (same format as Lambda):${NC}"
cat << EOF
{
  "action": "add",
  "x": 5,
  "y": 3
}
EOF

echo ""
echo -e "${GREEN}Deployment Parameters Used:${NC}"
echo "  Owner: ${OWNER}"
echo "  Environment: ${ENVIRONMENT}"
echo "  Stack Name: ${STACK_NAME}"
echo ""
echo -e "${GREEN}Next Steps:${NC}"
echo "1. Register this ECS task as a target in your Serverless Task Scheduler"
echo "2. Create a schedule that uses the target_alias 'calculator-ecs'"
echo "3. The ECS task will receive the payload via EXECUTION_PAYLOAD environment variable"
echo "4. Results will be sent back via Step Functions task token callback"
echo ""
echo -e "${BLUE}To test manually:${NC}"
echo "aws ecs run-task \\"
echo "  --cluster ${CLUSTER_ARN} \\"
echo "  --task-definition ${TASK_DEFINITION_ARN} \\"
echo "  --launch-type FARGATE \\"
if [ -n "$VPC_ID" ] && [ -n "$SUBNET_IDS" ]; then
    echo "  --network-configuration 'awsvpcConfiguration={subnets=[${SUBNET_IDS}],securityGroups=[${SECURITY_GROUP_ID}],assignPublicIp=ENABLED}' \\"
fi
echo "  --overrides '{\"containerOverrides\":[{\"name\":\"calculator\",\"environment\":[{\"name\":\"EXECUTION_PAYLOAD\",\"value\":\"{\\\"action\\\":\\\"add\\\",\\\"x\\\":5,\\\"y\\\":3}\"}]}]}'"
echo ""
