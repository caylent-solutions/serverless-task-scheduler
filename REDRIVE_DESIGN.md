# Step Function Redrive Design

## Problem

When a Step Functions target fails and is redriven via the API, the child execution is redriven directly. When the child completes, its EventBridge event carries the child's state machine ARN — which never matches the `ExecutionStatusEventRule` (scoped to `ExecutorStateMachine` only). The parent remains `FAILED`, postprocessor is never invoked, and DynamoDB stays `IN_PROGRESS` indefinitely.

Redriving the parent instead is not viable: `ExecuteStepFunctionTarget` names the child `{uuid}-nested` and AWS enforces execution name uniqueness for 90 days, so the parent redrive immediately fails with `ExecutionAlreadyExists`.

---

## Solution: Step Functions Redrive Monitor

Start a dedicated monitor state machine at redrive time. It polls the child execution using a `Wait → DescribeExecution → Choice` loop until the child reaches a terminal state, then invokes a Lambda to write the final result to DynamoDB, overwriting the `IN_PROGRESS` record.

```
POST /executions/{id}/redrive
  │
  ├─ sfn:RedriveExecution(child_execution_arn)
  ├─ DynamoDB: status → IN_PROGRESS
  └─ sfn:StartExecution(RedriveMonitorStateMachine, { child_execution_arn, tenant_id, target_alias, schedule_id })

RedriveMonitorStateMachine:
  Wait(60s)
    → aws-sdk:sfn:describeExecution(child_execution_arn)   ← native SDK, no Lambda
    → Choice: terminal status? No → loop / Yes → RecordRedriveResultLambda
        → derive parent_execution_name from child ARN (strip "-nested")
        → parent_execution_name == DynamoDB execution_id (SK)
        → put_item overwrites IN_PROGRESS with final status ✓
```

Monitor is only started for Step Functions targets (when `nested_execution_arn` is present in `redrive_info`). Lambda and ECS redrives go through the existing parent redrive path and are unaffected.

---

## DynamoDB Key Derivation

The child execution name is always `{parent_uuid}-nested` (set by `state_machine.json:100`). Stripping `-nested` yields the parent UUID, which is the DynamoDB SK (`execution_id`). This derivation is safe here — we're reversing a known transformation on a specific execution, not filtering across the account.

The DynamoDB PK (`tenant_schedule = "{tenant_id}#{schedule_id}"`) is not recoverable from the ARN, so `tenant_id`, `target_alias`, and `schedule_id` are passed explicitly in the monitor input. The redrive endpoint already holds the full DynamoDB record in memory, so this costs nothing extra.

---

## Implementation Plan

### 1. Shared module — `task-execution/execution_recorder.py` (new)

Extract from `postprocessing.py` into a shared module so both postprocessor and the new Lambda can use them without duplication:

- `record_execution(...)` — writes to TargetExecutionsTable via `put_item`
- `lookup_target_arn_from_dynamodb(tenant_id, target_alias)` — fallback ARN lookup
- `generate_console_url(...)` and its private helpers

`postprocessing.py` is updated to import these from `execution_recorder.py`. No behavior changes.

---

### 2. Monitor state machine — `task-execution/redrive_monitor_state_machine.json` (new)

```json
{
  "Comment": "Polls a redriven child Step Functions execution and records the result when complete.",
  "StartAt": "WaitForChildExecution",
  "States": {
    "WaitForChildExecution": {
      "Type": "Wait",
      "Seconds": 60,
      "Next": "CheckChildExecutionStatus"
    },
    "CheckChildExecutionStatus": {
      "Type": "Task",
      "Resource": "arn:aws:states:::aws-sdk:sfn:describeExecution",
      "Parameters": {
        "ExecutionArn.$": "$.child_execution_arn"
      },
      "ResultSelector": {
        "Status.$": "$.Status"
      },
      "ResultPath": "$.child_status_check",
      "Next": "IsChildExecutionComplete",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 10,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ]
    },
    "IsChildExecutionComplete": {
      "Type": "Choice",
      "Choices": [
        { "Variable": "$.child_status_check.Status", "StringEquals": "SUCCEEDED", "Next": "RecordResult" },
        { "Variable": "$.child_status_check.Status", "StringEquals": "FAILED",    "Next": "RecordResult" },
        { "Variable": "$.child_status_check.Status", "StringEquals": "TIMED_OUT", "Next": "RecordResult" },
        { "Variable": "$.child_status_check.Status", "StringEquals": "ABORTED",   "Next": "RecordResult" }
      ],
      "Default": "WaitForChildExecution"
    },
    "RecordResult": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "${RecordRedriveResultLambdaArn}",
        "Payload.$": "$"
      },
      "End": true,
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed", "Lambda.ServiceException"],
          "IntervalSeconds": 5,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ]
    }
  }
}
```

Input shape passed by the redrive endpoint:

```json
{
  "child_execution_arn": "arn:aws:states:...:execution:target-sm:uuid-nested",
  "tenant_id": "tenant_id",
  "target_alias": "target_alias",
  "schedule_id": "schedule_id"
}
```

The `child_status_check` object is merged into `$` by `ResultPath` so the full payload (including original fields) reaches `RecordRedriveResultLambda`.

---

### 3. Record Lambda — `task-execution/record_redrive_result.py` (new)

Receives the full monitor payload. Key differences from `postprocessing.py`:

- Context (`tenant_id`, `target_alias`, `schedule_id`) comes from the monitor input, not a parent `DescribeExecution`
- Derives `parent_execution_name` from `child_execution_arn` by stripping `-nested` — this is the DynamoDB SK
- Calls `DescribeExecution` on the **child** ARN (not the parent) for result details
- Child output is raw (not wrapped in `execution_result`/`target_arn` keys like the parent's `ResultSelector` output), so `target_arn` is always fetched via `lookup_target_arn_from_dynamodb()`
- For failures, `redrive_info.nested_execution_arn` is set directly to `child_execution_arn` (already known — no reconstruction needed)
- Calls `record_execution(state_machine_execution_arn=parent_execution_name, ...)` from `execution_recorder.py` — the `put_item` overwrites the IN_PROGRESS record using the same PK+SK

```python
def handler(event, context):
    child_execution_arn  = event['child_execution_arn']
    child_status         = event['child_status_check']['Status']
    tenant_id            = event['tenant_id']
    target_alias         = event['target_alias']
    schedule_id          = event['schedule_id']

    # Derive parent execution name (= DynamoDB SK) from child ARN
    parent_execution_name = child_execution_arn.split(':')[-1].removesuffix('-nested')

    child_execution = sfn_client.describe_execution(executionArn=child_execution_arn)
    target_arn = lookup_target_arn_from_dynamodb(tenant_id, target_alias)

    if child_status == 'SUCCEEDED':
        result       = json.loads(child_execution.get('output', '{}'))
        redrive_info = None
        failed_state = None
        our_status   = 'SUCCESS'
    else:
        result = {
            'Error': child_execution.get('error', child_status),
            'Cause': child_execution.get('cause', f'Execution {child_status.lower()}')
        }
        failed_state = child_execution.get('stopDate', 'Unknown')
        redrive_info = {
            'can_redrive': True,
            'nested_execution_arn': child_execution_arn,
            'message': f'Execution {child_status.lower()}. Can be redriven again.'
        }
        our_status = 'FAILED'

    record_execution(
        tenant_id=tenant_id,
        target_alias=target_alias,
        schedule_id=schedule_id,
        result=result,
        status=our_status,
        state_machine_execution_arn=parent_execution_name,
        execution_start_time=child_execution['startDate'].isoformat(),
        failed_state=failed_state,
        redrive_info=redrive_info,
        target_arn=target_arn
    )
```

---

### 4. Redrive endpoint — `api/app/routers/tenants.py`

After the existing `sfn_client.redrive_execution(...)` call succeeds and DynamoDB is updated to `IN_PROGRESS`, add a monitor start — only when `nested_execution_arn` is present (Step Functions targets only):

```python
monitor_arn = os.environ.get('REDRIVE_MONITOR_STATE_MACHINE_ARN')
if monitor_arn and nested_execution_arn:
    monitor_input = {
        'child_execution_arn': sfn_execution_arn,
        'tenant_id': tenant_id,
        'target_alias': target_alias,
        'schedule_id': execution_record.get('tenant_schedule', '').split('#', 1)[-1],
    }
    sfn_client.start_execution(
        stateMachineArn=monitor_arn,
        input=json.dumps(monitor_input, default=str)
    )
```

---

### 5. `template.yaml` additions

**New resources:**

| Resource | Type | Notes |
|----------|------|-------|
| `RedriveMonitorStateMachine` | `AWS::Serverless::StateMachine` | STANDARD type; `DefinitionSubstitutions: RecordRedriveResultLambdaArn` |
| `RedriveMonitorStateMachineRole` | `AWS::IAM::Role` | Needs `states:DescribeExecution` (`*`), `lambda:InvokeFunction` on record Lambda, CloudWatch Logs |
| `RedriveMonitorLogGroup` | `AWS::Logs::LogGroup` | 14-day retention |
| `RecordRedriveResultLambda` | `AWS::Serverless::Function` | 256MB, 30s, same env vars as postprocessor |
| `RecordRedriveResultLambdaRole` | `AWS::IAM::Role` | Needs `states:DescribeExecution` (`*`), DynamoDB `PutItem`/`GetItem` on executions + targets + mappings tables |
| `RecordRedriveResultLambdaLogGroup` | `AWS::Logs::LogGroup` | 14-day retention |

**Modified resources:**

| Resource | Change |
|----------|--------|
| `AppLambda` (Environment) | Add `REDRIVE_MONITOR_STATE_MACHINE_ARN: !Ref RedriveMonitorStateMachine` |
| `AppLambdaRole` | Add `states:StartExecution` on `!Ref RedriveMonitorStateMachine` |

---

## Implementation Summary

### Problem
When a Step Functions target execution is redriven via the API, the child execution is redriven directly. When the child completes, its EventBridge event carries the child's state machine ARN, which never matches the `ExecutionStatusEventRule` (scoped to `ExecutorStateMachine` only). The parent remains `FAILED`, postprocessor is never invoked, and DynamoDB stays `IN_PROGRESS` indefinitely.

### Solution
A `RedriveMonitorStateMachine` is started alongside every Step Functions target redrive. It polls the child execution using a native `aws-sdk:sfn:describeExecution` integration in a `Wait → DescribeExecution → Choice` loop until the child reaches a terminal state, then invokes `RecordRedriveResultLambda` to write the final result to DynamoDB, overwriting the `IN_PROGRESS` record.

The parent execution name (DynamoDB SK / `execution_id`) is derived at runtime inside `RecordRedriveResultLambda` by stripping the `-nested` suffix from the child execution name — no extra context needs to be reconstructed.

### Files Changed

**`task-execution/state_machine.json`** → **renamed** to `task-execution/executor_step_function.json`
- No content changes; renamed for clarity now that a second state machine exists alongside it.

**`task-execution/execution_recorder.py`** *(new)*
- Shared module extracted from `postprocessing.py` containing `record_execution()`, `lookup_target_arn_from_dynamodb()`, `generate_console_url()`, and their private helpers.
- Both `postprocessing.py` and the new `record_redrive_result.py` import from here so the DynamoDB write logic lives in one place.

**`task-execution/redrive_step_function.json`** *(new)*
- State machine definition for the redrive monitor.
- Uses the native `arn:aws:states:::aws-sdk:sfn:describeExecution` integration for polling — no Lambda needed for the status check itself.
- Loops via `Wait(60s) → DescribeExecution → Choice` until a terminal status is detected, then invokes `RecordRedriveResultLambda`.
- Retries on `DescribeExecution` failures (3 attempts, exponential backoff) and on the final Lambda invoke (3 attempts).

**`task-execution/record_redrive_result.py`** *(new)*
- Terminal Lambda invoked by `RedriveMonitorStateMachine` when the child execution completes.
- Derives `parent_execution_name` from `child_execution_arn` by stripping `-nested` from the last ARN segment. This is the DynamoDB SK (`execution_id`), so the `put_item` call overwrites the existing `IN_PROGRESS` record with the final status.
- `target_arn` is always fetched via `lookup_target_arn_from_dynamodb()` — child execution output does not carry this field (unlike the parent `ExecutorStateMachine` output shaped by `ResultSelector`).
- For failed child executions, `redrive_info.nested_execution_arn` is set directly to `child_execution_arn` (already known) rather than reconstructed.

**`task-execution/postprocessing.py`** *(modified)*
- Imports `record_execution()`, `lookup_target_arn_from_dynamodb()`, and `generate_console_url()` from `execution_recorder.py` instead of defining them locally.
- All existing behavior is unchanged.

**`template.yaml`** *(modified)*
- `ExecutorStateMachine.DefinitionUri` updated from `task-execution/state_machine.json` → `task-execution/executor_step_function.json`.
- `AppLambda` environment: added `REDRIVE_MONITOR_STATE_MACHINE_ARN` pointing to the new monitor state machine.
- `AppLambdaRole`: added `states:StartExecution` scoped to `RedriveMonitorStateMachine`.
- New log groups: `RecordRedriveResultLambdaLogGroup` (Lambda), `RedriveMonitorLogGroup` (Step Functions).
- New `RecordRedriveResultLambda` (256MB, 30s) with `RecordRedriveResultLambdaRole` — permissions for `states:DescribeExecution`, DynamoDB `PutItem`/`GetItem` on executions, targets, and mappings tables.
- New `RedriveMonitorStateMachine` (STANDARD type, X-Ray tracing, CloudWatch Logs) with `RedriveMonitorStateMachineRole` — permissions for `states:DescribeExecution` and `lambda:InvokeFunction` on the record Lambda.
- New Outputs: `RedriveMonitorStateMachineArn`, `RecordRedriveResultLambdaArn`.

**`api/app/routers/tenants.py`** *(modified)*
- Added `import json` to the `redrive_execution` function's local imports (needed for `json.dumps` on the monitor input).
- After a successful `sfn_client.redrive_execution()` call and DynamoDB `IN_PROGRESS` update, if `nested_execution_arn` is present (Step Functions targets only), `sfn_client.start_execution()` is called to start `RedriveMonitorStateMachine` with `child_execution_arn`, `tenant_id`, `target_alias`, and `schedule_id`.
- Monitor start failure is caught and logged as a warning — it does not fail the redrive API response, since the redrive itself already succeeded.
