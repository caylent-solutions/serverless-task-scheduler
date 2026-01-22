# Disaster Recovery Guide

## Table of Contents
- [Architecture Overview](#architecture-overview)
- [Disaster Recovery Strategy](#disaster-recovery-strategy)
- [Failover Procedure](#failover-procedure)
- [Cognito Authentication Options](#cognito-authentication-options)

---

## Architecture Overview

### AWS Services in Use

| Service | Purpose |
|---------|---------|
| **API Gateway** | REST API endpoints for the web UI |
| **Lambda** | API backend, task executors, schedule management |
| **DynamoDB** | Data storage with Global Tables for multi-region replication |
| **EventBridge Scheduler** | Cron-based scheduling engine |
| **Step Functions** | Orchestrates task execution workflow (preprocessing → execution → postprocessing) |
| **Cognito** | User authentication and authorization |
| **S3 + CloudFront** | Static website hosting for React UI |

### Main Components

```
┌─────────────┐
│   React UI  │  ← User interface (Vite build deployed to S3/CloudFront)
└──────┬──────┘
       │
┌──────▼──────┐
│  API Layer  │  ← FastAPI application on Lambda (creates/manages schedules)
└──────┬──────┘
       │
┌──────▼──────────┐
│  EventBridge    │  ← Fires schedules at specified times
│   Scheduler     │
└──────┬──────────┘
       │
┌──────▼──────────┐
│ Step Functions  │  ← Executor: Preprocessing → Invoke Target → Postprocessing
│   (Executor)    │
└──────┬──────────┘
       │
┌──────▼──────────┐
│ Target Lambdas  │  ← Customer-defined functions (e.g., data processing, reports)
└─────────────────┘
```

**Key Tables:**

*DynamoDB Global Tables* (replicated across regions):
- `Schedules`: Schedule definitions, cron expressions, state (ENABLED/DISABLED)
- `Executions`: Execution history and results
- `TenantMappings`: Multi-tenant target permissions

*Local DynamoDB Tables* (per region):
- `Targets`: Target Lambda names → regional ARN mappings (populated by CD pipelines)

---

## Disaster Recovery Strategy

### Active-Passive Multi-Region Setup

**Primary Region**: US-East-1 (Active)
- DynamoDB: Schedules table with all schedule definitions
- EventBridge: Active schedules firing according to cron expressions
- API: Receiving traffic via Route53
- All services operational

**DR Region**: US-West-1 (Passive)
- DynamoDB: Schedules table replicated automatically via Global Tables
- EventBridge: **No schedules exist yet** (will be created during failover)
- API: Deployed but idle
- Targets table: Pre-populated with regional ARNs

### How Target Registration Works

Schedules in the DynamoDB table **never** store hard-coded Lambda ARNs. Instead, they reference **target names** (e.g., `my-processor`).

The `Targets` table is **local to each region** and contains mappings from target names to region-specific ARNs:

```
US-East-1 Targets Table:
  Target Name: "my-processor" → arn:aws:lambda:us-east-1:123456:function:data-processor

US-West-1 Targets Table:
  Target Name: "my-processor" → arn:aws:lambda:us-west-1:123456:function:data-processor
```

**How targets get registered:**
1. Developer deploys a Lambda function to both regions
2. CD pipeline registers the target in **both** regional Targets tables:
   ```bash
   # Register in primary region
   aws dynamodb put-item --table-name Targets --region us-east-1 \
     --item '{"target_name": {"S": "my-processor"}, "arn": {"S": "arn:aws:lambda:us-east-1:..."}...}'
   
   # Register in DR region
   aws dynamodb put-item --table-name Targets --region us-west-1 \
     --item '{"target_name": {"S": "my-processor"}, "arn": {"S": "arn:aws:lambda:us-west-1:..."}...}'
   ```
3. Same target name, different ARNs per region

**Why this matters for DR:**
- The Schedules table (DynamoDB Global Table) replicates to DR region automatically
- During failover, EventBridge schedules are created in DR region from DynamoDB data
- When schedules fire, preprocessing looks up target names in the **local DR region Targets table**
- Gets the correct us-west-1 ARN automatically—no data modification needed!

### RTO and RPO Targets
- **RTO** (Recovery Time Objective): 30 minutes
- **RPO** (Recovery Point Objective): ~0 seconds (DynamoDB Global Tables provide near real-time replication)

---

## Failover Procedure

### When to Failover
- Primary region becomes unavailable
- API health checks fail for >5 minutes
- EventBridge Scheduler stops responding
- Critical infrastructure outage detected

### Step-by-Step Failover

#### Phase 1: Disaster Detection (T+0 to T+5)
1. **Monitoring alerts fire** indicating primary region failure
2. **Incident Commander** validates the outage
3. **Decision made** to initiate failover

#### Phase 2: Route Traffic to DR Region (T+5 to T+15)
1. **Update Route53** DNS record:
   ```bash
   # Point API domain to DR region
   api.yourservice.com → us-west-1-api-gateway-url
   ```
2. **Wait for DNS propagation** (~60 seconds, depends on TTL)
3. **Verify API health** in DR region:
   ```bash
   curl https://api.yourservice.com/health
   ```

#### Phase 3: Recreate EventBridge Schedules (T+15 to T+25)
1. **Invoke the `schedule_resync` Lambda**:
   ```bash
   aws lambda invoke \
     --function-name schedule_resync \
     --region us-west-1 \
     --payload '{"action": "failover", "from_region": "us-east-1", "to_region": "us-west-1"}' \
     response.json
   ```

2. **What `schedule_resync` does**:
   - Reads all schedules from DynamoDB Schedules table (already replicated to us-west-1)
   - For each schedule in DynamoDB:
     - Verifies target name exists in local us-west-1 Targets table
     - Creates a new EventBridge schedule in us-west-1
     - Logs creation
   - Cleans up EventBridge schedules in us-east-1 (if region is accessible):


3. **Key Points**:
   - EventBridge schedules are **regional AWS resources** that don't replicate
   - DynamoDB Global Tables provide the source of truth for schedule definitions
   - Script recreates schedules from scratch in DR region
   - Script is idempotent: Can be run multiple times (checks if schedule exists first)

#### Phase 4: Validation (T+25 to T+30)
Verify the following:
- Route53 pointing to us-west-1
- API responding to requests
- EventBridge schedules created in us-west-1 (count matches DynamoDB)
- Target names resolving to us-west-1 ARNs in local Targets table
- Recent executions appearing in DynamoDB (schedules are firing)
- CloudWatch logs showing activity
- No elevated error rates

### Failback (Returning to Primary)
Once the primary region is restored:

1. **Verify primary region health**
2. **Run `schedule_resync` to recreate schedules in primary**:
   - This creates EventBridge schedules in us-east-1 from DynamoDB data
   - Deletes EventBridge schedules in us-west-1
3. **Update Route53** back to primary region
4. **Monitor for 24 hours** to ensure stability

---

1. **Target name abstraction**: Schedules reference target names (not ARNs), which resolve to region-specific ARNs via local Targets tables
2. **DynamoDB is the source of truth**: Schedules table (Global) defines what should be scheduled; EventBridge is just the executor
3. **EventBridge schedules are regional**: They don't replicate, so `schedule_resync` recreates them in DR region from DynamoDB data
4. **CD pipeline responsibility**: Target deployments must register in both regions with region-specific ARNs
5. **Active-Passive strategy**: Only one region has active EventBridge schedules at a time (prevents duplicate executions)
6. **`schedule_resync` Lambda**: Manages the lifecycle of EventBridge schedules during failover and failback
7. **Cognito flexibility**: Choose between independent, shared, or AD-integrated authentication based on your needs

**DR is not a one-time setup—it requires regular testing and validation.**
