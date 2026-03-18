# Part 1: Serverless Task Scheduler - System Overview

---

## What is the Serverless Task Scheduler?

The Serverless Task Scheduler (STS) is a **multi-tenant AWS serverless platform** for scheduling and executing tasks across Lambda functions, ECS containers, and Step Functions workflows.

Think of it as a **universal cron job manager for the cloud** that multiple organizations can safely share.

![Architecture Overview](img/architecture-overview.png)

---

## The Problem It Solves

Organizations need to:

- Run AWS services on a schedule (like cron jobs)
- Trigger services on-demand via REST API
- Isolate different organizations' resources (multi-tenancy)
- Control who can execute what (role-based access)
- Track every task run with detailed logs and audit trails

**Without STS**, each team builds its own scheduling infrastructure, duplicating effort, security controls, and monitoring.

---

## Core Concepts

### Targets

A **target** is an AWS service you want to execute. Three types are supported:

| Type | Use Case | Timeout |
|------|----------|---------|
| **Lambda** | Quick tasks | < 15 minutes |
| **ECS** | Long-running container workloads | Hours |
| **Step Functions** | Multi-step workflows | Days |

Each target includes an ARN, configuration, and parameter schema.

### Tenants

A **tenant** represents an organization or team. Tenants are **fully isolated** -- they cannot see or access each other's resources, schedules, or execution history.

### Tenant Mappings (Target Aliases)

A **mapping** gives a tenant a friendly alias for a target. This is a critical abstraction:

- Custom naming per tenant
- Different tenants can use different versions of the same logical service
- Upgrades happen by changing the mapping, not the tenant's code

```
ACME Corp:   "send-email" --> email-sender-v2 (Lambda)
Globex Inc:  "send-email" --> email-bulk-processor (ECS)
Initech:     "send-email" --> email-approval-flow (Step Functions)
```

**Same alias. Different implementations. Zero code changes.**

### Schedules

A **schedule** automatically runs a mapping at specified times using AWS EventBridge Scheduler:

- `rate(5 minutes)` -- Every 5 minutes
- `cron(0 12 * * ? *)` -- Daily at noon UTC
- `at(2024-12-31T23:59:59)` -- One-time execution

---

## The Three Main Components

### 1. Web UI (React + Vite)

A browser-based single-page application for managing all aspects of the scheduler:

- Create and manage targets, tenants, mappings, and schedules
- View execution history with status, results, and CloudWatch log links
- Trigger on-demand executions
- User management and tenant access control

**Served from S3** via API Gateway -- no separate hosting costs, optimized for performance.

### 2. API Layer (FastAPI + API Gateway)

The control plane that manages all operations:

- **API Gateway** -- Single entry point for HTTPS requests
- **Lambda (Python/FastAPI)** -- Processes requests, enforces security
- **DynamoDB (6 tables)** -- Stores targets, tenants, mappings, schedules, executions, and user access
- **Cognito** -- User authentication (JWT-based)
- **EventBridge Scheduler** -- Creates and manages cron/rate schedules

### 3. Execution Engine (Step Functions)

The worker that actually runs scheduled tasks:

- **Preprocessing Lambda** -- Resolves tenant alias to actual target ARN, merges payloads
- **Executor State Machine** -- Routes to Lambda, ECS, or Step Functions based on target type
- **Lambda Execution Helper** -- Invokes Lambda targets and captures CloudWatch logs
- **Postprocessing Lambda** -- Records execution results to DynamoDB (triggered via EventBridge)

---

## How It All Fits Together

```
User (Browser)
    │
    ▼
API Gateway ──► S3 (Static UI files)
    │
    ▼
AppLambda (FastAPI)
    │
    ├──► Cognito (Auth)
    ├──► DynamoDB (6 Tables)
    └──► EventBridge Scheduler
              │
              ▼
         Executor State Machine (Step Functions)
              │
              ├──► Preprocessing Lambda
              │         │
              │         ▼
              │    DynamoDB (resolve alias → target)
              │
              ├──► Target Execution
              │    ├── Lambda (via Helper)
              │    ├── ECS (native integration)
              │    └── Step Functions (nested execution)
              │
              └──► Postprocessing Lambda (via EventBridge)
                        │
                        ▼
                   DynamoDB (record results)
```

---

## The Complete Execution Flow

### Scheduled Execution

1. **User creates schedule** via Web UI
   - API verifies JWT token, checks tenant access
   - Creates EventBridge schedule with cron/rate expression
   - Saves schedule metadata to DynamoDB

2. **EventBridge fires at scheduled time**
   - Assumes Scheduler Role (minimal permissions)
   - Starts Executor State Machine with `{ tenant_id, target_alias, schedule_id, payload }`

3. **Executor orchestrates**
   - **Preprocessing**: Resolves `tenant_id + target_alias` to actual target ARN, merges payloads
   - **Execution**: Routes to Lambda/ECS/Step Functions based on target type
   - **Postprocessing**: EventBridge detects completion, triggers Lambda to record results to DynamoDB

4. **User views results** via Web UI
   - Execution history with status, result payload, and clickable CloudWatch Logs links

### On-Demand Execution

The API creates a **one-time EventBridge schedule** set to fire 1 minute in the future, then follows the same execution flow. This ensures all executions go through the same security and orchestration path.

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | React + Vite, served from S3 via API Gateway |
| **Backend** | Python 3.13, FastAPI, Mangum (Lambda adapter) |
| **Infrastructure** | AWS SAM (CloudFormation), DynamoDB, Step Functions |
| **Auth** | AWS Cognito (JWT tokens, hosted UI) |
| **Scheduling** | AWS EventBridge Scheduler |
| **Monitoring** | CloudWatch Logs, X-Ray tracing |

---

## Deployment

**One-command deploy**: `./quickdeploy.sh`

This builds the UI, validates the SAM template, builds Lambda packages, deploys to AWS, uploads static files to S3, and configures Cognito -- all automatically.

**Multi-environment support**: Deploy separate dev/staging/prod with parameter overrides:

```bash
sam deploy --config-env prod --parameter-overrides Environment=prod
```

Each environment gets isolated DynamoDB tables, Lambda functions, Cognito pools, and API Gateway stages.

---

## Why Serverless?

| Benefit | Detail |
|---------|--------|
| **No servers to manage** | No EC2 patching, no capacity planning |
| **Pay per use** | Charged per request/execution, not idle time |
| **Auto-scaling** | 1 user or 10,000 -- same code, AWS handles scaling |
| **Built-in HA** | Lambda, DynamoDB, Step Functions are managed services |
| **One-command deploy** | Infrastructure + code deployed together |

---

*Next: [Part 2 - Executor Step Function](02-executor-step-function.md)*
