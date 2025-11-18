# Deployment Notes for ExecutorStepFunction

This document provides guidance for integrating ExecutorStepFunction into the SAM `template.yaml`.

## CloudFormation Resources to Add

### 1. Preprocessing Lambda

```yaml
PreprocessingLambda:
  Type: AWS::Serverless::Function
  Properties:
    FunctionName: !Sub ${StackName}-${Environment}-executor-preprocessing
    CodeUri: ExecutorStepFunction/
    Handler: preprocessing.handler
    Runtime: python3.13
    Timeout: 30
    Role: !GetAtt PreprocessingLambdaRole.Arn
    Environment:
      Variables:
        DYNAMODB_TABLE: !Sub ${StackName}-${Environment}-targets
        DYNAMODB_TENANT_TABLE: !Sub ${StackName}-${Environment}-tenant-mappings
        APP_ENV: !Ref Environment
```

### 2. Lambda Execution Helper Lambda

```yaml
LambdaExecutionHelperLambda:
  Type: AWS::Serverless::Function
  Properties:
    FunctionName: !Sub ${StackName}-${Environment}-executor-lambda-helper
    CodeUri: ExecutorStepFunction/
    Handler: lambda_execution_helper.handler
    Runtime: python3.13
    Timeout: 60  # Needs longer timeout for target Lambda execution
    Role: !GetAtt LambdaExecutionHelperRole.Arn
    Environment:
      Variables:
        APP_ENV: !Ref Environment
        AWS_REGION: !Ref AWS::Region
```

### 3. Postprocessing Lambda

```yaml
PostprocessingLambda:
  Type: AWS::Serverless::Function
  Properties:
    FunctionName: !Sub ${StackName}-${Environment}-executor-postprocessing
    CodeUri: ExecutorStepFunction/
    Handler: postprocessing.handler
    Runtime: python3.13
    Timeout: 30
    Role: !GetAtt PostprocessingLambdaRole.Arn
    Environment:
      Variables:
        DYNAMODB_EXECUTIONS_TABLE: !Sub ${StackName}-${Environment}-executions
        APP_ENV: !Ref Environment
```

### 4. Step Functions State Machine

```yaml
ExecutorStateMachine:
  Type: AWS::Serverless::StateMachine
  Properties:
    Name: !Sub ${StackName}-${Environment}-executor
    DefinitionUri: ExecutorStepFunction/state_machine.json
    DefinitionSubstitutions:
      PreprocessingLambdaArn: !GetAtt PreprocessingLambda.Arn
      LambdaExecutionHelperArn: !GetAtt LambdaExecutionHelperLambda.Arn
      PostprocessingLambdaArn: !GetAtt PostprocessingLambda.Arn
    Role: !GetAtt ExecutorStateMachineRole.Arn
    Type: STANDARD
    Tracing:
      Enabled: true
    Tags:
      caylent:owner: !Ref Owner
      caylent:env: !Ref Environment
      cfn:stack: !Ref StackName
```

## IAM Roles

### 1. Preprocessing Lambda Role

```yaml
PreprocessingLambdaRole:
  Type: AWS::IAM::Role
  Properties:
    RoleName: !Sub ${StackName}-${Environment}-preprocessing-${StackIdSuffix}
    AssumeRolePolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Principal:
            Service: lambda.amazonaws.com
          Action: sts:AssumeRole
    Policies:
      - PolicyName: PreprocessingPolicy
        PolicyDocument:
          Version: '2012-10-17'
          Statement:
            # DynamoDB read access
            - Effect: Allow
              Action:
                - dynamodb:GetItem
              Resource:
                - !GetAtt TargetsTable.Arn
                - !GetAtt TenantMappingsTable.Arn
    ManagedPolicyArns:
      - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

### 2. Lambda Execution Helper Role

```yaml
LambdaExecutionHelperRole:
  Type: AWS::IAM::Role
  Properties:
    RoleName: !Sub ${StackName}-${Environment}-lambda-helper-${StackIdSuffix}
    AssumeRolePolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Principal:
            Service: lambda.amazonaws.com
          Action: sts:AssumeRole
    Policies:
      - PolicyName: LambdaExecutionHelperPolicy
        PolicyDocument:
          Version: '2012-10-17'
          Statement:
            # Invoke target Lambda functions
            - Effect: Allow
              Action:
                - lambda:InvokeFunction
              Resource: '*'

            # CloudWatch Logs access to find log streams
            - Effect: Allow
              Action:
                - logs:DescribeLogStreams
                - logs:FilterLogEvents
              Resource: 'arn:aws:logs:*:*:log-group:/aws/lambda/*'
    ManagedPolicyArns:
      - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

### 3. Postprocessing Lambda Role

```yaml
PostprocessingLambdaRole:
  Type: AWS::IAM::Role
  Properties:
    RoleName: !Sub ${StackName}-${Environment}-postprocessing-${StackIdSuffix}
    AssumeRolePolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Principal:
            Service: lambda.amazonaws.com
          Action: sts:AssumeRole
    Policies:
      - PolicyName: PostprocessingPolicy
        PolicyDocument:
          Version: '2012-10-17'
          Statement:
            # DynamoDB write access to record executions
            - Effect: Allow
              Action:
                - dynamodb:PutItem
              Resource:
                - !GetAtt TargetExecutionsTable.Arn
    ManagedPolicyArns:
      - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

### 4. Step Functions State Machine Role

```yaml
ExecutorStateMachineRole:
  Type: AWS::IAM::Role
  Properties:
    RoleName: !Sub ${StackName}-${Environment}-sfn-executor-${StackIdSuffix}
    AssumeRolePolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Principal:
            Service: states.amazonaws.com
          Action: sts:AssumeRole
    Policies:
      - PolicyName: ExecutorStateMachinePolicy
        PolicyDocument:
          Version: '2012-10-17'
          Statement:
            # Invoke helper Lambda functions
            - Effect: Allow
              Action:
                - lambda:InvokeFunction
              Resource:
                - !GetAtt PreprocessingLambda.Arn
                - !GetAtt LambdaExecutionHelperLambda.Arn
                - !GetAtt PostprocessingLambda.Arn

            # ECS task execution (for ECS targets)
            - Effect: Allow
              Action:
                - ecs:RunTask
                - ecs:StopTask
                - ecs:DescribeTasks
              Resource: '*'

            # Step Functions execution (for nested Step Functions)
            - Effect: Allow
              Action:
                - states:StartExecution
                - states:DescribeExecution
                - states:StopExecution
              Resource: '*'

            # IAM PassRole for ECS tasks
            - Effect: Allow
              Action:
                - iam:PassRole
              Resource: '*'
              Condition:
                StringEquals:
                  iam:PassedToService: ecs-tasks.amazonaws.com

            # CloudWatch Logs for X-Ray
            - Effect: Allow
              Action:
                - logs:CreateLogDelivery
                - logs:GetLogDelivery
                - logs:UpdateLogDelivery
                - logs:DeleteLogDelivery
                - logs:ListLogDeliveries
                - logs:PutResourcePolicy
                - logs:DescribeResourcePolicies
                - logs:DescribeLogGroups
              Resource: '*'

            # X-Ray tracing
            - Effect: Allow
              Action:
                - xray:PutTraceSegments
                - xray:PutTelemetryRecords
                - xray:GetSamplingRules
                - xray:GetSamplingTargets
              Resource: '*'
    Tags:
      - Key: caylent:owner
        Value: !Ref Owner
      - Key: caylent:env
        Value: !Ref Environment
```

## EventBridge Scheduler Integration

### Update EventBridgeSchedulerRole

Add permission to invoke Step Functions:

```yaml
EventBridgeSchedulerRole:
  # ... existing properties ...
  Policies:
    - PolicyName: !Sub EventBridgeSchedulerPolicy-${Environment}
      PolicyDocument:
        Version: '2012-10-17'
        Statement:
          # EXISTING: Permission to invoke LambdaExecutor (keep for backward compatibility during migration)
          - Effect: Allow
            Action:
              - lambda:InvokeFunction
            Resource: !Sub arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:${StackName}-${Environment}-executor

          # NEW: Permission to start Step Functions execution
          - Effect: Allow
            Action:
              - states:StartExecution
            Resource: !GetAtt ExecutorStateMachine.Arn
```

### Update Schedule Creation Logic

In `ExecutionAPI/app/routers/tenants.py`, when creating schedules, use Step Functions ARN:

```python
# Current code uses:
executor_arn = os.environ.get("LAMBDA_EXECUTOR_ARN")

# Update to support both (for migration):
use_step_functions = os.environ.get("USE_STEP_FUNCTIONS_EXECUTOR", "false").lower() == "true"

if use_step_functions:
    executor_arn = os.environ.get("STEP_FUNCTIONS_EXECUTOR_ARN")
else:
    executor_arn = os.environ.get("LAMBDA_EXECUTOR_ARN")
```

Add to Globals environment variables:

```yaml
Globals:
  Function:
    Environment:
      Variables:
        # ... existing variables ...

        # Step Functions executor ARN
        STEP_FUNCTIONS_EXECUTOR_ARN: !GetAtt ExecutorStateMachine.Arn

        # Feature flag to use Step Functions instead of Lambda
        USE_STEP_FUNCTIONS_EXECUTOR: "false"  # Set to "true" to enable
```

## Outputs

Add these outputs to `template.yaml`:

```yaml
Outputs:
  # ... existing outputs ...

  ExecutorStateMachineArn:
    Description: ARN of the Executor Step Functions state machine
    Value: !GetAtt ExecutorStateMachine.Arn

  ExecutorStateMachineName:
    Description: Name of the Executor Step Functions state machine
    Value: !GetAtt ExecutorStateMachine.Name

  PreprocessingLambdaArn:
    Description: ARN of the Preprocessing Lambda
    Value: !GetAtt PreprocessingLambda.Arn

  LambdaExecutionHelperArn:
    Description: ARN of the Lambda Execution Helper
    Value: !GetAtt LambdaExecutionHelperLambda.Arn

  PostprocessingLambdaArn:
    Description: ARN of the Postprocessing Lambda
    Value: !GetAtt PostprocessingLambda.Arn
```

## Deployment Steps

### 1. Initial Deployment (Dual Mode)

```bash
# Deploy with Step Functions but keep using Lambda
sam build
sam deploy \
  --parameter-overrides \
    Owner=your-email@example.com \
    Environment=dev \
    StackName=sts

# At this point:
# - Both LambdaExecutor and ExecutorStateMachine exist
# - EventBridge schedules still target LambdaExecutor
# - USE_STEP_FUNCTIONS_EXECUTOR=false
```

### 2. Test Step Functions

```bash
# Manually test Step Functions execution
aws stepfunctions start-execution \
  --state-machine-arn $(aws cloudformation describe-stacks \
    --stack-name sts-dev \
    --query 'Stacks[0].Outputs[?OutputKey==`ExecutorStateMachineArn`].OutputValue' \
    --output text) \
  --input file://ExecutorStepFunction/test_events/execution_input.json \
  --name test-execution-$(date +%s)

# Monitor execution in Step Functions console
```

### 3. Enable Step Functions for New Schedules

Update stack with feature flag enabled:

```bash
# Update the template.yaml Globals section:
USE_STEP_FUNCTIONS_EXECUTOR: "true"

# Redeploy
sam build && sam deploy
```

Now new schedules will use Step Functions, existing schedules still use Lambda.

### 4. Migrate Existing Schedules

Option A: Let schedules naturally update (when users edit them)
Option B: Write a migration script to update all schedules

```python
# migration_script.py
import boto3

scheduler = boto3.client('scheduler')
sfn_arn = 'arn:aws:states:region:account:stateMachine:sts-dev-executor'

# List all schedule groups
groups = scheduler.list_schedule_groups()

for group in groups['ScheduleGroups']:
    group_name = group['Name']

    # List schedules in group
    schedules = scheduler.list_schedules(GroupName=group_name)

    for schedule in schedules['Schedules']:
        schedule_name = schedule['Name']

        # Get full schedule details
        details = scheduler.get_schedule(
            GroupName=group_name,
            Name=schedule_name
        )

        # Check if it's using LambdaExecutor
        if 'lambda' in details['Target']['Arn'] and 'executor' in details['Target']['Arn']:
            # Update to use Step Functions
            details['Target']['Arn'] = sfn_arn

            scheduler.update_schedule(
                GroupName=group_name,
                Name=schedule_name,
                # ... pass all required parameters
            )

            print(f"Migrated: {group_name}/{schedule_name}")
```

### 5. Deprecate LambdaExecutor

After all schedules are migrated:

```yaml
# Comment out or remove LambdaExecutor from template.yaml
# LambdaExecutor:
#   Type: AWS::Serverless::Function
#   ...

# Remove LAMBDA_EXECUTOR_ARN from environment variables

# Redeploy
sam build && sam deploy
```

## Monitoring After Deployment

### CloudWatch Alarms

Create alarms for:

1. **Step Functions Execution Failures**
```yaml
ExecutorStateMachineFailuresAlarm:
  Type: AWS::CloudWatch::Alarm
  Properties:
    AlarmName: !Sub ${StackName}-${Environment}-executor-sfn-failures
    MetricName: ExecutionsFailed
    Namespace: AWS/States
    Dimensions:
      - Name: StateMachineArn
        Value: !GetAtt ExecutorStateMachine.Arn
    Statistic: Sum
    Period: 300
    EvaluationPeriods: 1
    Threshold: 5
    ComparisonOperator: GreaterThanThreshold
```

2. **Lambda Helper Errors**
```yaml
LambdaHelperErrorsAlarm:
  Type: AWS::CloudWatch::Alarm
  Properties:
    AlarmName: !Sub ${StackName}-${Environment}-lambda-helper-errors
    MetricName: Errors
    Namespace: AWS/Lambda
    Dimensions:
      - Name: FunctionName
        Value: !Ref LambdaExecutionHelperLambda
    Statistic: Sum
    Period: 300
    EvaluationPeriods: 1
    Threshold: 5
    ComparisonOperator: GreaterThanThreshold
```

### Dashboard

Create a CloudWatch dashboard:

```yaml
ExecutorDashboard:
  Type: AWS::CloudWatch::Dashboard
  Properties:
    DashboardName: !Sub ${StackName}-${Environment}-executor
    DashboardBody: !Sub |
      {
        "widgets": [
          {
            "type": "metric",
            "properties": {
              "metrics": [
                ["AWS/States", "ExecutionsStarted", {"stat": "Sum", "label": "Started"}],
                [".", "ExecutionsSucceeded", {"stat": "Sum", "label": "Succeeded"}],
                [".", "ExecutionsFailed", {"stat": "Sum", "label": "Failed"}]
              ],
              "period": 300,
              "stat": "Sum",
              "region": "${AWS::Region}",
              "title": "Executor Executions",
              "yAxis": {
                "left": {
                  "min": 0
                }
              }
            }
          }
        ]
      }
```

## Rollback Plan

If issues arise after migration:

1. **Immediate Rollback**: Update feature flag
```yaml
USE_STEP_FUNCTIONS_EXECUTOR: "false"
```

2. **Redeploy**: `sam build && sam deploy`

3. **All schedules revert** to using LambdaExecutor

4. **Step Functions remains deployed** for investigation

## Cost Estimation

For 10,000 executions/day:

### Current (LambdaExecutor)
- Lambda: 10,000 * $0.0000002 = $0.002/day = $0.73/year

### New (ExecutorStepFunction)
- Step Functions: 10,000 * 5 transitions * $0.000025 = $1.25/day
- 3 Lambdas: 30,000 * $0.0000002 = $0.006/day
- Total: $1.256/day = $458.44/year

**Recommendation**: Worth the cost for:
- Better observability
- Redrive capability
- Support for long-running ECS tasks
- Extensibility for future features
