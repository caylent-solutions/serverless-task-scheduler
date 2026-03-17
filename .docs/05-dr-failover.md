# Part 5: Disaster Recovery Failover Process

---

## DR Architecture Overview

The Serverless Task Scheduler supports **active-passive multi-region DR** using:

- **DynamoDB Global Tables** for automatic data replication
- **DR Resync Lambda** to manage EventBridge schedules during failover
- **Alias-based scheduling** for seamless regional target resolution

![DR Architecture](img/dr-architecture.png)

---

## Regional Resource Layout

| Resource | Primary (us-east-2) | DR (us-west-2) |
|----------|-------------------|-----------------|
| API Gateway + Lambdas | **Active**, receiving traffic | Deployed, idle |
| DynamoDB Global Tables | Source | Auto-replicated replica |
| DynamoDB Targets table | Regional ARNs (us-east-2) | Regional ARNs (us-west-2) |
| EventBridge Schedules | **Active** | **None until failover** |
| Cognito User Pool | Active | Separate pool (same users) |
| Step Functions | Active | Deployed, idle |

---

## Why Alias-Based Scheduling Enables Seamless Failover

This is the key architectural insight that makes DR work without schedule modification:

```
Schedule stores: target_alias = "send-email"  (NOT an ARN)
                          │
                          ▼
    Preprocessing Lambda resolves at runtime:
        alias → target_id → ARN
                          │
                          ▼
    Uses the LOCAL region's Targets table
                          │
              ┌───────────┴───────────┐
              │                       │
         us-east-2                us-west-2
    arn:aws:lambda:           arn:aws:lambda:
    us-east-2:...:            us-west-2:...:
    email-sender              email-sender
```

**Schedules never contain hard-coded ARNs.** They contain aliases that are resolved at runtime against the local region's Targets table. As long as the DR Targets table has valid us-west-2 ARNs for the same `target_id` values, schedules execute correctly in either region without modification.

---

## The DR Resync Lambda

The DR Resync Lambda is the control mechanism for failover. It operates in three modes:

### `enable` -- Activate DR Region

Reads all schedules from DynamoDB Global Tables (already replicated) and creates corresponding EventBridge schedules in the DR region.

```bash
aws lambda invoke \
  --region us-west-2 --function-name $DR_RESYNC \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable"}' \
  response.json && cat response.json | jq .
```

**Response:**
```json
{
  "status": "success",
  "summary": {
    "total_schedules": 47,
    "created": 47,
    "skipped": 0,
    "errors": 0
  }
}
```

### `disable` -- Deactivate Region

Deletes all EventBridge schedules in the region to prevent duplicate executions.

```bash
aws lambda invoke \
  --region us-west-2 --function-name $DR_RESYNC \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "disable"}' \
  response.json && cat response.json | jq .
```

### `validate` -- Check Consistency

Verifies that every DynamoDB schedule has a corresponding EventBridge schedule and all targets are resolvable. Safe to run at any time, makes no changes.

```bash
aws lambda invoke \
  --region us-west-2 --function-name $DR_RESYNC \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "validate"}' \
  response.json && cat response.json | jq .
```

| Response Field | Meaning |
|---------------|---------|
| `status: success` | All schedules have corresponding EventBridge entries and resolvable targets |
| `status: partial` | Some schedules missing -- check `warnings` |
| `summary.missing_targets` | Schedules whose `target_id` is absent from the regional Targets table |
| `summary.missing_mappings` | Schedules with no matching TenantMapping |

**Scope to a single tenant:** `{"mode": "validate", "tenant_id": "acme"}`

---

## Failover Procedure (Primary → DR)

### Pre-Failover Checklist

- [ ] DynamoDB Global Table replication is current (check replica lag in AWS Console)
- [ ] DR stack is deployed in us-west-2
- [ ] All targets are registered in the DR region Targets table with us-west-2 ARNs
- [ ] DR Resync `validate` returns `status: success`

### Step 1: Dry Run (Preview)

```bash
aws lambda invoke \
  --region us-west-2 --function-name $DR_RESYNC \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable", "dry_run": true}' \
  response.json && cat response.json | jq .
```

Confirm `summary.total_schedules` matches expectations.

### Step 2: Enable DR Region

```bash
aws lambda invoke \
  --region us-west-2 --function-name $DR_RESYNC \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable"}' \
  response.json && cat response.json | jq .
```

Confirm `"status": "success"` and `created` matches `total_schedules`.

### Step 3: Route Traffic to DR

Update DNS / API Gateway custom domain to the DR API URL:

```bash
aws cloudformation describe-stacks \
  --stack-name {DR_STACK_NAME} --region us-west-2 \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" \
  --output text
```

### Step 4: Validate

```bash
aws lambda invoke \
  --region us-west-2 --function-name $DR_RESYNC \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "validate"}' \
  response.json && cat response.json | jq .
```

Also confirm:
- `curl https://{DR_API_URL}/health` returns 200
- Execution records appearing in DynamoDB (schedules are firing)
- No errors in CloudWatch Logs for the DR Executor state machine

---

## Failback Procedure (DR → Primary)

### Step 1: Disable DR Region

> **Important:** Disable DR **before** re-enabling primary to avoid a window where both regions fire simultaneously.

```bash
aws lambda invoke \
  --region us-west-2 --function-name $DR_RESYNC \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "disable"}' \
  response.json && cat response.json | jq .
```

### Step 2: Route Traffic Back to Primary

Update DNS / API Gateway routing to the primary region.

### Step 3: Verify Primary Schedules

```bash
aws lambda invoke \
  --region us-east-2 --function-name $PRIMARY_RESYNC \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "validate"}' \
  response.json && cat response.json | jq .
```

If schedules are missing (e.g., primary stack was redeployed during the incident):

```bash
aws lambda invoke \
  --region us-east-2 --function-name $PRIMARY_RESYNC \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable"}' \
  response.json && cat response.json | jq .
```

### Step 4: Monitor

Watch CloudWatch Logs and DynamoDB execution records for 30+ minutes to confirm normal operation.

---

## Registering Targets in the DR Region

> **Required before failover.** If the DR Targets table is empty, schedules will fire but all executions will fail because preprocessing cannot resolve targets.

Register each target in both regions using the **same `target_id`** but region-specific ARNs:

```bash
# Primary region
curl -X POST https://{PRIMARY_API_URL}/api/targets \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"target_id": "my-processor", "target_arn": "arn:aws:lambda:us-east-2:...", "target_type": "lambda"}'

# DR region -- same target_id, different ARN
curl -X POST https://{DR_API_URL}/api/targets \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"target_id": "my-processor", "target_arn": "arn:aws:lambda:us-west-2:...", "target_type": "lambda"}'
```

### Why the Targets Table is Regional

The Targets table maps `target_id` to a **region-specific ARN**. It is intentionally **not** a Global Table because:

- Lambda functions, ECS clusters, and Step Functions state machines are regional resources
- The same logical target has different ARNs in different regions
- Your CD pipeline should register targets in each region with the appropriate ARNs

Tenant mappings (which reference `target_id` by alias) **are** stored in a Global Table and replicate automatically.

---

## DR Architecture Diagram

```
                    ┌──────────────────────────┐
                    │       Route 53 / DNS      │
                    │    (or API Gateway CNAME)  │
                    └──────┬──────────┬─────────┘
                           │          │
              ┌────────────┘          └────────────┐
              ▼                                     ▼
    ┌──────────────────┐                 ┌──────────────────┐
    │  us-east-2       │                 │  us-west-2       │
    │  (Primary)       │                 │  (DR)            │
    │                  │                 │                  │
    │  API Gateway     │                 │  API Gateway     │
    │  AppLambda       │                 │  AppLambda       │
    │  Step Functions  │                 │  Step Functions  │
    │  EventBridge ✓   │                 │  EventBridge ✗   │
    │                  │                 │  (until failover)│
    │  Targets Table   │                 │  Targets Table   │
    │  (us-east-2 ARNs)│                 │  (us-west-2 ARNs)│
    │                  │                 │                  │
    │  ┌──────────┐    │    Global       │  ┌──────────┐   │
    │  │ DynamoDB │◄───┼───Tables────────┼──► DynamoDB │   │
    │  │ (Source)  │    │  Replication    │  │ (Replica) │   │
    │  └──────────┘    │                 │  └──────────┘   │
    └──────────────────┘                 └──────────────────┘
```

**Key points:**
- EventBridge schedules are only active in **one region at a time**
- DynamoDB Global Tables replicate schedules, tenants, mappings, users, and executions automatically
- Targets table is **regional** -- must be populated separately per region
- DR Resync Lambda manages the EventBridge lifecycle explicitly

---

## Teardown Warning

EventBridge schedule groups are **not** CloudFormation-managed. Always run `disable` before deleting a stack:

```bash
aws lambda invoke \
  --region {REGION} --function-name {RESYNC_FUNCTION_NAME} \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "disable"}' \
  response.json && cat response.json | jq .
```

Skipping this leaves orphaned schedule groups that can block future deployments and cannot be cleaned up by CloudFormation.

---

*Previous: [Part 4 - API Routes](04-api-routes.md) | Next: [Part 6 - UI User Guide](06-ui-user-guide.md)*
