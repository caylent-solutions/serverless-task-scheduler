# task-execution

The Step Functions-based execution engine that orchestrates all scheduled task runs. It replaced an earlier monolithic Lambda executor to gain visual workflows, built-in retries, redrive capability, and native support for long-running ECS and nested Step Functions targets.

For a full walkthrough of the architecture, routing patterns, and redrive design, see the [Executor Step Function deep dive](../.docs/02-executor-step-function.md).

## Architecture

![Executor Step Function](../.docs/img/executor-step-function.png)

The executor uses a **Parallel state with a single branch** to wrap the execution logic. This pattern provides centralized error handling across all target types and a consistent output format via `ResultSelector`, while preserving redrive capability on any failed state.

Postprocessing is decoupled from the state machine -- an EventBridge rule listens for execution status changes (`SUCCEEDED`, `FAILED`, `TIMED_OUT`, `ABORTED`) and triggers the Postprocessing Lambda automatically.

## Components

### State Machine Definition
**File**: `executor_step_function.json`

Defines the three-phase workflow: Preprocessing → Target Type Choice → EventBridge Handoff. The `TargetTypeChoice` state routes to the appropriate executor based on `$.target_type` (determined by parsing the target ARN during preprocessing).

### Preprocessing Lambda
**File**: `preprocessing.py`

Resolves a tenant's target alias to the actual AWS resource. Queries `TenantMappingsTable` to find the `target_id`, then queries `TargetsTable` to get the ARN, type, and configuration. Merges the mapping's default payload with the runtime payload (runtime values override defaults). Writes an initial `IN_PROGRESS` record to the executions table.

**Input**: `{ tenant_id, target_alias, schedule_id, payload }`
**Output**: `{ tenant_id, target_alias, schedule_id, target_id, target_arn, target_type, target_config, merged_payload }`

### Lambda Execution Helper
**File**: `lambda_execution_helper.py`

Invokes Lambda targets and captures CloudWatch log URLs. This exists because Step Functions' native Lambda integration doesn't expose the `RequestId`, which is needed to find the exact log stream for a given invocation. The helper invokes the target, captures the request ID, searches recent log streams for it, and returns a direct console URL.

**Input**: `{ target_arn, merged_payload }`
**Output**: `{ execution_id, target_type, response, status_code, function_name, cloudwatch_logs_url }`

### Postprocessing Lambda
**File**: `postprocessing.py`

Records execution results to DynamoDB. Triggered by EventBridge (not called directly from the state machine). Calls `DescribeExecution` to get the full output, extracts the result or error, generates/preserves the CloudWatch logs URL, and writes the final execution record. For failures, includes `redrive_info` with the failed state name and whether redrive is possible.

### Shared Module
**File**: `execution_recorder.py`

Shared functions used by both `postprocessing.py` and `record_redrive_result.py`: `record_execution()`, `lookup_target_arn_from_dynamodb()`, and `generate_console_url()`. This avoids duplicating the DynamoDB write logic between the two recording paths.

### Redrive Monitor
**File**: `redrive_step_function.json` + `record_redrive_result.py`

Handles a specific challenge with Step Functions targets: when a nested child execution is redriven, its completion event doesn't match the main `ExecutionStatusEventRule` (scoped to the Executor state machine). The monitor polls the child via `Wait → DescribeExecution → Choice` until it reaches a terminal state, then `RecordRedriveResultLambda` writes the final result to DynamoDB. See [REDRIVE_DESIGN.md](../REDRIVE_DESIGN.md) for the full design.

## Error Handling & Redrive

Each execution task has a `Catch` block that captures errors and routes them to postprocessing. Catch blocks do **not** prevent redrive -- Step Functions allows restarting from any failed state regardless. When redriven, already-succeeded states are skipped and execution resumes from the failure point.

For each failed execution, the system stores:

```json
{
  "can_redrive": true,
  "redrive_from_state": "ExecuteTargetWithErrorHandling",
  "failed_state": "ExecuteLambdaTarget",
  "state_machine_execution_arn": "arn:aws:states:...",
  "error": { "Error": "Lambda.ServiceException", "Cause": "..." }
}
```

## DynamoDB Schema

**Primary Key**: `tenant_schedule` (PK) = `{tenant_id}#{schedule_id}`, `execution_id` (SK) = `{timestamp}#{identifier}`

**GSI** `tenant-target-index`: `tenant_target` (PK) = `{tenant_id}#{target_alias}`, `timestamp` (SK)

**Failure-specific fields**: `failed_state`, `can_redrive`, `redrive_info`, `redrive_from_state`, `state_machine_execution_arn`

## Environment Variables

| Variable | Used By | Description |
|----------|---------|-------------|
| `DYNAMODB_TABLE` | Preprocessing | Targets table name |
| `DYNAMODB_TENANT_TABLE` | Preprocessing | Tenant mappings table name |
| `DYNAMODB_EXECUTIONS_TABLE` | Postprocessing, Record Redrive Result | Executions table name |
| `APP_ENV` | All | Environment name (dev/qa/uat/prod) |

## IAM Permissions

| Component | Permissions |
|-----------|------------|
| Preprocessing Lambda | DynamoDB `GetItem` on Targets and TenantMappings tables |
| Lambda Execution Helper | Lambda `InvokeFunction` (wildcard), CloudWatch Logs `DescribeLogStreams` + `FilterLogEvents` |
| Postprocessing Lambda | DynamoDB `PutItem` on Executions table, Step Functions `DescribeExecution` |
| State Machine Role | Lambda `InvokeFunction` on helper Lambdas, ECS `RunTask`/`DescribeTasks`, Step Functions `StartExecution`/`DescribeExecution`/`StopExecution`, IAM `PassRole` to `ecs-tasks.amazonaws.com` |

## Testing

```bash
# Test individual Lambdas locally
sam local invoke PreprocessingLambda -e test_events/preprocessing_event.json
sam local invoke LambdaExecutionHelperLambda -e test_events/lambda_execution_event.json
sam local invoke PostprocessingLambda -e test_events/postprocessing_event.json

# Test with Step Functions Local
docker run -p 8083:8083 amazon/aws-stepfunctions-local
```

## Limitations

- **Payload size**: 256 KB per state
- **Execution history**: 25,000 events max per execution
- **Cold starts**: Three Lambda cold starts vs. one (mitigated with provisioned concurrency)
- **Execution time**: 1 year max (practically unlimited for all use cases)

## Further Reading

- [Executor Step Function deep dive](../.docs/02-executor-step-function.md) -- Full architecture walkthrough with routing patterns, payload merging, and observability
- [Security Model](../.docs/03-security-model.md) -- IAM role separation and the three-tier permission model
- [Redrive Design](../REDRIVE_DESIGN.md) -- Monitor state machine design for Step Functions target redrives
- [Step Functions Error Handling](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)
- [Step Functions Redrive](https://docs.aws.amazon.com/step-functions/latest/dg/redrive-executions.html)
- [Step Functions Service Integrations](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-service-integrations.html)
