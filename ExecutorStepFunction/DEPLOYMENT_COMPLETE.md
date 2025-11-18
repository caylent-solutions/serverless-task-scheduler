# ExecutorStepFunction - Deployment Complete

The ExecutorStepFunction infrastructure has been fully integrated into `template.yaml`.

## What Was Added to template.yaml

### 1. Lambda Functions (3)

#### PreprocessingLambda
- **Function Name**: `${StackName}-${Environment}-executor-preprocessing`
- **Handler**: `preprocessing.handler`
- **Timeout**: 30 seconds
- **Memory**: 256 MB
- **Role**: PreprocessingLambdaRole
  - DynamoDB GetItem on TargetsTable and TenantMappingsTable

#### LambdaExecutionHelperLambda
- **Function Name**: `${StackName}-${Environment}-executor-lambda-helper`
- **Handler**: `lambda_execution_helper.handler`
- **Timeout**: 60 seconds (needs longer for target Lambda execution)
- **Memory**: 256 MB
- **Role**: LambdaExecutionHelperRole
  - Lambda InvokeFunction on all functions (*)
  - CloudWatch Logs DescribeLogStreams and FilterLogEvents

#### PostprocessingLambda
- **Function Name**: `${StackName}-${Environment}-executor-postprocessing`
- **Handler**: `postprocessing.handler`
- **Timeout**: 30 seconds
- **Memory**: 256 MB
- **Role**: PostprocessingLambdaRole
  - DynamoDB PutItem on TargetExecutionsTable

### 2. Step Functions State Machine

#### ExecutorStateMachine
- **Name**: `${StackName}-${Environment}-executor-sfn`
- **Type**: STANDARD
- **Tracing**: Enabled (X-Ray)
- **Definition**: `ExecutorStepFunction/state_machine.json`
- **DefinitionSubstitutions**:
  - `PreprocessingLambdaArn`: Preprocessing Lambda ARN
  - `LambdaExecutionHelperArn`: Lambda Execution Helper ARN
  - `PostprocessingLambdaArn`: Postprocessing Lambda ARN
- **Role**: ExecutorStateMachineRole
  - Lambda InvokeFunction on all three helper Lambdas
  - ECS RunTask, StopTask, DescribeTasks (*)
  - Step Functions StartExecution, DescribeExecution, StopExecution (*)
  - IAM PassRole for ECS tasks
  - X-Ray tracing permissions

### 3. IAM Role Updates

#### EventBridgeSchedulerRole (Updated)
Added permission to start Step Functions execution:
```yaml
- Effect: Allow
  Action:
    - states:StartExecution
  Resource: !Sub arn:aws:states:${AWS::Region}:${AWS::AccountId}:stateMachine:${StackName}-${Environment}-executor-sfn
```

This allows EventBridge Scheduler to invoke either LambdaExecutor or ExecutorStateMachine during the migration period.

### 4. Environment Variables (Globals)

Added to all Lambda functions:
- `STEP_FUNCTIONS_EXECUTOR_ARN`: ARN of the ExecutorStateMachine
- `USE_STEP_FUNCTIONS_EXECUTOR`: Feature flag ("false" by default)

These enable the gradual migration from LambdaExecutor to ExecutorStateMachine.

### 5. CloudFormation Outputs

Added outputs:
- `ExecutorStateMachineArn`: ARN of the state machine
- `ExecutorStateMachineName`: Name of the state machine
- `PreprocessingLambdaArn`: ARN of preprocessing Lambda
- `LambdaExecutionHelperArn`: ARN of Lambda execution helper
- `PostprocessingLambdaArn`: ARN of postprocessing Lambda

## Resource Naming Convention

All resources follow the pattern:
```
${StackName}-${Environment}-executor-<component>
```

Examples:
- `sts-dev-executor-sfn` (state machine)
- `sts-dev-executor-preprocessing` (preprocessing Lambda)
- `sts-dev-executor-lambda-helper` (Lambda execution helper)
- `sts-dev-executor-postprocessing` (postprocessing Lambda)

## IAM Roles Summary

| Role | AssumeRole Principal | Key Permissions |
|------|---------------------|-----------------|
| PreprocessingLambdaRole | lambda.amazonaws.com | DynamoDB GetItem on Targets and TenantMappings |
| LambdaExecutionHelperRole | lambda.amazonaws.com | Lambda InvokeFunction, CloudWatch Logs read |
| PostprocessingLambdaRole | lambda.amazonaws.com | DynamoDB PutItem on Executions |
| ExecutorStateMachineRole | states.amazonaws.com | Invoke 3 Lambdas, ECS/SFN execution, X-Ray |
| EventBridgeSchedulerRole | scheduler.amazonaws.com | Invoke LambdaExecutor and ExecutorStateMachine |

## Deployment Commands

### Deploy Both LambdaExecutor and ExecutorStateMachine

```bash
sam build
sam deploy
```

This deploys both systems side-by-side for gradual migration.

### Enable Step Functions (Feature Flag)

Update `template.yaml`:
```yaml
USE_STEP_FUNCTIONS_EXECUTOR: "true"
```

Then redeploy:
```bash
sam build && sam deploy
```

New schedules will use ExecutorStateMachine, existing schedules continue with LambdaExecutor.

### Test Step Functions Manually

```bash
# Get the ARN from outputs
STATE_MACHINE_ARN=$(aws cloudformation describe-stacks \
  --stack-name <your-stack-name> \
  --query 'Stacks[0].Outputs[?OutputKey==`ExecutorStateMachineArn`].OutputValue' \
  --output text)

# Start execution
aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input file://ExecutorStepFunction/test_events/execution_input.json \
  --name test-$(date +%s)
```

## Migration Path

### Phase 1: Deploy (Current)
✅ Both LambdaExecutor and ExecutorStateMachine deployed
✅ EventBridge schedules use LambdaExecutor
✅ `USE_STEP_FUNCTIONS_EXECUTOR: "false"`

### Phase 2: Enable Feature Flag
- Set `USE_STEP_FUNCTIONS_EXECUTOR: "true"`
- Redeploy
- New schedules use ExecutorStateMachine
- Existing schedules still use LambdaExecutor

### Phase 3: Migrate Existing Schedules
- Update schedules via API or migration script
- Change target ARN from Lambda to Step Functions
- Monitor execution records in DynamoDB

### Phase 4: Deprecate LambdaExecutor
- After all schedules migrated
- Comment out LambdaExecutor resources in template.yaml
- Remove LAMBDA_EXECUTOR_ARN from environment variables
- Redeploy

## Cost Impact

With both systems deployed:

### Current Cost (LambdaExecutor only)
- 1 Lambda function: $0.20 per 1M requests

### New Cost (Both systems)
- 1 Lambda function (LambdaExecutor): $0.20 per 1M requests
- 3 Lambda functions (ExecutorStepFunction): $0.60 per 1M requests
- 1 Step Functions state machine: $25 per 1M state transitions
- **Total**: ~5 state transitions per execution = $0.125 per 1,000 executions

For 10,000 executions/day:
- LambdaExecutor: $0.73/year
- ExecutorStateMachine: $458/year

**Recommendation**: Worth the cost for better observability, redrive capability, and extensibility.

## Validation

After deployment, verify:

### 1. Lambda Functions Exist
```bash
aws lambda list-functions --query 'Functions[?contains(FunctionName, `executor`)].FunctionName'
```

Should show:
- `<stack>-<env>-executor` (LambdaExecutor)
- `<stack>-<env>-executor-preprocessing`
- `<stack>-<env>-executor-lambda-helper`
- `<stack>-<env>-executor-postprocessing`

### 2. State Machine Exists
```bash
aws stepfunctions list-state-machines --query 'stateMachines[?contains(name, `executor-sfn`)].name'
```

Should show:
- `<stack>-<env>-executor-sfn`

### 3. IAM Roles Exist
```bash
aws iam list-roles --query 'Roles[?contains(RoleName, `executor`)].RoleName'
```

Should show roles for all components.

### 4. Test Step Functions Execution
```bash
# Use test event
aws stepfunctions start-execution \
  --state-machine-arn <arn> \
  --input file://ExecutorStepFunction/test_events/execution_input.json \
  --name manual-test-$(date +%s)

# Watch execution in console
echo "https://console.aws.amazon.com/states/home?region=<region>#/statemachines/view/<arn>"
```

## Troubleshooting

### Lambda Functions Not Found
- Check `sam build` completed successfully
- Verify `ExecutorStepFunction/` directory has all .py files
- Check CloudFormation stack events for errors

### State Machine Definition Invalid
- Validate JSON: `cat ExecutorStepFunction/state_machine.json | jq .`
- Check DefinitionSubstitutions in template.yaml
- Ensure ARN placeholders match Lambda function names

### IAM Permission Errors
- Check ExecutorStateMachineRole has Lambda InvokeFunction
- Verify EventBridgeSchedulerRole has states:StartExecution
- Review CloudWatch Logs for specific permission errors

### Execution Records Not Written
- Check PostprocessingLambda has DynamoDB PutItem permission
- Verify DYNAMODB_EXECUTIONS_TABLE environment variable is correct
- Check CloudWatch Logs for PostprocessingLambda errors

## Next Steps

1. ✅ Deploy infrastructure: `sam build && sam deploy`
2. ✅ Verify all resources created
3. ✅ Test manual Step Functions execution
4. ⏳ Update UI to support redrive functionality
5. ⏳ Enable feature flag when ready
6. ⏳ Migrate schedules gradually
7. ⏳ Monitor and validate
8. ⏳ Deprecate LambdaExecutor

## Reference

- [State Machine Definition](state_machine.json)
- [Preprocessing Lambda](preprocessing.py)
- [Lambda Execution Helper](lambda_execution_helper.py)
- [Postprocessing Lambda](postprocessing.py)
- [Design Documentation](DESIGN_IMPROVEMENTS.md)
- [Deployment Notes](DEPLOYMENT_NOTES.md)
