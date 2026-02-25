# DR Resync Lambda

Disaster Recovery Resync Lambda for managing EventBridge Scheduler schedules during regional failover.

## Overview

This Lambda function recreates or removes EventBridge Scheduler schedules in the DR region during a failover event. It reads all schedule records from the DynamoDB Global Tables (automatically replicated across regions) and creates the corresponding EventBridge Scheduler schedules targeting the DR region's **Executor State Machine** — matching the same pattern used by the API Lambda when schedules are created normally.

## Architecture

```
DynamoDB Global Tables (replicated)
├─ Schedules table       → source of truth for all schedules
├─ TenantMappings table  → maps tenant_id + target_alias → target_id
└─ Targets table         → validates the target exists in this region

         ↓ Scans & Validates ↓

   DR Resync Lambda
   ├─ Shares DynamoDBClient + EventBridgeScheduler from api/app/awssdk/
   ├─ Uses DB_TARGET=aws (DynamoDBClient connects to AWS, not localhost)
   └─ Built via SAM Makefile build (copies api/app/ into artifact)

         ↓ Creates/Deletes ↓

EventBridge Scheduler (regional)
├─ Schedule Group: {SCHEDULER_GROUP_NAME}-{tenant_id}  (per-tenant groups)
├─ Schedule Name:  {schedule_id}  (UUID, same as in DynamoDB)
└─ Target: STEP_FUNCTIONS_EXECUTOR_ARN
           └─ Input: { tenant_id, target_alias, schedule_id, payload }
```

### Key Design Points

- **EventBridge target is always the Executor State Machine**, not the target's own ARN. The executor receives `target_alias` in its input and resolves the actual target itself. This matches how the API creates schedules.
- **Schedule groups are not CloudFormation-managed.** They are created on-demand by `ensure_schedule_group_exists()` and persist independently of the stack lifecycle. Orphaned schedules can accumulate if stacks are rebuilt without running `disable` first (see [Runbook](#runbook)).
- **The Schedules table is scanned with raw boto3** because `DynamoDBClient.get_all_schedules()` is per-tenant; no cross-tenant method exists in the shared client. All other data access goes through the API's `DynamoDBClient`.

## Environment Variables

| Variable | Source | Purpose |
|---|---|---|
| `DYNAMODB_TABLE` | `!Ref TargetsTable` | Targets table name |
| `DYNAMODB_TENANT_TABLE` | `!Ref TenantMappingsTable` | TenantMappings table name |
| `DYNAMODB_SCHEDULES_TABLE` | `!Ref SchedulesTable` | Schedules table name |
| `DB_TARGET` | `aws` (hardcoded) | Tells DynamoDBClient to connect to AWS (not localhost) |
| `SCHEDULER_ROLE_ARN` | `!GetAtt EventBridgeSchedulerRole.Arn` | IAM role passed to EventBridge for schedule execution |
| `SCHEDULER_GROUP_NAME` | `!Sub ${StackName}-${Environment}-schedules` | Base group name; tenant suffix appended at runtime |
| `STEP_FUNCTIONS_EXECUTOR_ARN` | `!GetAtt ExecutorStateMachine.Arn` | ARN of the Executor Step Functions in this region |

## Usage

Replace `{FUNCTION_NAME}` with the value of the `DRResyncLambdaName` CloudFormation output.

### Enable Region (activate DR)
```bash
aws lambda invoke \
  --region us-east-2 \
  --function-name {FUNCTION_NAME} \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable"}' \
  response.json && cat response.json | jq .
```

### Disable Region (deactivate DR)
```bash
aws lambda invoke \
  --region us-east-2 \
  --function-name {FUNCTION_NAME} \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "disable"}' \
  response.json && cat response.json | jq .
```

### Validate Region (check consistency, no changes)
```bash
aws lambda invoke \
  --region us-east-2 \
  --function-name {FUNCTION_NAME} \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "validate"}' \
  response.json && cat response.json | jq .
```

### Dry Run (preview without executing)
```bash
aws lambda invoke \
  --region us-east-2 \
  --function-name {FUNCTION_NAME} \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable", "dry_run": true}' \
  response.json && cat response.json | jq .
```

### Scope to a single tenant
```bash
aws lambda invoke \
  --region us-east-2 \
  --function-name {FUNCTION_NAME} \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable", "tenant_id": "acme"}' \
  response.json && cat response.json | jq .
```

## Input Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `mode` | string | Yes | — | `enable`, `disable`, or `validate` |
| `dry_run` | boolean | No | `false` | Preview actions without making changes |
| `tenant_id` | string | No | `null` | Restrict to a single tenant (default: all tenants) |

## Response Format

```json
{
  "status": "success|partial|failure",
  "mode": "enable|disable|validate",
  "region": "us-east-2",
  "execution_time": "2026-02-25T21:15:41Z",
  "duration_seconds": 12.4,
  "summary": {
    "total_schedules": 150,
    "processed": 150,
    "created": 148,
    "skipped": 2,
    "failed": 0,
    "missing_targets": 0,
    "missing_mappings": 0
  },
  "errors": [],
  "warnings": []
}
```

**Status values:**
- `success` — all schedules processed without failures
- `partial` — some succeeded, some failed
- `failure` — all failed, or a fatal error occurred

## Behavior Details

### Enable Mode
1. Scans DynamoDB Schedules table (all tenants, or filtered by `tenant_id`)
2. For each schedule:
   - Looks up `TenantMapping` (tenant_id + target_alias) via `DynamoDBClient`
   - Validates the `Target` exists in this region's Targets table via `DynamoDBClient`
   - Ensures the tenant's schedule group exists (creates it if not)
   - Creates the EventBridge schedule targeting `STEP_FUNCTIONS_EXECUTOR_ARN`
   - Skips (idempotent) if the schedule already exists
   - Throttles at 100ms between calls (~10 calls/sec)
3. Returns summary with created/skipped/failed counts

### Disable Mode
1. Scans DynamoDB Schedules table
2. For each schedule:
   - Deletes the corresponding EventBridge schedule
   - Skips (idempotent) if the schedule doesn't exist
3. Returns summary with deleted/skipped counts

### Validate Mode
1. Scans DynamoDB Schedules table
2. For each schedule:
   - Checks whether the schedule exists in EventBridge
   - Reports missing schedules as warnings (does not create or modify anything)
3. Returns `success` if all schedules exist in EventBridge, `partial` if any are missing

## Error Handling

| Condition | Behavior |
|---|---|
| Missing TenantMapping | Logs warning, marks as `error` with reason `missing_mapping`, continues |
| Missing Target | Logs warning, marks as `error` with reason `missing_target`, continues |
| Schedule already exists (enable) | Marked as `skipped` — idempotent |
| Schedule not found (disable) | Marked as `skipped` — idempotent |
| EventBridge API error | Logged, marked as `failed`, processing continues |
| Fatal scan/init error | Returns `failure` status immediately |

## Throttling

- **Rate**: 10 EventBridge API calls per second (100ms delay between calls)
- **Lambda timeout**: 900 seconds (15 minutes)
- **Capacity**: Handles ~9,000 schedules within the timeout window

## Build System

The DR Resync Lambda uses a **SAM Makefile build** (`BuildMethod: makefile`) rather than the standard SAM Python builder. This is because the Lambda imports from `api/app/awssdk/` (shared with the API Lambda), which lives outside the `dr-resync/` directory.

The [Makefile](Makefile) `build-DRResyncLambda` target:
1. Installs dependencies from `requirements.txt` using the `manylinux2014_x86_64 / Python 3.13` platform target (ensures binary wheels match the Lambda runtime, regardless of the local Python version)
2. Copies the Lambda source files into the artifact
3. Copies `api/app/__init__.py`, `api/app/validation.py`, `api/app/awssdk/`, and `api/app/models/` into the artifact so that `from app.awssdk.dynamodb import get_database_client` resolves correctly at runtime

**Requirement**: `make` must be available on the build machine. `quickdeploy.sh` checks for this automatically.

## Deployment

```bash
# Build and deploy via quickdeploy
./quickdeploy.sh

# Or build only
sam build

# Or deploy to a specific region
sam deploy --region us-east-2
```

## Runbook

### DR Failover (activate secondary region)

1. Confirm the primary region is degraded and DynamoDB Global Table replication is current
2. Update DNS / API Gateway routing to point to the secondary region
3. Run DR Resync **enable** in the secondary region:
   ```bash
   aws lambda invoke \
     --region {DR_REGION} \
     --function-name {FUNCTION_NAME} \
     --cli-binary-format raw-in-base64-out \
     --payload '{"mode": "enable"}' \
     response.json && cat response.json | jq .
   ```
4. Confirm `status: success` and review the summary
5. Run **validate** to cross-check EventBridge against DynamoDB:
   ```bash
   aws lambda invoke \
     --region {DR_REGION} \
     --function-name {FUNCTION_NAME} \
     --cli-binary-format raw-in-base64-out \
     --payload '{"mode": "validate"}' \
     response.json && cat response.json | jq .
   ```

### DR Failback (return to primary region)

1. Run DR Resync **disable** in the secondary region before tearing down the stack:
   ```bash
   aws lambda invoke \
     --region {DR_REGION} \
     --function-name {FUNCTION_NAME} \
     --cli-binary-format raw-in-base64-out \
     --payload '{"mode": "disable"}' \
     response.json && cat response.json | jq .
   ```
2. Confirm `status: success`
3. Restore DNS / API Gateway routing to the primary region
4. Proceed with `cloudformation delete-stack` if tearing down the DR stack

> **Important:** Always run `disable` before deleting the CloudFormation stack. EventBridge schedule groups and schedules are **not** CloudFormation-managed — they are created by the application and persist independently of the stack. Deleting the stack without running `disable` first will leave orphaned EventBridge schedules that cannot be cleaned up by CloudFormation and may conflict with future deployments.

## Monitoring

- **Log Group**: `/aws/lambda/{FUNCTION_NAME}` (14-day retention)
- **Key log messages**:
  - `ResyncManager initialized` — Lambda started successfully
  - `Successfully created schedule: {id}` — schedule created in EventBridge
  - `Schedule already exists: {id}` — skipped (idempotent)
  - `Successfully deleted schedule: {id}` — schedule removed from EventBridge
  - `Tenant mapping not found: {tenant}/{alias}` — data consistency issue
  - `Target not found: {target_id}` — target missing from regional Targets table
