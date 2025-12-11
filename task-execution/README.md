# task-execution

A Step Functions-based replacement for the LambdaExecutor Lambda function. This implementation provides better observability, error handling, and redrive capabilities for scheduled task execution.

## Overview

The task-execution orchestrates the execution of scheduled tasks by:
1. **Preprocessing**: Resolving tenant target mappings and merging payloads
2. **Target Execution**: Conditionally routing to Lambda, ECS, or Step Functions based on target type
3. **Postprocessing**: Recording execution results to DynamoDB with redrive information

## Architecture

**Key Design**: Uses a **Parallel state with single branch** to wrap the execution logic, providing centralized error handling and clean visual representation. See [DESIGN_IMPROVEMENTS.md](DESIGN_IMPROVEMENTS.md) for details.

```
EventBridge Scheduler
        ↓
┌─────────────────────────────────────┐
│  task-execution               │
│                                     │
│  ┌─────────────────────────┐      │
│  │  Preprocessing Lambda    │      │
│  │  - Resolve target        │      │
│  │  - Merge payloads        │      │
│  └──────────┬───────────────┘      │
│             ↓                       │
│  ┌─────────────────────────┐      │
│  │  Parallel State          │      │
│  │  (Error Handling Wrapper)│      │
│  │  ┌─────────────────────┐│      │
│  │  │ Target Type Choice  ││      │
│  │  └─┬───────┬────────┬──┘│      │
│  │    ↓       ↓        ↓   │      │
│  │  Lambda  ECS  StepFns   │      │
│  └───┬─────────────────────┘      │
│      ↓ (success or error)          │
│  ┌─────────────────────────┐      │
│  │  Postprocessing Lambda   │      │
│  │  - Record to DynamoDB    │      │
│  │  - Add redrive info      │      │
│  └─────────────────────────┘      │
└─────────────────────────────────────┘
```

**Benefits**:
- Single error handling path (no duplication)
- Cleaner visual graph in Step Functions console
- Easy to extend with new target types

## Components

### 1. State Machine Definition
**File**: `state_machine.json`

The core orchestration workflow that defines:
- State transitions and error handling
- Conditional routing based on target type
- Retry policies for transient failures
- Catch blocks for error recording

**Key Features**:
- Task-level error handling with `Catch` blocks
- Redrive capability preserved for all failed states
- Native Step Functions integrations for ECS and nested Step Functions
- Custom Lambda integration for CloudWatch log URL capture

### 2. Preprocessing Lambda
**File**: `preprocessing.py`

Resolves the target from tenant mapping and prepares the execution payload.

**Input**:
```json
{
  "tenant_id": "jer",
  "target_alias": "calculator",
  "schedule_id": "daily-calculation",
  "payload": {...}
}
```

**Output**:
```json
{
  "tenant_id": "jer",
  "target_alias": "calculator",
  "schedule_id": "daily-calculation",
  "target_id": "calc-target",
  "target_arn": "arn:aws:lambda:...",
  "target_type": "lambda",
  "target_config": {...},
  "merged_payload": {...}
}
```

**Responsibilities**:
- Query DynamoDB for tenant mapping
- Query DynamoDB for target details
- Merge default payload with runtime payload (runtime overrides defaults)
- Validate target exists and is accessible

### 3. Lambda Execution Helper
**File**: `lambda_execution_helper.py`

Executes Lambda functions and captures CloudWatch logs URL.

**Why Needed**: Step Functions' native Lambda integration doesn't provide the RequestId, which is needed to find the exact CloudWatch log stream.

**Input**:
```json
{
  "target_arn": "arn:aws:lambda:...",
  "merged_payload": {...}
}
```

**Output**:
```json
{
  "execution_id": "a1b2c3d4-...",
  "target_type": "lambda",
  "response": {...},
  "status_code": 200,
  "function_name": "calculator",
  "cloudwatch_logs_url": "https://console.aws.amazon.com/cloudwatch/..."
}
```

**Responsibilities**:
- Invoke Lambda function synchronously
- Capture RequestId from Lambda response
- Search CloudWatch logs for the specific log stream
- Generate direct console URL to log stream
- Handle Lambda function errors

### 4. Postprocessing Lambda
**File**: `postprocessing.py`

Records execution results to DynamoDB with redrive information.

**Input (Success)**:
```json
{
  "tenant_id": "jer",
  "target_alias": "calculator",
  "schedule_id": "daily-calculation",
  "execution_result": {...},
  "status": "SUCCESS",
  "state_machine_execution_arn": "execution-name",
  "execution_start_time": "2025-01-15T10:00:00.000Z"
}
```

**Input (Failure)**:
```json
{
  "tenant_id": "jer",
  "target_alias": "calculator",
  "schedule_id": "daily-calculation",
  "execution_result": {
    "Error": "...",
    "Cause": "..."
  },
  "status": "FAILED",
  "state_machine_execution_arn": "execution-name",
  "execution_start_time": "2025-01-15T10:00:00.000Z",
  "failed_state": "ExecuteLambdaTarget",
  "redrive_info": {
    "can_redrive": true,
    "redrive_from_state": "ExecuteLambdaTarget"
  }
}
```

**Output**:
```json
{
  "status": "recorded",
  "execution_id": "2025-01-15T10:00:00.000Z#request-id"
}
```

**Responsibilities**:
- Write execution record to DynamoDB
- Include redrive information for failed executions
- Maintain backward compatibility with existing execution records
- Generate sortable execution IDs (timestamp#identifier)

## Error Handling & Redrive

### Error Handling Strategy

1. **Task-Level Catch Blocks**: Each execution task has a `Catch` block that captures errors and routes to the `RecordExecutionFailure` state
2. **Error Details Preserved**: The error object is captured in `$.error` and passed to postprocessing
3. **Graceful Failure**: Executions fail with a `Fail` state after recording the error

### Redrive Capability

**Key Question**: Can we record failures AND still redrive?

**Answer**: YES! Here's why:

- Step Functions' redrive feature allows restarting from ANY failed state
- Catch blocks don't prevent redrive - they just allow graceful error handling
- When you redrive, the execution:
  - Skips already-succeeded states
  - Retries the failed state with the same input
  - Continues from there

### Redrive Information Stored

For each failed execution, we store:
```json
{
  "can_redrive": true,
  "redrive_from_state": "ExecuteLambdaTarget",
  "failed_state": "ExecuteLambdaTarget",
  "state_machine_execution_arn": "arn:aws:states:...",
  "error": {
    "Error": "Lambda.ServiceException",
    "Cause": "..."
  }
}
```

This allows the UI to:
- Show which executions can be redriven
- Display which state failed
- Provide a direct link to redrive the execution

## DynamoDB Schema

Execution records are stored in the same table and format as LambdaExecutor:

**Primary Key**:
- `tenant_schedule` (PK): `{tenant_id}#{schedule_id}`
- `execution_id` (SK): `{timestamp}#{execution_identifier}`

**Additional Fields for Failures**:
- `failed_state`: Name of the state that failed
- `can_redrive`: Boolean indicating if redrive is possible
- `redrive_info`: Object with redrive details
- `redrive_from_state`: State to redrive from
- `state_machine_execution_arn`: Step Functions execution ARN

**GSI**: `tenant-target-index`
- `tenant_target` (PK): `{tenant_id}#{target_alias}`
- `timestamp` (SK): ISO 8601 timestamp

## Environment Variables

All Lambda functions require:
- `DYNAMODB_TABLE`: Targets table name
- `DYNAMODB_TENANT_TABLE`: Tenant mappings table name
- `DYNAMODB_EXECUTIONS_TABLE`: Executions table name
- `APP_ENV`: Environment name (dev/qa/uat/prod)
- `AWS_REGION`: AWS region

## IAM Permissions Required

### Preprocessing Lambda
- DynamoDB: `GetItem` on Targets and TenantMappings tables

### Lambda Execution Helper
- Lambda: `InvokeFunction` on target Lambda functions
- CloudWatch Logs: `DescribeLogStreams`, `FilterLogEvents`

### Postprocessing Lambda
- DynamoDB: `PutItem` on Executions table

### Step Functions State Machine
- Lambda: `InvokeFunction` on all three helper Lambdas
- ECS: `RunTask`, `DescribeTasks` for ECS targets
- Step Functions: `StartExecution` for nested Step Functions
- IAM: `PassRole` for ECS task execution roles

## Deployment

### SAM Template Integration

To integrate with `template.yaml`, add:

1. **Lambda Functions** (3):
   - PreprocessingLambda
   - LambdaExecutionHelperLambda
   - PostprocessingLambda

2. **Step Functions State Machine**:
   - Replace `${PreprocessingLambdaArn}` with `!GetAtt PreprocessingLambda.Arn`
   - Replace `${LambdaExecutionHelperArn}` with `!GetAtt LambdaExecutionHelperLambda.Arn`
   - Replace `${PostprocessingLambdaArn}` with `!GetAtt PostprocessingLambda.Arn`

3. **IAM Roles**:
   - task-executionRole (for state machine execution)
   - Update Lambda execution roles with necessary permissions

4. **EventBridge Scheduler Update**:
   - Change target from LambdaExecutor to task-execution

### Migration Path

1. **Phase 1**: Deploy task-execution alongside LambdaExecutor
2. **Phase 2**: Test with non-critical schedules
3. **Phase 3**: Gradually migrate schedules to use Step Functions
4. **Phase 4**: Deprecate LambdaExecutor once all schedules migrated

## Benefits Over LambdaExecutor

1. **Better Observability**:
   - Visual workflow in Step Functions console
   - Each step's input/output visible
   - Easier to debug failures

2. **Redrive Capability**:
   - Restart failed executions from any state
   - No need to re-run entire workflow
   - UI can expose redrive button

3. **Better Error Handling**:
   - Granular retry policies per state
   - Separate error paths for different failure types
   - Failed states clearly identified

4. **Extensibility**:
   - Easy to add new target types
   - Can add conditional logic (e.g., pre-flight checks)
   - Can add parallel executions

5. **Cost Efficiency** (for long-running tasks):
   - Step Functions doesn't charge for wait time
   - Better for ECS tasks that take minutes/hours
   - Lambda has 15-minute timeout limit

## Limitations

1. **State Machine Limit**: 25,000 events in execution history
2. **Execution Time**: 1 year maximum (practically unlimited)
3. **Payload Size**: 256 KB limit per state
4. **Cold Starts**: Three Lambda cold starts vs one (but can be mitigated with provisioned concurrency)

## Testing

### Local Testing

Use AWS SAM CLI to test individual Lambda functions:

```bash
# Test preprocessing
sam local invoke PreprocessingLambda -e test_events/preprocessing_event.json

# Test lambda execution helper
sam local invoke LambdaExecutionHelperLambda -e test_events/lambda_execution_event.json

# Test postprocessing
sam local invoke PostprocessingLambda -e test_events/postprocessing_event.json
```

### Step Functions Local Testing

Use Step Functions Local:
```bash
# Start local endpoint
docker run -p 8083:8083 amazon/aws-stepfunctions-local

# Create state machine
aws stepfunctions create-state-machine \
  --endpoint-url http://localhost:8083 \
  --name task-execution \
  --definition file://state_machine.json \
  --role-arn arn:aws:iam::123456789012:role/DummyRole

# Start execution
aws stepfunctions start-execution \
  --endpoint-url http://localhost:8083 \
  --state-machine-arn arn:aws:states:us-east-1:123456789012:stateMachine:task-execution \
  --input file://test_events/execution_input.json
```

## Monitoring

### CloudWatch Metrics

- Step Functions automatically publishes:
  - ExecutionsFailed
  - ExecutionsSucceeded
  - ExecutionTime
  - ExecutionThrottled

### CloudWatch Alarms

Recommended alarms:
1. ExecutionsFailed > threshold
2. ExecutionTime > timeout threshold
3. Lambda errors for helper functions

### X-Ray Tracing

Enable X-Ray on all Lambda functions and Step Functions for distributed tracing.

## Future Enhancements

1. **Parallel Execution**: Execute multiple targets in parallel
2. **Pre-flight Checks**: Validate execution conditions before starting
3. **Approval Workflow**: Add manual approval step for sensitive operations
4. **Conditional Execution**: Skip execution based on business logic
5. **Execution Queuing**: Queue executions when rate limits are hit
6. **Cost Optimization**: Use Express Workflows for high-throughput, short-duration executions

## References

- [Step Functions Error Handling](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)
- [Step Functions Redrive](https://docs.aws.amazon.com/step-functions/latest/dg/redrive-executions.html)
- [Step Functions Service Integrations](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-service-integrations.html)
