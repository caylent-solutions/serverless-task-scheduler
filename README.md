# Serverless Task Scheduler

A multi-tenant AWS serverless platform for scheduling and executing tasks across Lambda functions, ECS containers, and Step Functions workflows.

## What It Does

This service acts as a centralized scheduler for AWS services, similar to a cron server but designed for the cloud. It provides:

- **Task Scheduling** - Run AWS services on a schedule (like cron jobs)
- **On-Demand Execution** - Trigger services via REST API
- **Multi-Tenancy** - Isolate different organizations' resources
- **Access Control** - Role-based permissions using AWS Cognito
- **Execution History** - Track all task runs with detailed logs

**Think of it as:** A smart task scheduler for AWS that multiple teams can safely share.

## Core Concepts

### Targets
A **target** is an AWS service you want to execute. Three types are supported:
- **Lambda** - Functions for quick tasks (< 15 minutes)
- **ECS** - Containers for longer workloads
- **Step Functions** - Multi-step workflows

Each target includes an ARN (AWS Resource Name), configuration, and parameter schema.

### Tenants
A **tenant** represents an organization or team. Tenants are isolated - they can't see or access each other's resources.

### Tenant Mappings
A **mapping** gives a tenant a friendly alias for a target. This allows:
- Custom naming per tenant
- Different tenants using different versions
- Easy upgrades without breaking tenant code

**Example:** Both `acme-corp` and `globex-inc` can have an alias `send-email`, pointing to different Lambda versions.

### Schedules
A **schedule** automatically runs a mapping at specified times using AWS EventBridge Scheduler.

**Examples:**
- `rate(5 minutes)` - Every 5 minutes
- `cron(0 12 * * ? *)` - Daily at noon UTC
- `at(2024-12-31T23:59:59)` - One-time execution

## Architecture

```
┌─────────┐    JWT     ┌─────────────┐         ┌──────────────┐
│  User   │──────────>│  API Gateway │────────>│  API Lambda  │
│(Browser)│           │              │         │  (FastAPI)   │
└─────────┘           └─────────────┘         └──────┬───────┘
                                                      │
                 ┌────────────────────────────────────┼────────────────┐
                 │                                    │                │
                 v                                    v                v
          ┌──────────┐                        ┌─────────────┐  ┌─────────────┐
          │ DynamoDB │                        │ EventBridge │  │   Cognito   │
          │  Tables  │                        │  Scheduler  │  │(Auth/Users) │
          └──────────┘                        └──────┬──────┘  └─────────────┘
          • Targets                                  │
          • Tenants                                  │ (scheduled)
          • Mappings                                 │
          • Schedules                                v
          • Executions                    ┌─────────────────────┐
          • Users                         │  Step Functions     │
                                         │  Executor           │
                                         └──────────┬──────────┘
                                                    │
                        ┌───────────────────────────┼───────────────────┐
                        │                           │                   │
                        v                           v                   v
                 ┌──────────┐              ┌──────────────┐     ┌──────────────┐
                 │  Lambda  │              │  ECS Tasks   │     │Step Functions│
                 │ Functions│              │ (Containers) │     │  (Workflows) │
                 └──────────┘              └──────────────┘     └──────────────┘
```

### How Execution Works

**The Step Functions Executor** is a state machine that orchestrates all task execution:

1. **Triggered by:**
   - EventBridge Scheduler (for scheduled tasks)
   - API Lambda (for on-demand execution)

2. **Execution Flow:**
   1. Preprocessing Lambda resolves the tenant mapping and merges payload
   2. Executor state machine invokes the target service
   3. Helper Lambda captures CloudWatch logs (for Lambda targets)
   4. Postprocessing Lambda records results to DynamoDB

3. **Why Step Functions?**
   - **Reliable** - Automatic retries and error handling
   - **Observable** - Visual execution history in AWS Console
   - **Flexible** - Supports sync/async execution patterns
   - **Integrated** - Native support for Lambda, ECS, and nested Step Functions

### Security Model

Three IAM roles provide defense-in-depth:

1. **API Lambda Role**
   - Reads/writes DynamoDB
   - Manages EventBridge schedules
   - Starts Step Functions executions
   - ❌ Cannot invoke targets directly

2. **EventBridge Scheduler Role**
   - ✅ Can only start the Executor state machine
   - ❌ Cannot do anything else (least privilege)

3. **Executor State Machine Role**
   - Invokes Lambda/ECS/Step Functions
   - Reads/writes execution records
   - Accesses CloudWatch logs
   - ⚠️ Most privileged role - only used by executor

## Quick Start

### Prerequisites
- AWS Account with CLI configured
- AWS SAM CLI installed
- Python 3.13+
- Node.js 18+ (for UI)

### Deploy

```bash
# Quick deploy (builds UI + deploys everything)
./quickdeploy.sh

# Or deploy manually:
sam build
sam deploy --guided
```

The deploy creates:
- API Gateway endpoint
- Lambda functions (API + execution helpers)
- Step Functions state machine
- DynamoDB tables (6 total)
- Cognito user pool
- EventBridge schedule groups

### First-Time Setup

1. **Create an admin user in Cognito:**
   ```bash
   aws cognito-idp admin-create-user \
     --user-pool-id <pool-id> \
     --username admin@example.com \
     --user-attributes Name=email,Value=admin@example.com
   ```

2. **Get a JWT token:**
   - Log in via the web UI (served at API Gateway URL)
   - Or use the Cognito API to get tokens programmatically

3. **Create your first target:**
   ```bash
   curl -X POST https://your-api-gateway.com/targets \
     -H "Authorization: Bearer <jwt-token>" \
     -H "Content-Type: application/json" \
     -d '{
       "target_id": "hello-world",
       "target_arn": "arn:aws:lambda:us-east-1:123456789:function:my-function",
       "target_type": "lambda",
       "target_description": "My first Lambda target"
     }'
   ```

## API Workflows

### Workflow 1: Schedule a Daily Report

**Step 1: Admin creates a target (Lambda definition)**
```bash
POST /targets
{
  "target_id": "daily-report-v1",
  "target_arn": "arn:aws:lambda:us-east-1:123456:function:generate-report",
  "target_type": "lambda",
  "target_description": "Generates daily sales reports"
}
```

**Step 2: Tenant creates a mapping (friendly alias)**
```bash
POST /tenants/acme-corp/mappings
{
  "target_alias": "sales-report",
  "target_id": "daily-report-v1"
}
```

**Step 3: Create schedule**
```bash
POST /tenants/acme-corp/mappings/sales-report/schedules
{
  "schedule_expression": "cron(0 9 * * ? *)",
  "description": "Daily at 9 AM UTC",
  "state": "ENABLED",
  "target_input": {
    "report_type": "sales",
    "format": "pdf"
  }
}
```

### Workflow 2: On-Demand Execution

Execute immediately without a schedule:
```bash
POST /tenants/acme-corp/mappings/sales-report/_execute
{
  "report_type": "sales",
  "format": "pdf"
}
```

For long-running tasks, use async mode:
```bash
POST /tenants/acme-corp/mappings/sales-report/_execute?async=true
{
  "report_type": "sales",
  "format": "pdf"
}
```

## API Reference

### Authentication
All endpoints require JWT token from Cognito (except `/health` and `/`):
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Endpoints

**Targets** (Admin only)
- `GET /targets` - List all targets
- `POST /targets` - Create target
- `PUT /targets/{id}` - Update target
- `DELETE /targets/{id}` - Delete target

**Tenants** (Admin only)
- `GET /tenants` - List tenants
- `POST /tenants` - Create tenant
- `GET /tenants/{id}/users` - List tenant users

**Mappings** (Requires tenant access)
- `GET /tenants/{id}/mappings` - List mappings
- `POST /tenants/{id}/mappings` - Create mapping
- `DELETE /tenants/{id}/mappings/{alias}` - Delete mapping

**Execution** (Requires tenant access)
- `POST /tenants/{id}/mappings/{alias}/_execute` - Execute (sync/async)

**Schedules** (Requires tenant access)
- `GET /tenants/{id}/schedules` - List all schedules
- `POST /tenants/{id}/mappings/{alias}/schedules` - Create schedule
- `PUT /tenants/{id}/mappings/{alias}/schedules/{schedule_id}` - Update
- `DELETE /tenants/{id}/mappings/{alias}/schedules/{schedule_id}` - Delete

**Users** (Admin only)
- `GET /users` - List users
- `POST /users` - Create user & send invitation
- `POST /users/{user_id}/tenants/{tenant_id}` - Grant access
- `DELETE /users/{user_id}/tenants/{tenant_id}` - Revoke access

**Utility**
- `GET /health` - Health check (no auth)
- `GET /openapi.json` - OpenAPI spec

## Testing

### Bruno API Collection
The `api/bruno/` directory contains a complete API test suite.

1. Open in Bruno
2. Set `authToken` variable with your JWT
3. Update tenant IDs as needed
4. Run requests

### Local Development

**API (FastAPI):**
```bash
cd api
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

**UI (React):**
```bash
cd ui-react
npm install
npm start
```

## Project Structure

```
serverless-task-scheduler/
├── api/                      # FastAPI REST API
│   ├── app/
│   │   ├── main.py          # FastAPI application
│   │   ├── lambda_handler.py # AWS Lambda entry point
│   │   ├── routers/         # API routes
│   │   ├── models/          # Pydantic models
│   │   ├── awssdk/          # AWS SDK wrappers
│   │   └── wwwroot/         # Static UI files (auto-generated)
│   └── requirements.txt     # Python dependencies
│
├── task-execution/          # Step Functions executor
│   ├── state_machine.json   # Step Functions definition (ASL)
│   ├── preprocessing.py     # Resolve targets & merge payloads
│   ├── lambda_execution_helper.py # Capture Lambda logs
│   ├── postprocessing.py    # Record execution results
│   └── requirements.txt
│
├── ui-react/                # React web interface
│   ├── src/
│   │   ├── App.js          # Main app component
│   │   ├── components/     # React components
│   │   └── config.js       # API configuration
│   └── package.json
│
└── template.yaml            # AWS SAM template
```

## Environment Variables

**API Lambda:**
- `DYNAMODB_*_TABLE` - DynamoDB table names (6 tables)
- `COGNITO_USER_POOL_ID` - Cognito user pool
- `COGNITO_CLIENT_ID` - Cognito app client
- `SCHEDULER_ROLE_ARN` - EventBridge scheduler IAM role
- `STEP_FUNCTIONS_EXECUTOR_ARN` - Executor state machine ARN
- `ADMIN_USER_EMAIL` - Bootstrap admin email

**Execution Lambdas:**
- `DYNAMODB_TABLE` - Targets table
- `DYNAMODB_TENANT_TABLE` - Mappings table
- `DYNAMODB_EXECUTIONS_TABLE` - Executions table
- `APP_ENV` - Environment (dev/qa/prod) - controls logging verbosity

## Common Issues

### "Access denied" errors
- Verify JWT token is valid (check expiration)
- Ensure user has access to the tenant
- Admin operations require `admin` tenant membership

### Schedules not executing
1. Check schedule is `ENABLED` in EventBridge
2. Verify EventBridgeSchedulerRole has permission to invoke executor
3. Check Step Functions execution logs in AWS Console
4. Review execution records in DynamoDB executions table

### Target execution failures
1. Verify tenant mapping exists and points to valid target
2. Check target ARN and type are correct
3. Ensure executor role has permission to invoke target service
4. Review error details in executions table

## Why These Technologies?

**DynamoDB** - Serverless, auto-scaling, fast key-value lookups

**EventBridge Scheduler** - Native AWS scheduler with cron/rate expressions and timezone support

**Step Functions** - Visual workflow orchestration with built-in retry logic and error handling

**FastAPI** - Modern Python web framework with automatic API docs and type validation

**React** - Popular UI framework with component-based architecture

## Contributing

### Requirements
- Python 3.13+
- Node.js 18+
- AWS SAM CLI
- Bruno (for API testing)

### Code Quality
All code has been linted and formatted:
- Python: flake8 compliant (except line length)
- JavaScript: ESLint + Prettier

### Recent Updates
- ✅ Updated all Python packages (including python-jose security fix)
- ✅ Updated all Node packages (React 19.2+)
- ✅ Fixed all linting warnings in Python and JavaScript
- ✅ Cleaned up unused imports and variables
- ✅ Directory structure reorganization (ExecutionAPI→api, ExecutorStepFunction→task-execution, ui→ui-react)

## License

[Add your license here]
