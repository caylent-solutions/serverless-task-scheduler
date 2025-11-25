# Sample ECS Task for Serverless Task Scheduler

This directory contains a sample ECS Fargate task that demonstrates how to create container-based workloads compatible with the Serverless Task Scheduler. The task implements a simple calculator that accepts input in the same JSON format as Lambda functions.

## Overview

The sample demonstrates:
- **Lambda-compatible input format**: Accepts JSON payload via `EXECUTION_PAYLOAD` environment variable
- **Step Function task token callback**: Uses `waitForTaskToken` pattern to pass results directly to downstream states
- **Container wrapper pattern**: Shows how to adapt any application to work with the scheduler

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Step Function (ExecutorStepFunction)                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Preprocessing                                           │
│     └─> Merges payload with target configuration           │
│                                                             │
│  2. ExecuteECSTarget                                        │
│     └─> ecs:runTask.waitForTaskToken                       │
│         ├─> Passes TASK_TOKEN to container                 │
│         └─> Waits for callback                             │
│                                                             │
│  3. ECS Task Execution                                      │
│     ├─> entrypoint.py reads TASK_TOKEN env var            │
│     ├─> Reads EXECUTION_PAYLOAD env var                    │
│     ├─> Parses JSON and calls lambda_handler_calculator.py │
│     ├─> Sends result via SendTaskSuccess callback          │
│     └─> Logs to CloudWatch                                 │
│                                                             │
│  4. Result returned to Step Function                        │
│     └─> Available in $.execution_result for downstream     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Files

- **`lambda_handler_calculator.py`**: The actual calculator logic (Lambda handler format)
- **`entrypoint.py`**: Container wrapper that:
  - Reads `TASK_TOKEN` environment variable (for Step Functions callback)
  - Reads `EXECUTION_PAYLOAD` environment variable
  - Invokes the Lambda handler with the payload
  - Sends result to Step Functions via `SendTaskSuccess`/`SendTaskFailure`
  - Outputs JSON result to stdout (for logging)
  - Provides Lambda-compatible context object
- **`Dockerfile`**: Builds container image using AWS Lambda base image
- **`template.yaml`**: SAM template that creates:
  - ECR repository
  - ECS cluster
  - ECS task definition
  - IAM roles
  - CloudWatch log group
  - Security group (if VPC provided)
- **`deploy.sh`**: Automated deployment script

## Prerequisites

- AWS CLI configured with appropriate credentials
- Docker installed and running
- SAM CLI installed (`pip install aws-sam-cli`)
- Appropriate AWS permissions for:
  - ECR (create repository, push images)
  - ECS (create cluster, task definitions)
  - IAM (create roles)
  - CloudFormation (deploy stacks)
  - CloudWatch Logs (create log groups)
  - Step Functions (SendTaskSuccess, SendTaskFailure - for task callbacks)

## Deployment

### Basic Deployment (without VPC)

**Required: Set OWNER environment variable** (Caylent tagging requirement)

```bash
cd sample-ecs-task
export OWNER="your.email@caylent.com"
./deploy.sh
```

### Deployment with VPC Configuration

```bash
export OWNER="your.email@caylent.com"
export VPC_ID="vpc-xxxxxxxxx"
export SUBNET_IDS="subnet-xxxxx,subnet-yyyyy"
./deploy.sh
```

### Custom Parameters

```bash
export OWNER="your.email@caylent.com"
export ENVIRONMENT="dev"  # or staging, prod
export AWS_REGION="us-east-2"  # default matches main project
export STACK_NAME="calculator-ecs-task"
export CLUSTER_NAME="serverless-task-scheduler-cluster"
export VPC_ID="vpc-xxxxxxxxx"
export SUBNET_IDS="subnet-xxxxx,subnet-yyyyy"
./deploy.sh
```

**Note:** The default AWS region is `us-east-2` to match the main Serverless Task Scheduler project configuration.

## What the Deploy Script Does

1. **Creates ECR Repository**: Sets up a private ECR repository for the calculator image
2. **Builds Docker Image**: Packages the calculator code and entrypoint into a container
3. **Pushes to ECR**: Uploads the image to your ECR repository
4. **Creates ECS Resources**: Deploys cluster, task definition, IAM roles, and logging
5. **Outputs Configuration**: Provides the exact JSON needed to register with the scheduler

## Integration with Serverless Task Scheduler

After deployment, register the ECS task as a target:

```json
{
  "target_type": "ecs",
  "target_alias": "calculator-ecs",
  "target_config": {
    "cluster": "arn:aws:ecs:us-east-1:123456789012:cluster/serverless-task-scheduler-cluster",
    "task_definition": "arn:aws:ecs:us-east-1:123456789012:task-definition/calculator-task:1",
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
```

## Input Format

The ECS task accepts the same input format as the Lambda version:

```json
{
  "action": "add",
  "x": 5,
  "y": 3
}
```

Supported actions:
- `add`: Addition
- `subtract`: Subtraction
- `multiply`: Multiplication
- `divide`: Division

## Output Format

The task sends results directly to Step Functions via the task token callback and also logs to stdout.

### Success Response (sent via SendTaskSuccess):

```json
{
  "status": "success",
  "result": {
    "result": 8
  },
  "execution_id": "ecs-task-2025-11-25T10:30:00.000000",
  "timestamp": "2025-11-25T10:30:05.123456"
}
```

This result becomes available in the Step Function state as `$.execution_result` and can be accessed by downstream states.

### Error Response (sent via SendTaskFailure):

```json
{
  "error": "TaskExecutionError",
  "cause": "Division by zero"
}
```

### How Task Token Callback Works

1. **Step Functions** passes `$$.Task.Token` to the ECS task via the `TASK_TOKEN` environment variable
2. **ECS Task** executes the workload and captures the result
3. **ECS Task** calls `boto3.client('stepfunctions').send_task_success()` with:
   - `taskToken`: The token received from the environment variable
   - `output`: JSON string of the result
4. **Step Functions** receives the result and makes it available to downstream states in `$.execution_result`

This pattern allows ECS task output to flow directly into the Step Function's state, unlike the `.sync` pattern which only provides task metadata (exit code, status, etc.).

## Testing

### Test via AWS CLI

```bash
aws ecs run-task \
  --cluster arn:aws:ecs:us-east-1:123456789012:cluster/serverless-task-scheduler-cluster \
  --task-definition arn:aws:ecs:us-east-1:123456789012:task-definition/calculator-task:1 \
  --launch-type FARGATE \
  --network-configuration 'awsvpcConfiguration={subnets=[subnet-xxxxx],securityGroups=[sg-xxxxx],assignPublicIp=ENABLED}' \
  --overrides '{"containerOverrides":[{"name":"calculator","environment":[{"name":"EXECUTION_PAYLOAD","value":"{\"action\":\"add\",\"x\":5,\"y\":3}"}]}]}'
```

### Test via Serverless Task Scheduler

1. Register the ECS task as a target using the Targets API
2. Create a schedule that references the target alias
3. Trigger the schedule or wait for it to execute
4. View results in the execution history

## Monitoring

### CloudWatch Logs

Logs are sent to: `/ecs/calculator-task`

View logs:
```bash
aws logs tail /ecs/calculator-task --follow
```

### Task Execution

View running tasks:
```bash
aws ecs list-tasks --cluster serverless-task-scheduler-cluster
```

Describe a specific task:
```bash
aws ecs describe-tasks --cluster serverless-task-scheduler-cluster --tasks <task-id>
```

## Customization

### Adding Your Own Logic

1. Replace `lambda_handler_calculator.py` with your own Lambda handler
2. Ensure your handler follows the pattern: `def lambda_handler(event, context):`
3. Update the Dockerfile to copy any additional dependencies
4. Add required Python packages to a `requirements.txt` if needed:

```dockerfile
# In Dockerfile, add:
COPY requirements.txt .
RUN pip install -r requirements.txt --target "${LAMBDA_TASK_ROOT}"
```

### Modifying Container Resources

Edit `template.yaml` to adjust CPU and memory:

```yaml
CalculatorTaskDefinition:
  Type: AWS::ECS::TaskDefinition
  Properties:
    Cpu: '512'      # 0.5 vCPU
    Memory: '1024'  # 1 GB
```

### Adding Environment Variables

Modify the task definition in `template.yaml`:

```yaml
ContainerDefinitions:
  - Name: calculator
    Environment:
      - Name: MY_CUSTOM_VAR
        Value: my_value
```

## Cost Considerations

- **ECS Fargate**: Charged per vCPU and memory per second
  - 0.25 vCPU, 0.5 GB: ~$0.01 per task (1 minute execution)
- **ECR Storage**: ~$0.10/GB/month
- **CloudWatch Logs**: ~$0.50/GB ingested
- **Data Transfer**: Minimal for small payloads

For cost optimization:
- Use FARGATE_SPOT for non-critical workloads (70% discount)
- Set appropriate CloudWatch log retention (default: 7 days)
- Consider Lambda for tasks <15 minutes execution time

## Troubleshooting

### Image Build Fails

```bash
# Check Docker is running
docker ps

# Verify Dockerfile syntax
docker build -t test .
```

### Push to ECR Fails

```bash
# Re-authenticate
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com
```

### Task Fails to Start

1. Check CloudWatch logs: `/ecs/calculator-task`
2. Verify network configuration (subnets must have internet access or NAT gateway)
3. Check security group allows outbound traffic
4. Verify IAM roles have correct permissions

### Task Runs but No Output

1. Check the task stopped reason:
   ```bash
   aws ecs describe-tasks --cluster <cluster> --tasks <task-id>
   ```
2. Review CloudWatch logs for errors
3. Verify `EXECUTION_PAYLOAD` environment variable is being set

## Clean Up

To remove all resources:

```bash
# Delete the CloudFormation stack
aws cloudformation delete-stack --stack-name calculator-ecs-task

# Delete ECR images (optional - stack deletion removes repository)
aws ecr batch-delete-image \
  --repository-name serverless-task-scheduler/calculator \
  --image-ids imageTag=latest
```

## IAM Permissions

The ECS task requires two IAM roles:

### Task Execution Role
Used by ECS to pull images and write logs:
- `ecr:GetAuthorizationToken`
- `ecr:BatchCheckLayerAvailability`
- `ecr:GetDownloadUrlForLayer`
- `ecr:BatchGetImage`
- `logs:CreateLogStream`
- `logs:PutLogEvents`

### Task Role
Used by the application running inside the container:
- `logs:CreateLogStream` - Write application logs
- `logs:PutLogEvents` - Write application logs
- `states:SendTaskSuccess` - Send successful results to Step Functions
- `states:SendTaskFailure` - Send failure notifications to Step Functions
- `states:SendTaskHeartbeat` - Send heartbeats to prevent timeout (optional)

The template automatically creates both roles with the required permissions.

## Security Best Practices

1. **Use VPC**: Always deploy tasks in a VPC with private subnets
2. **Least Privilege IAM**: Task role has minimal permissions (logs + Step Functions callbacks only)
3. **Image Scanning**: ECR repository has scan-on-push enabled
4. **Secrets Management**: Use AWS Secrets Manager or Parameter Store for sensitive data:

```yaml
# In task definition
Secrets:
  - Name: DB_PASSWORD
    ValueFrom: arn:aws:secretsmanager:region:account:secret:db-password
```

5. **Task Token Security**: The task token is sensitive - never log it or expose it in error messages

## Additional Resources

- [ECS Fargate Documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html)
- [Step Functions ECS Integration](https://docs.aws.amazon.com/step-functions/latest/dg/connect-ecs.html)
- [Serverless Task Scheduler Documentation](../README.md)
