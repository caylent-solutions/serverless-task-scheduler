# bug: Orphaned IN_PROGRESS Parent Executions After Successful Step Function Redrive

## Description

When a Step Functions target execution fails and is redriven, the parent execution record in DynamoDB is set to `IN_PROGRESS` at the start of the redrive. A `RedriveMonitorStateMachine` is supposed to watch the child execution and call `RecordRedriveResultLambda` to flip the parent record to `SUCCESS` or `FAILED` when the child reaches a terminal state.

However, if the `RedriveMonitorStateMachine` fails to start, the failure is silently swallowed as a warning ([`tenants.py` lines ~823-824](task-execution/record_redrive_result.py)):

```python
except Exception as e:
    logger.warning(f"Failed to start redrive monitor (redrive still succeeded): {e}")
```

This leaves the parent execution record permanently stuck at `IN_PROGRESS` in the executions table — even when the redriven child step function eventually succeeds. Over time this produces a backlog of orphaned `IN_PROGRESS` records that never resolve.

## Verified Assumptions

| Assumption | Status |
|---|---|
| Child execution name is parent name + `-nested` | ✅ Confirmed — `executor_step_function.json` line 95: `"Name.$": "States.Format('{}-nested', $$.Execution.Name)"` |
| `RecordRedriveResultLambda` derives parent name by stripping `-nested` | ✅ Confirmed — `record_redrive_result.py` lines 35–54 |
| Everything routes through `record_redrive_result` | ❌ No — normal (non-redriven) executions route through EventBridge → `PostprocessingLambda`. Only redriven SFN executions use `RecordRedriveResultLambda`. Both call the same shared `record_execution()` in `execution_recorder.py`. |
| `record_execution()` uses `put_item` to overwrite the `IN_PROGRESS` record | ✅ Confirmed — `execution_recorder.py` lines 148–149 |

## Root Cause

The `RedriveMonitorStateMachine` startup in [`tenants.py`](api/app/routers/tenants.py) is wrapped in a try/except that logs a warning and continues. There is no retry, no compensating write back to `FAILED`, and no subsequent mechanism to detect and resolve records that got stuck at `IN_PROGRESS`.

## Proposed Fix

### 1. Don't leave orphaned IN_PROGRESS on monitor startup failure

If the monitor fails to start, the execution will never be resolved. At minimum, the redrive endpoint should revert the DynamoDB record back to `FAILED` (with an appropriate error note) rather than leaving it `IN_PROGRESS`:

```python
except Exception as e:
    logger.warning(f"Failed to start redrive monitor: {e}")
    # Revert record back to FAILED so it doesn't appear orphaned
    # update_execution_status(execution_id, 'FAILED', error=str(e))
```

### 2. Add a reconciliation scan for orphaned IN_PROGRESS records

A periodic Lambda (or on-demand admin endpoint) should scan the executions table for records in `IN_PROGRESS` older than a configurable threshold (e.g. 1 hour), then for each:

1. Derive the child execution ARN by appending `-nested` to the parent execution name
2. Call `sfn:describeExecution` on the child
3. If the child is in a terminal state (`SUCCEEDED`, `FAILED`, `TIMED_OUT`, `ABORTED`), call `record_execution()` with the appropriate final status (same path as `RecordRedriveResultLambda`)
4. If the child is still `RUNNING`, leave the record as-is

This reconciler can also serve as a one-time cleanup for records already orphaned in existing deployments.

### 3. (Optional) Make monitor startup failure non-silent

Raise the warning to an error and emit a CloudWatch metric or alarm so orphaned records are detected operationally before they accumulate.

## Relevant Files

- [`api/app/routers/tenants.py`](api/app/routers/tenants.py) — redrive endpoint; monitor startup; IN_PROGRESS write (lines ~762–824)
- [`task-execution/record_redrive_result.py`](task-execution/record_redrive_result.py) — Lambda that records child result to parent DynamoDB record
- [`task-execution/execution_recorder.py`](task-execution/execution_recorder.py) — shared `record_execution()` used by both postprocessor and redrive result Lambda
- [`task-execution/redrive_step_function.json`](task-execution/redrive_step_function.json) — monitor state machine definition (polls child every 10s)
- [`task-execution/executor_step_function.json`](task-execution/executor_step_function.json) — confirms `-nested` naming convention (line 95)

## Acceptance Criteria

- [ ] If `RedriveMonitorStateMachine` fails to start, the execution record is reverted to `FAILED` (not left as `IN_PROGRESS`)
- [ ] A reconciliation mechanism exists to detect and resolve `IN_PROGRESS` records older than a configurable threshold by checking the child execution status directly
- [ ] Existing orphaned `IN_PROGRESS` records are resolved by the reconciler on first run
- [ ] `RecordRedriveResultLambda` behavior is unchanged for the normal (monitor-started) redrive path
