# ExecutorStepFunction Implementation Summary

## Directory Structure

```
ExecutorStepFunction/
├── state_machine.json                      # Step Functions state machine definition
├── preprocessing.py                        # Lambda: Resolve target and merge payloads
├── lambda_execution_helper.py              # Lambda: Execute Lambda targets with CloudWatch URL
├── postprocessing.py                       # Lambda: Record execution to DynamoDB
├── requirements.txt                        # Python dependencies
├── README.md                               # Comprehensive documentation
├── state_machine_visual.md                 # Visual flow diagrams
├── SUMMARY.md                              # This file
└── test_events/                            # Sample test events
    ├── preprocessing_event.json
    ├── lambda_execution_event.json
    ├── postprocessing_success_event.json
    ├── postprocessing_failure_event.json
    └── execution_input.json
```

## What's Been Created

### 1. State Machine Definition ([state_machine.json](state_machine.json))
A complete Step Functions state machine that:
- ✅ Handles preprocessing (resolve target, merge payloads)
- ✅ Routes to Lambda, ECS, or Step Functions based on target type
- ✅ **Uses Parallel state with single branch to centralize error handling** (see [DESIGN_IMPROVEMENTS.md](DESIGN_IMPROVEMENTS.md))
- ✅ Captures errors with Catch blocks
- ✅ Records success/failure to DynamoDB
- ✅ Preserves redrive capability for all failed states
- ✅ Uses native AWS integrations where possible (ECS, Step Functions)
- ✅ **Clean visual graph**: Parallel state collapses complexity (11 states instead of 14)

### 2. Preprocessing Lambda ([preprocessing.py](preprocessing.py))
- ✅ Resolves tenant mapping from DynamoDB
- ✅ Resolves target details from DynamoDB
- ✅ Merges default payload with runtime payload
- ✅ Validates tenant and target exist
- ✅ Outputs enriched event for downstream states

### 3. Lambda Execution Helper ([lambda_execution_helper.py](lambda_execution_helper.py))
- ✅ Invokes Lambda functions synchronously
- ✅ Captures Lambda RequestId
- ✅ Searches CloudWatch logs for exact log stream
- ✅ Generates direct console URL to log stream
- ✅ Handles Lambda function errors

### 4. Postprocessing Lambda ([postprocessing.py](postprocessing.py))
- ✅ Records execution results to DynamoDB
- ✅ Writes redrive information for failed executions
- ✅ Maintains backward compatibility with LambdaExecutor schema
- ✅ Includes failed_state, can_redrive, and redrive_from_state
- ✅ Supports both success and failure paths

### 5. Documentation
- ✅ [README.md](README.md): Comprehensive guide covering architecture, components, deployment, testing
- ✅ [state_machine_visual.md](state_machine_visual.md): Visual flow diagrams and data transformations
- ✅ Test events for local testing

## Key Features

### ✅ Redrive Capability
**Question**: Can we record failure states to the database AND still be able to redrive the execution from the failure point?

**Answer**: YES!

The implementation uses task-level Catch blocks that:
1. Capture errors and route to RecordExecutionFailure
2. Write failure details to DynamoDB including:
   - `failed_state`: Which state failed
   - `can_redrive`: Boolean (always true)
   - `redrive_from_state`: State to redrive from
   - `state_machine_execution_arn`: Step Functions execution ARN
3. End with a Fail state

Step Functions' redrive feature allows restarting from ANY failed state, even if the failure was caught and handled. The redrive will:
- Skip already-succeeded states
- Retry the failed state with the same input
- Continue from there

### ✅ Error Handling
- Preprocessing failures are caught and recorded separately
- Target execution failures are caught per target type
- All errors include full context for debugging
- UI can display error details and offer redrive button

### ✅ Observability
- Visual workflow in Step Functions console
- Each state's input/output visible
- CloudWatch logs for each Lambda
- X-Ray tracing support
- Execution history preserved

### ✅ Extensibility
- Easy to add new target types (just add a new Choice branch)
- Can add pre-flight checks before execution
- Can add approval workflows
- Can add parallel execution support

## Data Flow

### Input (from EventBridge Scheduler)
```json
{
  "tenant_id": "jer",
  "target_alias": "calculator",
  "schedule_id": "daily-calculation",
  "payload": {...}
}
```

### Output (DynamoDB Execution Record - Success)
```json
{
  "tenant_schedule": "jer#daily-calculation",
  "execution_id": "2025-01-15T10:00:00.000Z#a1b2c3d4...",
  "tenant_target": "jer#calculator",
  "timestamp": "2025-01-15T10:00:00.000Z",
  "status": "SUCCESS",
  "result": {
    "execution_id": "a1b2c3d4...",
    "response": {...},
    "cloudwatch_logs_url": "..."
  },
  "state_machine_execution_arn": "execution-name"
}
```

### Output (DynamoDB Execution Record - Failure)
```json
{
  "tenant_schedule": "jer#daily-calculation",
  "execution_id": "2025-01-15T10:00:00.000Z#execution-name",
  "tenant_target": "jer#calculator",
  "timestamp": "2025-01-15T10:00:00.000Z",
  "status": "FAILED",
  "result": {
    "Error": "Lambda.ServiceException",
    "Cause": "..."
  },
  "failed_state": "ExecuteLambdaTarget",
  "can_redrive": true,
  "redrive_info": {
    "can_redrive": true,
    "redrive_from_state": "ExecuteLambdaTarget"
  },
  "state_machine_execution_arn": "arn:aws:states:..."
}
```

## Next Steps

### To Deploy:
1. Add the Lambda functions to `template.yaml`
2. Add the Step Functions state machine to `template.yaml`
3. Add IAM roles and permissions
4. Update EventBridge Scheduler to target Step Functions instead of LambdaExecutor

### To Test:
1. Use SAM CLI to test individual Lambda functions locally
2. Use Step Functions Local for end-to-end testing
3. Deploy to dev environment and test with non-critical schedules

### To Integrate with UI:
1. Update execution list to display `failed_state` and `can_redrive`
2. Add "Redrive" button for failed executions where `can_redrive: true`
3. Implement redrive API call: `aws stepfunctions redrive-execution --execution-arn <arn>`
4. Display Step Functions execution link for visual debugging

## Benefits Over LambdaExecutor

| Feature | LambdaExecutor | ExecutorStepFunction |
|---------|----------------|---------------------|
| **Redrive** | Manual re-invoke | Native redrive from failed state |
| **Visibility** | Logs only | Visual workflow + logs |
| **Debugging** | Parse logs | View state I/O |
| **Error Handling** | Try-catch in code | Catch blocks per state |
| **Extensibility** | Modify code | Add states |
| **Timeout** | 15 min max | 1 year max |
| **Long-running** | Not suitable | Perfect for ECS tasks |

## Cost Comparison

### LambdaExecutor (1 Lambda)
- $0.20 per 1 million requests
- For 1,000 executions/day: ~$0.006/day = $2.19/year

### ExecutorStepFunction (3 Lambdas + State Machine)
- State transitions: ~5 per execution
- $25 per 1 million state transitions
- Lambda executions: 3 per execution
- For 1,000 executions/day:
  - Step Functions: $0.125/day
  - Lambdas: $0.018/day
  - Total: ~$0.143/day = $52.20/year

**Note**: The higher cost is offset by better observability, redrive capability, and support for long-running tasks.

## Migration Strategy

1. **Phase 1**: Deploy ExecutorStepFunction alongside LambdaExecutor (both exist)
2. **Phase 2**: Test with a few non-critical schedules
3. **Phase 3**: Update UI to support redrive functionality
4. **Phase 4**: Gradually migrate schedules to use Step Functions
5. **Phase 5**: Deprecate LambdaExecutor once all schedules migrated

## Questions Answered

### ✅ Can we record failures AND redrive from failure point?
**YES** - Catch blocks don't prevent redrive. We can catch errors, record them to DynamoDB with full context, and still use Step Functions' native redrive capability.

### ✅ How do we capture CloudWatch logs URL for Lambda executions?
We use a custom Lambda helper that invokes the target Lambda and captures the RequestId, then searches CloudWatch logs to find the exact log stream.

### ✅ How do we handle different target types (Lambda, ECS, SFN)?
We use a Choice state that routes to the appropriate executor based on `target_type`. ECS and Step Functions use native integrations, Lambda uses our custom helper.

### ✅ What information do we store for redrive?
We store: `failed_state`, `can_redrive`, `redrive_from_state`, `state_machine_execution_arn`, and the full error object. This gives the UI everything needed to display failure info and enable redrive.
