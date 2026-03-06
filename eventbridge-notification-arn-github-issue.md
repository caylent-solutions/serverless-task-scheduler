# feat: EventBridge Execution Notification ARN on Target Alias Configuration

## Background

Customers have asked for status notifications when a scheduled target alias execution completes. Rather than building a specific notification mechanism into the scheduler, the cleanest approach is to allow an optional **EventBridge event bus ARN** to be configured per target alias (tenant mapping). When an execution completes, the scheduler posts a structured event to that bus — and the implementation team wires up whatever notification system they want (SNS, Lambda, SQS, email, Slack, etc.) as a rule on that bus.

This keeps the scheduler generic and unopinionated about notification delivery, while giving teams a well-defined integration point.

## Proposed Design

### New Field: `eventbridge_notification_arn`

Add an optional field to the **TenantMapping** model (per tenant + target alias combination):

```python
eventbridge_notification_arn: Optional[str] = None
```

This is placed on the tenant mapping (not on the target or schedule) because notification routing is a per-tenant, per-alias concern — different tenants running the same target may want notifications delivered to different buses.

### Notification Event Contract

When an execution completes (success or failure), the scheduler posts the following event to the configured bus:

```json
{
  "Source": "custom.taskscheduler",
  "DetailType": "ExecutionComplete",
  "EventBusName": "<configured ARN>",
  "Detail": {
    "tenant_id": "acme",
    "target_alias": "nightly-report",
    "schedule_id": "sched-abc123",
    "execution_id": "arn:aws:states:...:execution:...",
    "status": "SUCCESS | FAILED | TIMED_OUT | ABORTED",
    "timestamp": "2024-01-15T02:00:01Z",
    "result": { ... }
  }
}
```

This contract is stable — implementation teams can build EventBridge rules matching on `Source`, `DetailType`, and `detail.tenant_id` or `detail.target_alias` to route to their notification targets.

## Data Flow

```
TenantMapping (DynamoDB)
  └─ eventbridge_notification_arn stored per tenant+alias

PreprocessingLambda (on execution start)
  └─ resolve_target() already queries TenantMappingsTable
  └─ retrieve eventbridge_notification_arn from mapping
  └─ include in preprocessing output → flows into executor state machine output
  └─ also store in the initial IN_PROGRESS execution record (for redrive path)

ExecutorStateMachine (executor_step_function.json)
  └─ thread eventbridge_notification_arn through Parallel state ResultSelector
  └─ present in final execution output available to postprocessor

PostprocessingLambda (on execution terminal state via EventBridge rule)
  └─ describe_execution() retrieves output (already done)
  └─ extract eventbridge_notification_arn from output
  └─ after record_execution(), if ARN present: events.put_events(...)

RecordRedriveResultLambda (on redriven SFN execution completion)
  └─ retrieve eventbridge_notification_arn from the existing execution record in DynamoDB
     (stored during preprocessing — avoids threading through monitor state machine)
  └─ after record_execution(), if ARN present: events.put_events(...)
```

## Required Changes

### 1. Data Model — `api/app/models/tenantmapping.py`
- Add `eventbridge_notification_arn: Optional[str] = None`

### 2. Preprocessing Lambda — `task-execution/preprocessing.py`
- In `resolve_target()`, return `eventbridge_notification_arn` from the TenantMapping item
- Include it in the preprocessing output dict
- Store it in the initial `IN_PROGRESS` execution record written to `TargetExecutionsTable` (needed by the redrive path — see item 6)

### 3. Executor State Machine — `task-execution/executor_step_function.json`
- Add `eventbridge_notification_arn` to the `ResultSelector` of the `ExecuteTargetWithErrorHandling` Parallel state so it flows through to the final execution output

### 4. Postprocessing Lambda — `task-execution/postprocessing.py`
- After `describe_execution()`, extract `eventbridge_notification_arn` from execution output
- After `record_execution()` succeeds, if ARN is non-empty, call `events.put_events()` with the notification payload
- Handle `events.put_events()` failure gracefully — log a warning but do not fail the postprocessor (notification delivery is best-effort)

### 5. Record Redrive Result Lambda — `task-execution/record_redrive_result.py`
- After `record_execution()`, look up `eventbridge_notification_arn` from the existing execution record in DynamoDB (already retrieved during the record update)
- If present, call `events.put_events()` with the same notification payload structure

### 6. IAM Permissions — `template.yaml`
- Add `events:PutEvents` to **PostprocessingLambdaRole**:
  ```yaml
  - Effect: Allow
    Action:
      - events:PutEvents
    Resource:
      - !Sub 'arn:aws:events:${AWS::Region}:${AWS::AccountId}:event-bus/*'
  ```
- Add the same to **RecordRedriveResultLambdaRole**

### 7. UI — `ui-vite/src/components/tenants/TenantMappingList.jsx`
- Add an optional "Notification Event Bus ARN" input field to the mapping edit form (right column, below default payload)
- Include basic ARN format hint/placeholder: `arn:aws:events:us-east-1:123456789012:event-bus/my-bus`
- Field is optional — no required validation
- Include in `prepareMappingData()` serialization

## Notes

- **Event bus ARN, not rule ARN.** `PutEvents` targets a bus; rules are attached to the bus by the implementation team. The field name and placeholder should make this clear in the UI.
- **Notification delivery is best-effort.** A failure to post to EventBridge should not fail the execution record. Log the error and continue.
- **No change to `execution_recorder.py`** — the notification is fired by the postprocessor/redrive Lambda after recording, not inside the recorder itself.
- **Redrive path does not need the ARN threaded through the monitor state machine.** Storing it in the initial `IN_PROGRESS` execution record (step 2 above) is sufficient — `RecordRedriveResultLambda` can read it from the record it's about to overwrite.

## Acceptance Criteria

- [ ] `eventbridge_notification_arn` field exists on TenantMapping model and is persisted to/from DynamoDB
- [ ] UI exposes an optional "Notification Event Bus ARN" field on the target alias configuration form
- [ ] When an execution completes (success or failure), if a notification ARN is configured, an event is posted to that bus with the defined contract (`Source`, `DetailType`, `Detail` fields)
- [ ] Notification is sent for both normal executions (via PostprocessingLambda) and redriven Step Functions executions (via RecordRedriveResultLambda)
- [ ] A `PutEvents` failure does not fail or retry the execution record — it is logged as a warning only
- [ ] `PostprocessingLambdaRole` and `RecordRedriveResultLambdaRole` both have `events:PutEvents` on `event-bus/*`
- [ ] If `eventbridge_notification_arn` is absent or empty, no EventBridge call is made (no behavior change for existing configurations)
