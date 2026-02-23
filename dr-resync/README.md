# DR Resync Lambda

Disaster Recovery Resync Lambda for resyncing EventBridge Scheduler schedules during regional failover.

## Overview

This Lambda function recreates EventBridge schedules in the secondary region during a DR failover event. It reads all schedules from the DynamoDB Global Tables (which are automatically replicated) and recreates the corresponding EventBridge Scheduler schedules in the active region.

## Usage

### Enable Region (Active the DR region)
```bash
aws lambda invoke \
  --function-name sts-prod-dr-resync-XXXXX \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable"}' \
  response.json
```

### Disable Region (Deactivate the DR region)
```bash
aws lambda invoke \
  --function-name sts-prod-dr-resync-XXXXX \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "disable"}' \
  response.json
```

### Validate Region (Check consistency without changes)
```bash
aws lambda invoke \
  --function-name sts-prod-dr-resync-XXXXX \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "validate"}' \
  response.json
```

### Dry Run (Preview changes without executing)
```bash
aws lambda invoke \
  --function-name sts-prod-dr-resync-XXXXX \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable", "dry_run": true}' \
  response.json
```

### Sync Specific Tenant
```bash
aws lambda invoke \
  --function-name sts-prod-dr-resync-XXXXX \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable", "tenant_id": "acme"}' \
  response.json
```

## Input Parameters

- **mode** (required): Operation mode
  - `enable`: Create EventBridge schedules from DynamoDB Schedules table
  - `disable`: Delete EventBridge schedules from the region
  - `validate`: Dry-run, check consistency between DynamoDB and EventBridge

- **dry_run** (optional, default: false): If true, report actions without executing

- **tenant_id** (optional): Filter to specific tenant (default: all tenants)

## Response Format

```json
{
  "status": "success|partial|failure",
  "mode": "enable|disable|validate",
  "region": "us-east-1",
  "execution_time": "2026-02-19T15:30:45Z",
  "duration_seconds": 45.2,
  "summary": {
    "total_schedules": 1523,
    "processed": 1523,
    "created": 1520,
    "skipped": 3,
    "failed": 0,
    "missing_targets": 0,
    "missing_mappings": 0
  },
  "errors": [
    {
      "tenant_id": "acme",
      "schedule_id": "daily-email",
      "error": "Target not found in regional Targets table"
    }
  ],
  "warnings": []
}
```

## Architecture

```
DynamoDB Global Tables (Auto-replicated)
├─ Schedules table
├─ TenantMappings table
└─ Targets table (regional)

         ↓ Scans & Validates ↓

   DR Resync Lambda
   (uses AppLambdaRole)
   (reuses awssdk modules)

         ↓ Creates ↓

EventBridge Scheduler (regional)
├─ Schedule Group (sts-{env}-schedules)
└─ Individual Schedules
```

## Behavior Details

### Enable Mode
1. Scans DynamoDB Schedules table
2. For each schedule:
   - Validates TenantMapping exists (tenant_id + target_alias)
   - Validates Target exists in regional Targets table
   - Gets target ARN
   - Creates EventBridge schedule (skips if already exists)
   - Throttles at 10 calls/second (100ms between calls)
3. Returns summary with created/skipped/failed counts

### Disable Mode
1. Scans DynamoDB Schedules table
2. For each schedule:
   - Deletes corresponding EventBridge schedule
   - Skips if schedule doesn't exist (idempotent)
3. Returns summary with deleted/skipped counts

### Validate Mode
1. Scans DynamoDB Schedules table
2. For each schedule:
   - Checks if corresponding EventBridge schedule exists
   - Reports missing schedules as warnings
3. Does NOT create or modify anything

## Error Handling

- **Missing Target**: Logs error, skips schedule, continues with others
- **Missing TenantMapping**: Logs error, skips schedule, continues with others
- **Schedule Already Exists** (enable): Logs as skipped (idempotent)
- **Schedule Doesn't Exist** (disable): Logs as skipped (idempotent)
- **EventBridge Throttling**: Built-in 100ms delay between API calls

## Throttling

- **Rate**: 10 API calls per second
- **Delay**: 100ms between consecutive API calls
- **Purpose**: Prevents overwhelming EventBridge Scheduler API
- **Suitable for**: Up to ~10,000 schedules per 15-minute timeout

## IAM Permissions

Reuses `AppLambdaRole` which includes:
- DynamoDB: Query, Scan, GetItem on Schedules, TenantMappings, Targets tables
- EventBridge Scheduler: CreateSchedule, DeleteSchedule, GetSchedule, ListSchedules
- IAM: PassRole (for scheduler role)

No additional permissions needed.

## Deployment

Deployed via CloudFormation SAM template:
```yaml
DRResyncLambda:
  Type: AWS::Serverless::Function
  Properties:
    FunctionName: sts-{env}-dr-resync-XXXXX
    Runtime: python3.13
    Timeout: 900  # 15 minutes
    Memory: 512 MB
    Role: AppLambdaRole  # Reused
```

## Typical DR Failover Workflow

1. **Detect** primary region failure
2. **Point** API Gateway to secondary region
3. **Invoke** DR Resync Lambda in secondary region:
   ```bash
   aws lambda invoke \
     --region us-west-2 \
     --function-name sts-prod-dr-resync-... \
     --cli-binary-format raw-in-base64-out \
     --payload '{"mode": "enable"}' \
     response.json
   ```
4. **Monitor** response for creation success
5. **Verify** schedules are running in secondary region
6. **Resume** operations from secondary region

## Testing

### Test Enable Mode (Dry Run)
```bash
aws lambda invoke \
  --function-name sts-prod-dr-resync-XXXXX \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable", "dry_run": true}' \
  response.json && cat response.json | jq .
```

### Test Validate Mode (No Changes)
```bash
aws lambda invoke \
  --function-name sts-prod-dr-resync-XXXXX \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "validate"}' \
  response.json && cat response.json | jq .
```

### Test with Specific Tenant
```bash
aws lambda invoke \
  --function-name sts-prod-dr-resync-XXXXX \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable", "tenant_id": "test-tenant"}' \
  response.json && cat response.json | jq .
```

## Monitoring

Lambda execution logs available in CloudWatch:
- Log Group: `/aws/lambda/sts-{env}-dr-resync-XXXXX`
- Retention: 14 days
- Log Entries: One per schedule processed + summary

Check logs for:
- `Successfully created schedule: ...` → Schedule created
- `Schedule already exists: ...` → Schedule was skipped
- `Target not found: ...` → Validation error
- `Tenant mapping not found: ...` → Data inconsistency
