# ExecutorStepFunction - Visual Flow

This document provides a visual representation of the Step Functions state machine flow.

**Key Design**: Uses a Parallel state with a single branch to wrap the Choice/execution logic, allowing centralized error handling and post-processing. This significantly reduces visual graph complexity.

## Happy Path (Success Flow)

```
┌─────────────────────────────────────────────────────────┐
│  START                                                  │
│  Input: {tenant_id, target_alias, schedule_id, payload}│
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  Preprocessing                                          │
│  Type: Task (Lambda)                                    │
│  Function: preprocessing.py                             │
│  ┌─────────────────────────────────────────────────┐  │
│  │ • Query tenant mapping                          │  │
│  │ • Query target details                          │  │
│  │ • Merge default + runtime payloads              │  │
│  └─────────────────────────────────────────────────┘  │
│  Output: {                                              │
│    tenant_id, target_alias, schedule_id,                │
│    target_arn, target_type, target_config,              │
│    merged_payload                                       │
│  }                                                      │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  ExecuteTargetWithErrorHandling                         │
│  Type: Parallel (Single Branch)                         │
│  ┌─────────────────────────────────────────────────┐  │
│  │  BRANCH 1:                                      │  │
│  │  ┌───────────────────────────────────────────┐ │  │
│  │  │ TargetTypeChoice (Choice State)           │ │  │
│  │  │ Routes based on $.target_type             │ │  │
│  │  └─┬──────────┬──────────┬──────────────────┘ │  │
│  │    │          │          │                     │  │
│  │    │ lambda   │ ecs      │ stepfunctions       │  │
│  │    ↓          ↓          ↓                     │  │
│  │  ┌────────┐┌────────┐┌────────────────────┐  │  │
│  │  │Lambda  ││ECS     ││StepFunction        │  │  │
│  │  │Helper  ││Native  ││Native              │  │  │
│  │  └────────┘└────────┘└────────────────────┘  │  │
│  │  All execution paths end here ────────────►   │  │
│  └─────────────────────────────────────────────────┘  │
│                                                         │
│  ResultSelector extracts needed fields from branch     │
│  Catch → RecordFailure (centralized error handler)     │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  RecordSuccess                                          │
│  Type: Task (Lambda)                                    │
│  Function: postprocessing.py                            │
│  ┌─────────────────────────────────────────────────┐  │
│  │ • Write to DynamoDB                             │  │
│  │ • Status: SUCCESS                               │  │
│  │ • Include execution_id                          │  │
│  │ • Include CloudWatch URL (for Lambda)           │  │
│  └─────────────────────────────────────────────────┘  │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  ExecutionSucceeded                                     │
│  Type: Succeed                                          │
└─────────────────────────────────────────────────────────┘
```

## Error Path (Failure Flow)

```
┌─────────────────────────────────────────────────────────┐
│  Preprocessing                                          │
└───────────────────────┬─────────────────────────────────┘
                        │ (on error)
                        ↓
                   ┌─────────┐
                   │ Catch   │
                   └────┬────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  RecordFailure (CENTRALIZED)                            │
│  Type: Task (Lambda)                                    │
│  ┌─────────────────────────────────────────────────┐  │
│  │ • Write to DynamoDB                             │  │
│  │ • Status: FAILED                                │  │
│  │ • failed_state: Name of failed state            │  │
│  │ • error: Full error object                      │  │
│  │ • redrive_info: {                               │  │
│  │     can_redrive: true,                          │  │
│  │     redrive_from_state: (failed state name)     │  │
│  │   }                                             │  │
│  └─────────────────────────────────────────────────┘  │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  ExecutionFailed                                        │
│  Type: Fail                                             │
│  Error: "TargetExecutionFailed"                         │
└─────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────┐
│  ExecuteTargetWithErrorHandling (Parallel State)        │
│  Any error in the branch (Lambda/ECS/SFN execution)     │
└───────────────────────┬─────────────────────────────────┘
                        │ (on error)
                        ↓
                   ┌─────────┐
                   │ Catch   │
                   └────┬────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  RecordFailure (SAME STATE AS ABOVE)                    │
│  Type: Task (Lambda)                                    │
│  Handles ALL execution failures in one place            │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  ExecutionFailed                                        │
│  Type: Fail                                             │
└─────────────────────────────────────────────────────────┘
```

## State Machine States

| State Name | Type | Description | Error Handling |
|------------|------|-------------|----------------|
| Preprocessing | Task | Resolve target and merge payloads | Catch → RecordFailure |
| ExecuteTargetWithErrorHandling | Parallel | Wraps execution logic for centralized error handling | Catch → RecordFailure |
| TargetTypeChoice | Choice | Route to appropriate executor (inside Parallel branch) | N/A |
| ExecuteLambdaTarget | Task | Execute Lambda via helper (inside Parallel branch) | Bubbles up to Parallel Catch |
| ExecuteECSTarget | Task | Execute ECS via native integration (inside Parallel branch) | Bubbles up to Parallel Catch |
| ExecuteStepFunctionTarget | Task | Execute SFN via native integration (inside Parallel branch) | Bubbles up to Parallel Catch |
| RecordSuccess | Task | Record success to DynamoDB | None |
| RecordFailure | Task | **CENTRALIZED** failure recording with redrive info | None |
| UnsupportedTargetType | Fail | Invalid target type specified (inside Parallel branch) | Terminal |
| ExecutionFailed | Fail | Execution failed (after recording) | Terminal |
| ExecutionSucceeded | Succeed | Execution completed successfully | Terminal |

**Total States**: 11 (reduced from 14 in previous design)
**Recording States**: 2 (RecordSuccess, RecordFailure) - down from 3

## Benefits of Parallel State Pattern

### Visual Simplification
The Parallel state with a single branch acts as a "try-catch" block:
- **Before**: 3 execution states × 2 error paths = 6 error transitions + 3 success transitions = 9 arrows
- **After**: 1 error path + 1 success path = 2 arrows from the Parallel state

### Code Maintainability
- **Single error handler**: All execution failures route to one `RecordFailure` state
- **No duplication**: Error recording logic written once, not per target type
- **Easier to extend**: Add new target types inside the Parallel branch without adding new error paths

### Visual Graph in Step Functions Console
```
Before (messy):
  Preprocessing → Choice → [Lambda, ECS, SFN]
                    ↓↓↓      ↓↓↓     ↓↓↓
              RecordFailure RecordSuccess
                    ↓            ↓
                  Fail       Succeed

After (clean):
  Preprocessing → Parallel[Choice → Lambda/ECS/SFN] → RecordSuccess → Succeed
       ↓                      ↓
  RecordFailure → Fail
```

The Parallel state "collapses" the internal complexity into a single visual box!

## Data Flow

### Input Format (from EventBridge Scheduler)
```json
{
  "tenant_id": "jer",
  "target_alias": "calculator",
  "schedule_id": "daily-calculation",
  "payload": {
    "operation": "add",
    "numbers": [1, 2, 3]
  }
}
```

### After Preprocessing
```json
{
  "tenant_id": "jer",
  "target_alias": "calculator",
  "schedule_id": "daily-calculation",
  "target_id": "calc-target",
  "target_arn": "arn:aws:lambda:us-east-1:123456789012:function:calculator",
  "target_type": "lambda",
  "target_config": {},
  "merged_payload": {
    "operation": "add",
    "numbers": [1, 2, 3],
    "default_key": "default_value"
  },
  "default_payload": {
    "default_key": "default_value"
  },
  "runtime_payload": {
    "operation": "add",
    "numbers": [1, 2, 3]
  }
}
```

### After Target Execution (Lambda)
```json
{
  // ... all previous fields ...
  "execution_result": {
    "execution_id": "a1b2c3d4-5e6f-7g8h-9i0j-1k2l3m4n5o6p",
    "target_type": "lambda",
    "response": {
      "statusCode": 200,
      "body": "{\"result\": 6}"
    },
    "status_code": 200,
    "function_name": "calculator",
    "cloudwatch_logs_url": "https://console.aws.amazon.com/cloudwatch/..."
  }
}
```

### After RecordExecutionSuccess
```json
{
  // ... all previous fields ...
  "record_result": {
    "status": "recorded",
    "execution_id": "2025-01-15T10:00:00.000Z#a1b2c3d4-5e6f-7g8h-9i0j-1k2l3m4n5o6p"
  }
}
```

### Error Object (on failure)
```json
{
  // ... all previous fields ...
  "error": {
    "Error": "Lambda.ServiceException",
    "Cause": "{\"errorMessage\":\"Task timed out after 30.00 seconds\"}"
  }
}
```

## Redrive Workflow

When an execution fails and needs to be redriven:

```
1. User views failed execution in UI
   └─> Sees: failed_state, error details, can_redrive: true

2. User clicks "Redrive" button
   └─> UI calls: aws stepfunctions redrive-execution
       --execution-arn <arn>

3. Step Functions creates new execution
   └─> Copies input from failed execution
   └─> Skips already-succeeded states
   └─> Starts from failed state

4. Redriven execution proceeds normally
   └─> If succeeds: RecordExecutionSuccess
   └─> If fails again: RecordExecutionFailure (can redrive again)
```

## Comparison with LambdaExecutor

| Aspect | LambdaExecutor | ExecutorStepFunction |
|--------|---------------|---------------------|
| Architecture | Single Lambda function | Step Functions + 3 Lambdas |
| Visibility | CloudWatch Logs only | Visual workflow + logs |
| Error Handling | Try-catch in code | Catch blocks per state |
| Redrive | Manual re-invocation | Native Step Functions redrive |
| Debugging | Parse logs | View state input/output |
| Extensibility | Modify code | Add states |
| Cost | $0.20 per 1M requests | $25 per 1M state transitions (4-6 per execution) |
| Timeout | 15 minutes max | 1 year max |
| Long-running | Not suitable | Excellent for ECS tasks |
