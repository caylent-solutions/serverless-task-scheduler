# Disaster Recovery Runbook

Operational procedures for DR failover and failback. For architecture, setup, and target registration see the [Disaster Recovery section in README.md](README.md#disaster-recovery).

---

## Pre-Failover Checklist

- [ ] DynamoDB Global Table replication is current (AWS Console → DynamoDB → Global Tables → Schedules → Replicas, lag should be seconds)
- [ ] DR stack is deployed in us-west-2 (`./quickdeploy.sh --dr-region us-west-2`)
- [ ] All targets are registered in the DR region Targets table with us-west-2 ARNs
- [ ] DR Resync validate returns `status: success` (see [Validate](#validate))

---

## Get the DR Resync Function Name

```bash
# DR region
DR_RESYNC=$(aws cloudformation describe-stacks \
  --stack-name jyelle-dr-test-dr --region us-west-2 \
  --query "Stacks[0].Outputs[?OutputKey=='DRResyncLambdaName'].OutputValue" \
  --output text)

# Primary region
PRIMARY_RESYNC=$(aws cloudformation describe-stacks \
  --stack-name jyelle-dr-test --region us-east-2 \
  --query "Stacks[0].Outputs[?OutputKey=='DRResyncLambdaName'].OutputValue" \
  --output text)
```

---

## Failover (Primary → DR)

### 1. Dry run (preview)

```bash
aws lambda invoke \
  --region us-west-2 --function-name $DR_RESYNC \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable", "dry_run": true}' \
  response.json && cat response.json | jq .
```

Confirm `summary.total_schedules` matches expectations before proceeding.

### 2. Enable DR region

```bash
aws lambda invoke \
  --region us-west-2 --function-name $DR_RESYNC \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable"}' \
  response.json && cat response.json | jq .
```

Confirm `"status": "success"` and `summary.created` matches `summary.total_schedules`.

### 3. Route traffic to DR

Update DNS / API Gateway custom domain to the DR API URL:

```bash
aws cloudformation describe-stacks \
  --stack-name jyelle-dr-test-dr --region us-west-2 \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" \
  --output text
```

### 4. Validate

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

## Failback (DR → Primary)

### 1. Disable DR region

> Do this **before** re-enabling the primary to avoid a window where both regions fire simultaneously.

```bash
aws lambda invoke \
  --region us-west-2 --function-name $DR_RESYNC \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "disable"}' \
  response.json && cat response.json | jq .
```

Confirm `"status": "success"`.

### 2. Route traffic back to primary

Update DNS / API Gateway routing to the primary region (us-east-2).

### 3. Verify primary EventBridge schedules

```bash
aws lambda invoke \
  --region us-east-2 --function-name $PRIMARY_RESYNC \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "validate"}' \
  response.json && cat response.json | jq .
```

If schedules are missing (e.g. primary stack was redeployed during the incident), recreate them:

```bash
aws lambda invoke \
  --region us-east-2 --function-name $PRIMARY_RESYNC \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "enable"}' \
  response.json && cat response.json | jq .
```

### 4. Monitor

Watch CloudWatch Logs and DynamoDB execution records for 30+ minutes to confirm normal operation.

---

## Validate

Check consistency between DynamoDB and EventBridge without making changes. Can be run against either region at any time.

```bash
aws lambda invoke \
  --region {REGION} --function-name {RESYNC_FUNCTION_NAME} \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "validate"}' \
  response.json && cat response.json | jq .
```

| Response field | Meaning |
|---|---|
| `status: success` | All DynamoDB schedules have a corresponding EventBridge schedule |
| `status: partial` | Some schedules missing from EventBridge — check `warnings` |
| `summary.missing_targets` | Schedules whose `target_id` is absent from the regional Targets table |
| `summary.missing_mappings` | Schedules with no matching TenantMapping |

Scope to a single tenant: `{"mode": "validate", "tenant_id": "acme"}`

---

## Teardown Warning

EventBridge schedule groups are not CloudFormation-managed. Always run `disable` before deleting a stack:

```bash
aws lambda invoke \
  --region {REGION} --function-name {RESYNC_FUNCTION_NAME} \
  --cli-binary-format raw-in-base64-out \
  --payload '{"mode": "disable"}' \
  response.json && cat response.json | jq .
```

Skipping this leaves orphaned schedule groups that can block future deployments and cannot be cleaned up by CloudFormation.
