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

### Files changed

```
task-execution/
├── execution_recorder.py                 (new) shared functions extracted from postprocessing.py
├── record_redrive_result.py              (new) terminal Lambda for monitor
├── redrive_monitor_state_machine.json    (new) monitor state machine definition
└── postprocessing.py                     (modified) imports from execution_recorder.py

template.yaml                             (modified) 6 new resources, 2 modified resources

api/app/routers/tenants.py               (modified) start monitor after successful SF redrive
```
