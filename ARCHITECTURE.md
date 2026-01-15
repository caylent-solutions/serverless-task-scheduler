# Serverless Task Scheduler - Architecture Documentation

## Overview

The Serverless Task Scheduler (STS) is a multi-tenant AWS serverless application that manages and executes scheduled tasks across different compute services (Lambda functions, ECS containers, and Step Functions workflows). 

Think of it like a sophisticated cron job manager that works across an entire organization:
- **Multi-tenant** means multiple organizations (tenants) can use the same system with their data isolated
- **Serverless** means no servers to manage - AWS handles scaling, availability, and infrastructure
- **Modular architecture** means clear separation between the API layer (what users interact with), execution orchestration (how tasks run), and data storage (where information is kept)

---

## Top-Level Artifacts

### 1. **api/** - REST API Service

The FastAPI-based REST API that provides the management interface for the entire platform.

#### Purpose
- User authentication and authorization via AWS Cognito
- CRUD operations for targets, tenants, mappings, schedules, and users
- Direct execution endpoint for on-demand task execution
- Dynamic OpenAPI schema generation based on available targets
- Provides API endpoints for the React web UI (UI is served separately from S3 via API Gateway)

#### Key Files
- [app/main.py](api/app/main.py) - FastAPI application with middleware, routing, and authentication
- [app/lambda_handler.py](api/app/lambda_handler.py) - AWS Lambda handler using Mangum adapter
- [app/routers/](api/app/routers/) - API route handlers (targets, tenants, schedules, auth, user)
- [app/models/](api/app/models/) - Pydantic models for request/response validation
- [app/awssdk/](api/app/awssdk/) - AWS SDK wrappers (DynamoDB, Cognito, EventBridge, Step Functions)
- [requirements.txt](api/requirements.txt) - Python dependencies

#### Related AWS Resources (from template.yaml)

**API Gateway (Lines 374-472)**
- **Resource**: `ApiGateway` - AWS::Serverless::Api
- **Configuration**:
  - REST API with stage name from `Environment` parameter
  - Routes `/api/{proxy+}` to AppLambda (FastAPI backend)
  - Routes `/` and `/{proxy+}` to S3 StaticFilesBucket (React UI)
  - Binary media type support for images
  - X-Ray tracing enabled
  - SPA routing support (404s return index.html for client-side routing)
- **Purpose**: Single entry point that routes API requests to Lambda and static file requests to S3

**App Lambda Function (Lines 387-413)**
- **Resource**: `AppLambda` - AWS::Serverless::Function
- **Configuration**:
  - Handler: `app/lambda_handler.handler`
  - Runtime: Python 3.13
  - CodeUri: `api/`
  - Timeout: 30 seconds, Memory: 512 MB
  - Role: `AppLambdaRole` (Lines 794-898)
- **Environment Variables**:
  - `DB_TARGET=aws` - Use AWS DynamoDB (not local)
  - `DYNAMODB_TABLE` - Reference to TargetsTable
  - `DYNAMODB_TENANTS_TABLE` - Reference to TenantsTable
  - `DYNAMODB_TENANT_TABLE` - Reference to TenantMappingsTable
  - `DYNAMODB_EXECUTIONS_TABLE` - Reference to TargetExecutionsTable
  - `DYNAMODB_SCHEDULES_TABLE` - Reference to SchedulesTable
  - `DYNAMODB_USER_MAPPINGS_TABLE` - Reference to UserMappingsTable
  - `API_BASE_PATH` - Environment name for stage routing
  - `SCHEDULER_ROLE_ARN` - ARN of EventBridgeSchedulerRole
  - `SCHEDULER_GROUP_NAME` - EventBridge schedule group name
  - `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, `COGNITO_REGION`, `COGNITO_DOMAIN`
  - `STEP_FUNCTIONS_EXECUTOR_ARN` - ARN of ExecutorStateMachine
  - `ADMIN_USER_EMAIL` - Bootstrap admin user
- **Permissions (AppLambdaRole, Lines 807-898)**:
  - DynamoDB: Full CRUD on all six tables
  - EventBridge Scheduler: Create/update/delete schedules
  - IAM: PassRole for EventBridge Scheduler
  - Step Functions: RedriveExecution and DescribeExecution
  - Cognito: User authentication and admin operations
  - Secrets Manager: GetSecretValue for configuration

**DynamoDB Tables - Data Storage**

**Key Concepts**:
- **PK (Partition Key)**: Main identifier used to distribute data across servers. All items with same PK are stored together.
- **SK (Sort Key)**: Optional secondary identifier within a partition. Allows storing multiple related items under one PK, sorted by SK.
- **GSI (Global Secondary Index)**: Alternative way to query the table using different attributes. Like having a second copy of the table organized differently.
- **TTL (Time To Live)**: Automatic deletion of old records based on timestamp. Saves storage costs.

**The Six Tables**:
1. **TargetsTable (Lines 75-94)**: Stores target definitions (what can be executed)
   - PK: `target_id` (string) - unique identifier for each target
   - Stores: ARN (AWS Resource Name - address of the resource), type (lambda/ecs/stepfunctions), configuration, parameter schema
   - Example: A Lambda function that sends emails, or an ECS task that processes data

2. **TenantsTable (Lines 100-119)**: Stores tenant (organization) definitions
   - PK: `tenant_id` (string) - unique identifier for each organization
   - Stores: Tenant name, description, metadata
   - Think of tenants as separate organizations sharing the same system

3. **TenantMappingsTable (Lines 125-148)**: Maps tenant aliases to targets
   - PK: `tenant_id` (string) - which organization
   - SK: `target_alias` (string) - friendly name chosen by the tenant
   - Stores: Mapping between tenant's custom names and actual target IDs
   - Example: Tenant calls it "send-email" but it maps to target "email-sender-v2"

4. **TargetExecutionsTable (Lines 158-197)**: Execution history (what ran and what happened)
   - PK: `tenant_schedule` (composite: `tenant_id#schedule_id`) - identifies which schedule ran
   - SK: `execution_id` (string) - unique ID for this specific execution
   - GSI: `tenant-target-index` (tenant_target + timestamp) for listing executions by tenant/target
   - TTL enabled on `ttl` attribute for automatic cleanup (old records auto-delete)
   - Stores: Execution status, response payload, CloudWatch logs URL, Lambda request ID

5. **SchedulesTable (Lines 199-233)**: Schedule definitions (when things should run)
   - PK: `tenant_id` (string) - which organization owns this schedule
   - SK: `schedule_id` (string) - unique schedule identifier
   - GSI: `tenant-target-index` (tenant_id + target_alias) for querying schedules by target
   - Stores: Cron expression (time-based schedule like "run every day at 9 AM"), schedule state (enabled/disabled), target input payload
   - **Cron expressions**: Standard format borrowed from Unix cron, e.g., `cron(0 9 * * ? *)` means "9:00 AM every day"

6. **UserMappingsTable (Lines 241-273)**: User-to-tenant access control (who can access what)
   - PK: `user_id` (email address, string) - identifies the user
   - SK: `tenant_id` (string) - which organization they can access
   - GSI: `tenant-index` (tenant_id + user_id) for reverse lookup (which users belong to a tenant)
   - Stores: Access control mappings between users and organizations

**Cognito Resources - Authentication**
1. **CognitoUserPool (Lines 278-312)**: User authentication
   - Email-based username
   - Auto-verified email addresses
   - Password policy enforcement

2. **CognitoUserPoolClient (Lines 317-342)**: Web application client
   - OAuth flows: authorization code
   - Auth flows: SRP, password, refresh token
   - Callback/logout URLs configured during deployment

3. **CognitoUserPoolDomain (Lines 347-353)**: Hosted UI domain
   - Unique domain per stack for Cognito Hosted UI

**S3 Static File Hosting**
1. **StaticFilesBucket (Lines 290-322)**: S3 bucket for React UI files
   - Private bucket with public access blocked
   - CORS enabled for API Gateway integration
   - Stores built React application (HTML, CSS, JavaScript, images)

2. **ApiGatewayS3Role (Lines 327-369)**: IAM role for API Gateway to read from S3
   - Allows API Gateway to serve static files from S3
   - Read-only access to StaticFilesBucket

---

### 2. **task-execution/** - Execution Orchestration Engine

The Step Functions-based execution engine that handles all target invocations with proper error handling and logging.

#### Purpose
- Orchestrates execution of Lambda, ECS, and Step Functions targets
- Centralizes execution logic for security (single point of invocation)
- Resolves tenant mappings to actual targets
- Merges schedule payloads with target defaults
- Captures execution results and CloudWatch logs
- Records execution history to DynamoDB

#### Key Files
- [state_machine.json](task-execution/state_machine.json) - Step Functions ASL definition
- [preprocessing.py](task-execution/preprocessing.py) - Resolves targets and merges payloads
- [lambda_execution_helper.py](task-execution/lambda_execution_helper.py) - Invokes Lambda targets and captures logs
- [postprocessing.py](task-execution/postprocessing.py) - Records execution results to DynamoDB

#### Related AWS Resources (from template.yaml)

**Executor State Machine (Lines 651-668)**
- **Resource**: `ExecutorStateMachine` - AWS::Serverless::StateMachine
- **Configuration**:
  - Type: STANDARD (long-running, full history)
  - DefinitionUri: `task-execution/state_machine.json`
  - DefinitionSubstitutions: Injects Lambda ARNs at deployment
  - Role: `ExecutorStateMachineRole` (Lines 670-744)
  - X-Ray tracing enabled
- **Purpose**: Orchestrates the three-stage execution flow

**State Machine Workflow**:
1. **Preprocessing (Lines 5-25)**:
   - Invokes PreprocessingLambda
   - Resolves tenant mapping to target ID
   - Retrieves target configuration (ARN, type, config)
   - Merges schedule payload with target defaults
   - Retry policy: 2 attempts with exponential backoff

2. **ExecuteTargetWithErrorHandling (Lines 27-128)**:
   - Parallel state with single branch for centralized error handling
   - Choice state routes to appropriate executor:
     - **Lambda**: Invokes LambdaExecutionHelperLambda
     - **ECS**: Uses native Step Functions ECS integration (`ecs:runTask.waitForTaskToken`)
     - **Step Functions**: Uses sync nested execution (`states:startExecution.sync:2`)
   - ResultSelector extracts execution result and metadata

3. **EventBridgeHandoff (Lines 130-134)**:
   - Pass state indicating completion
   - EventBridge rule automatically triggers postprocessing

**Preprocessing Lambda (Lines 463-483)**
- **Resource**: `PreprocessingLambda` - AWS::Serverless::Function
- **Configuration**:
  - Handler: `preprocessing.handler`
  - CodeUri: `task-execution/`
  - Runtime: Python 3.13
  - Timeout: 30 seconds, Memory: 256 MB
  - Role: `PreprocessingLambdaRole` (Lines 485-518)
- **Environment Variables**:
  - `DYNAMODB_TABLE` - Reference to TargetsTable
  - `DYNAMODB_TENANT_TABLE` - Reference to TenantMappingsTable
- **Permissions (Lines 498-509)**:
  - DynamoDB: GetItem on TargetsTable and TenantMappingsTable

**Lambda Execution Helper (Lines 523-541)**
- **Resource**: `LambdaExecutionHelperLambda` - AWS::Serverless::Function
- **Configuration**:
  - Handler: `lambda_execution_helper.handler`
  - CodeUri: `task-execution/`
  - Runtime: Python 3.13
  - Timeout: 60 seconds (longer to wait for target execution)
  - Memory: 256 MB
  - Role: `LambdaExecutionHelperRole` (Lines 543-581)
- **Permissions (Lines 556-572)**:
  - Lambda: InvokeFunction on any Lambda (wildcard)
  - CloudWatch Logs: DescribeLogStreams and FilterLogEvents to capture logs

**Postprocessing Lambda (Lines 586-605)**
- **Resource**: `PostprocessingLambda` - AWS::Serverless::Function
- **Configuration**:
  - Handler: `postprocessing.handler`
  - CodeUri: `task-execution/`
  - Runtime: Python 3.13
  - Timeout: 30 seconds, Memory: 256 MB
  - Role: `PostprocessingLambdaRole` (Lines 607-646)
- **Environment Variables**:
  - `DYNAMODB_EXECUTIONS_TABLE` - Reference to TargetExecutionsTable
- **Permissions (Lines 620-637)**:
  - DynamoDB: PutItem on TargetExecutionsTable
  - Step Functions: DescribeExecution to get full execution details

**EventBridge Rule (Lines 749-780)**
- **Resource**: `ExecutionStatusEventRule` - AWS::Events::Rule
- **Configuration**:
  - Triggers on: Step Functions Execution Status Change
  - Filters: ExecutorStateMachine, status in [SUCCEEDED, FAILED, TIMED_OUT, ABORTED]
  - Target: PostprocessingLambda
- **Purpose**: Automatically invokes postprocessing when execution completes

**Executor State Machine Role (Lines 670-744)**
- **Resource**: `ExecutorStateMachineRole` - AWS::IAM::Role
- **Permissions (Lines 684-737)**:
  - Lambda: InvokeFunction on helper Lambdas
  - ECS: RunTask, StopTask, DescribeTasks (wildcard for any ECS target)
  - Step Functions: StartExecution, DescribeExecution, StopExecution (wildcard for nested executions)
  - IAM: PassRole to `ecs-tasks.amazonaws.com` (for ECS task execution roles)
  - X-Ray: Tracing operations
  - EventBridge: PutTargets, PutRule, DescribeRule (for managed rules)

---

### 3. **ui-vite/** - React Web Application

The Vite-based React single-page application for browser-based management.

#### Purpose
- User-friendly web interface for all API operations
- Visual schedule and execution management
- User authentication via Cognito Hosted UI
- Real-time execution history viewing

#### Build Process
- Built using Vite: `npm run build` in ui-vite/ directory
- Produces optimized production build in `ui-vite/build/` directory
- Build outputs: HTML, CSS, JavaScript bundles, static assets

#### Deployment Integration
- Build artifacts uploaded to S3 StaticFilesBucket after SAM deployment
- Served directly from S3 via API Gateway integration (not through Lambda)
- API Gateway routes root (`/`) and all non-API paths (`/{proxy+}`) to S3
- SPA routing: 404 errors return index.html for client-side routing
- Cache headers: Static assets cached for 1 year, index.html set to no-cache

---

### 4. **template.yaml** - Infrastructure as Code

AWS SAM template defining all infrastructure resources.

#### Purpose
- Declarative infrastructure definition
- Automated resource provisioning
- Parameter-based multi-environment support
- Output values for deployment information

#### Parameters (Lines 12-24)
- `Owner` - Email address for resource tagging and admin bootstrap
- `Environment` - Deployment stage (dev/staging/prod)
- `StackName` - Prefix for all resource names

#### Globals (Lines 29-64)
- Applies to all Lambda functions
- Runtime: Python 3.13
- Timeout: 30 seconds (default)
- Memory: 512 MB (default)
- X-Ray tracing enabled
- Common environment variables
- Resource tagging

#### Stack Outputs (Lines 976-1064)
- API URL with environment stage
- Lambda function name
- DynamoDB table names
- Cognito User Pool details
- Cognito Hosted UI URL
- S3 static files bucket name and ARN
- React app URL (same as API URL root)
- API documentation URL
- Step Functions state machine details
- Helper Lambda ARNs

---

### 5. **quickdeploy.ps1** - Automated Deployment Script

PowerShell script for one-command deployment.

#### Purpose
- Streamlines the entire deployment process
- Ensures UI is built and bundled
- Validates and deploys SAM application
- Configures Cognito post-deployment

#### Deployment Flow (Lines 1-150)
1. **Read Configuration** (Lines 20-35): Extract stack name from samconfig.toml
2. **Build UI** (Lines 39-50): `npm run build` in ui-vite/ directory
3. **SAM Validate** (Lines 53-60): `sam validate --lint`
4. **SAM Build** (Lines 63-70): `sam build`
5. **SAM Deploy** (Lines 73-81): `sam deploy --no-confirm-changeset --no-fail-on-empty-changeset`
6. **Upload UI to S3** (Lines 84-100): Sync ui-vite/build/ to StaticFilesBucket
7. **Configure Cognito** (Lines 115-135): Update logout/callback URLs using AWS CLI

#### Configuration Management
- Uses `samconfig.toml` for deployment parameters
- Retrieves stack outputs via CloudFormation describe-stacks
- Dynamically configures Cognito URLs based on API Gateway endpoint

---

### 6. **samconfig.toml** - SAM Configuration

Stores deployment parameters for the SAM CLI.

#### Purpose
- Eliminates need for `--guided` on subsequent deploys
- Stores parameter values (Owner, Environment, StackName)
- Defines deployment options (region, capabilities, etc.)

---

### 7. **sample-ecs-task/** - ECS Target Example

Example ECS task implementation showing how to create compatible ECS targets.

#### Purpose
- Reference implementation for ECS task integration
- Demonstrates task token callback pattern
- Shows how to receive execution payload from Step Functions

#### Integration Pattern
1. Step Functions passes `TASK_TOKEN` and `EXECUTION_PAYLOAD` as environment variables
2. ECS task performs work with payload
3. Task calls `SendTaskSuccess` or `SendTaskFailure` with task token
4. Step Functions resumes execution with result

---

## Execution Flow Diagrams

### Scheduled Execution Flow

```
┌─────────────────────┐
│ EventBridge         │
│ Scheduler           │  Triggered by cron/rate expression
└──────────┬──────────┘
           │ 1. Assume EventBridgeSchedulerRole
           │ 2. Invoke with tenant_id, target_alias, schedule_id, payload
           ▼
┌─────────────────────┐
│ ExecutorStateMachine│
│ (Step Functions)    │
└──────────┬──────────┘
           │ State: Preprocessing
           ▼
┌─────────────────────┐
│ PreprocessingLambda │
└──────────┬──────────┘
           │ 1. Query TenantMappingsTable (tenant_id + target_alias → target_id)
           │ 2. Query TargetsTable (target_id → target config)
           │ 3. Merge schedule payload with target defaults
           │ 4. Return: target_arn, target_type, merged_payload, target_config
           ▼
┌─────────────────────┐
│ ExecutorStateMachine│
│ State: Choice       │
└──────────┬──────────┘
           │ Route based on target_type
           ├─────────────┬───────────────┬────────────────┐
           ▼             ▼               ▼                ▼
    ┌──────────┐  ┌─────────┐    ┌─────────────┐   ┌─────────┐
    │ Lambda   │  │ ECS     │    │ Step        │   │ Fail    │
    │ Helper   │  │ RunTask │    │ Functions   │   │ State   │
    └────┬─────┘  └────┬────┘    └──────┬──────┘   └─────────┘
         │             │                 │
         │ Invoke      │ Run task        │ Start nested
         │ target      │ with payload    │ execution
         │             │ Wait for        │ Wait for
         │             │ callback        │ completion
         ▼             ▼                 ▼
    ┌─────────────────────────────────────────┐
    │ Execution Result                        │
    │ (status, response, logs_url)            │
    └──────────────────┬──────────────────────┘
                       │
                       ▼
    ┌─────────────────────────────────────────┐
    │ ExecutorStateMachine                    │
    │ State: EventBridgeHandoff (Pass)        │
    │ Execution completes                     │
    └──────────────────┬──────────────────────┘
                       │ EventBridge detects state change
                       ▼
    ┌─────────────────────────────────────────┐
    │ ExecutionStatusEventRule                │
    │ (EventBridge Rule)                      │
    └──────────────────┬──────────────────────┘
                       │ Trigger: Status SUCCEEDED/FAILED/TIMED_OUT/ABORTED
                       ▼
    ┌─────────────────────────────────────────┐
    │ PostprocessingLambda                    │
    └──────────────────┬──────────────────────┘
                       │ 1. Call DescribeExecution to get full details
                       │ 2. Extract status, result, error
                       │ 3. Write to TargetExecutionsTable
                       │    PK: tenant_id#schedule_id
                       │    SK: execution_id
                       │    Attributes: status, result, timestamp, logs_url
                       ▼
    ┌─────────────────────────────────────────┐
    │ TargetExecutionsTable                   │
    │ (DynamoDB)                              │
    └─────────────────────────────────────────┘
```

### On-Demand Execution Flow

```
┌─────────────────────┐
│ User Browser        │
│ (React UI)          │
└──────────┬──────────┘
           │ POST /tenants/{tenant_id}/mappings/{alias}/_execute
           │ Authorization: Bearer {JWT}
           ▼
┌─────────────────────┐
│ API Gateway         │
└──────────┬──────────┘
           │ Route to AppLambda (via /api/ path)
           ▼
┌─────────────────────┐
│ AppLambda           │
│ (FastAPI)           │
└──────────┬──────────┘
           │ 1. Verify JWT token (Cognito)
           │ 2. Check UserMappingsTable (user has access to tenant?)
           │ 3. Generate unique schedule ID (adhoc-{uuid})
           │ 4. Create one-time EventBridge Schedule:
           │    - Expression: at({current_time + 1 minute})
           │    - Target: ExecutorStateMachine
           │    - Auto-delete after execution
           │ 5. Return schedule ID and query URL to user
           ▼
┌─────────────────────┐
│ EventBridge         │
│ Scheduler           │  Fires at scheduled time (1 minute from now)
└──────────┬──────────┘
           │ Assumes EventBridgeSchedulerRole
           │ Invokes ExecutorStateMachine with tenant_id, target_alias, payload
           ▼
┌─────────────────────┐
│ ExecutorStateMachine│
│ (Step Functions)    │
└──────────┬──────────┘
           │ ... (Same flow as scheduled execution)
           ▼
    (See Scheduled Execution Flow above)
```

---

## Security Architecture

### IAM Roles and Permissions

**Three-Tier Permission Model**:

1. **AppLambdaRole** - API Layer (Lines 1038-1148)
   - **Can**: Full CRUD on all six DynamoDB tables (including GSI access)
   - **Can**: Manage EventBridge Scheduler (create/update/delete schedules, schedule groups)
   - **Can**: Pass EventBridgeSchedulerRole to EventBridge Scheduler
   - **Can**: RedriveExecution and DescribeExecution on ExecutorStateMachine
   - **Can**: Manage Cognito users (create, delete, set password, list users)
   - **Can**: Read secrets from Secrets Manager
   - **Cannot**: Directly invoke target Lambda functions, run ECS tasks, or start Step Functions
   - **Rationale**: API manages scheduling and data but doesn't execute targets directly (security separation)

2. **EventBridgeSchedulerRole** - Scheduler (Lines 658-694)
   - **Can**: ONLY start ExecutorStateMachine executions (highly restricted scope)
   - **Cannot**: Do anything else (no DynamoDB, Lambda, ECS, or other AWS service access)
   - **Rationale**: Principle of least privilege - scheduler has minimal permissions needed for its job

3. **ExecutorStateMachineRole** - Execution Engine (Lines 908-996)
   - **Can**: Invoke PreprocessingLambda, LambdaExecutionHelperLambda, PostprocessingLambda
   - **Can**: Run any ECS task, stop tasks, describe tasks (wildcard for flexibility)
   - **Can**: Start, stop, describe any Step Functions execution (for nested executions)
   - **Can**: PassRole to ECS tasks (restricted to ecs-tasks.amazonaws.com service)
   - **Can**: X-Ray tracing operations
   - **Can**: EventBridge rule management (for Step Functions managed rules)
   - **Rationale**: Centralized execution authority - single point for broad invocation permissions

4. **Helper Lambda Roles** - Preprocessing/Execution/Postprocessing
   - **PreprocessingLambdaRole** (Lines 485-518): Read TargetsTable and TenantMappingsTable
   - **LambdaExecutionHelperRole** (Lines 543-581): Invoke Lambdas, read CloudWatch Logs
   - **PostprocessingLambdaRole** (Lines 607-646): Write TargetExecutionsTable, describe Step Functions executions

### Multi-Tenancy Isolation

**What is Multi-Tenancy?**
Multi-tenancy means multiple organizations (tenants) share the same application instance, but each tenant's data is completely isolated from others. Think of it like an apartment building - everyone shares the same building and utilities, but each apartment is private.

**Data Isolation** (keeping data separate):
- All DynamoDB tables use `tenant_id` as the partition key (PK) or part of a composite key
- Every query automatically filters by tenant_id, so tenants can only see their own data
- User access controlled via UserMappingsTable (maps user email → allowed tenant IDs)
- Admin tenant has special privileges for cross-tenant management

**Access Control Flow** (how we verify access):
1. User authenticates with AWS Cognito (gets a JWT token proving identity)
2. JWT contains user email in the "sub" claim (subject identifier)
3. API queries UserMappingsTable with user email to find allowed tenants
4. Returns list of tenant IDs user can access
5. API verifies requested tenant_id is in user's allowed list
6. If not allowed: HTTP 403 Forbidden error

**Admin Privileges** (special super-user access):
- Members of the `admin` tenant (created automatically at startup)
- Can manage targets (add/update/delete Lambda/ECS/Step Functions definitions)
- Can access all tenants' data for system administration
- Can manage user-tenant mappings (grant/revoke tenant access)

---

## Deployment Architecture

### Resource Naming Strategy

All AWS resources follow a consistent naming pattern for easy identification:
```
${StackName}-${Environment}-${ResourceType}-${StackIdSuffix}
```

**Example**: `sts-dev-api-a1b2c3d4`

**Components explained**:
- `StackName`: Parameter from deployment (default: "sts" for Serverless Task Scheduler)
- `Environment`: Parameter for deployment stage (e.g., "dev", "staging", "prod")
- `ResourceType`: Descriptive name for the resource (e.g., "api", "targets", "executor-sfn")
- `StackIdSuffix`: 8-character suffix extracted from CloudFormation stack ID (ensures global uniqueness)

**Why this pattern?**
- **Easy identification**: Instantly see which environment and stack a resource belongs to
- **No naming conflicts**: Multiple teams can deploy stacks without name collisions
- **Clear ownership**: Know who owns the resource and its purpose at a glance
- **Cost tracking**: Consistent tagging makes cost allocation reports easier to understand

### Environment Variables Flow

**Global Variables** (Lines 39-64 in template.yaml):
- Applied to all Lambda functions automatically
- Includes DB_TARGET, table names, Cognito config, scheduler config

**Function-Specific Variables**:
- AppLambda also receives: `STEP_FUNCTIONS_EXECUTOR_ARN`
- Preprocessing: `DYNAMODB_TABLE`, `DYNAMODB_TENANT_TABLE`
- Postprocessing: `DYNAMODB_EXECUTIONS_TABLE`

### API Gateway Stage Routing

**How API Gateway stages work**:
- API Gateway creates a deployment "stage" named after the `Environment` parameter
- Each stage has its own URL with the stage name in the path
- Base path format: `https://{api-id}.execute-api.{region}.amazonaws.com/{environment}/`
- Example: `https://xyz123.execute-api.us-east-1.amazonaws.com/dev/`

**How routing works internally**:
- When a request comes in like `https://.../dev/api/user/info`
- API Gateway strips the stage prefix (`/dev`) before sending to Lambda
- Lambda receives just `/api/user/info`
- FastAPI's `root_path` is set to `/api` to match incoming paths
- This ensures API documentation URLs and redirects work correctly

**Why stages?**
Stages let you have multiple deployments (dev, staging, prod) from the same API Gateway, each with its own configuration and endpoints.

---

## Data Models

### Targets Table Schema
```
{
  "target_id": "email-sender-v1",           // PK
  "target_name": "Email Sender",
  "target_description": "Sends emails via SES",
  "target_arn": "arn:aws:lambda:us-east-1:123:function:send-email",
  "target_type": "lambda",                  // lambda | ecs | stepfunctions
  "target_config": {},                      // ECS: cluster, task_definition, etc.
  "target_parameter_schema": {...},         // JSON Schema
  "target_response_schema": {...},          // JSON Schema
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

### Tenant Mappings Table Schema
```
{
  "tenant_id": "acme-corp",                 // PK
  "target_alias": "email-sender",           // SK
  "target_id": "email-sender-v1",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

### Schedules Table Schema
```
{
  "tenant_id": "acme-corp",                 // PK
  "schedule_id": "daily-report-9am",        // SK
  "target_alias": "report-generator",
  "schedule_expression": "cron(0 9 * * ? *)",
  "timezone": "America/New_York",
  "state": "ENABLED",                       // ENABLED | DISABLED
  "target_input": {...},                    // Payload to pass to target
  "description": "Daily sales report at 9 AM",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

### Executions Table Schema
```
{
  "tenant_schedule": "acme-corp#daily-report-9am",  // PK (composite)
  "execution_id": "abc123-def456-789",               // SK
  "tenant_id": "acme-corp",
  "schedule_id": "daily-report-9am",
  "target_alias": "report-generator",
  "tenant_target": "acme-corp#report-generator",     // GSI PK
  "timestamp": "2024-01-01T09:00:00Z",               // GSI SK
  "status": "SUCCEEDED",                             // SUCCEEDED | FAILED | RUNNING
  "result": {...},                                   // Target response payload
  "error": null,                                     // Error details if failed
  "logs_url": "https://console.aws.amazon.com/...", // CloudWatch Logs deep link
  "lambda_request_id": "abc-123-def",                // For log correlation
  "ttl": 1735689600                                  // Unix timestamp for auto-deletion
}
```

### User Mappings Table Schema
```
{
  "user_id": "user@example.com",            // PK (email)
  "tenant_id": "acme-corp",                 // SK
  "role": "user",                           // user | admin
  "created_at": "2024-01-01T00:00:00Z",
  "create_user": "admin@example.com"
}
```

---

## Key Design Decisions

### Why Step Functions Instead of Lambda Executor?

**Previous Architecture**: A single Lambda Executor function handled all execution logic in code.

**Current Architecture**: Step Functions state machine orchestrates the execution flow visually.

**Why the change? (Benefits)**:
1. **Visual Workflow**: State machine provides a graphical flowchart of the execution process - you can see exactly what's happening
2. **Built-in Error Handling**: Parallel states with centralized catch/finally blocks (like try-catch in programming)
3. **Native Integration**: Direct support for ECS and nested Step Functions without writing custom invocation code
4. **Execution History**: Full execution history automatically saved in Step Functions console for debugging
5. **Retry Logic**: Declare retry behavior in configuration instead of writing retry loops in code
6. **Long-Running Support**: ECS tasks can run longer than Lambda's 15-minute maximum timeout
7. **Scalability**: Step Functions automatically handles concurrent executions without manual scaling configuration

**Trade-offs** (nothing is perfect):
- Slightly higher cost per execution compared to Lambda-only approach
- More complex initial setup and learning curve
- Additional Lambda functions needed for pre/post processing steps

### Why EventBridge for Postprocessing?

Instead of calling the postprocessing Lambda directly from the state machine's final step, we use an EventBridge rule that automatically triggers when the execution finishes.

**Why this approach? (Benefits)**:
1. **Decoupling**: State machine doesn't need to know postprocessing exists - cleaner separation of concerns
2. **Reliability**: EventBridge guarantees at-least-once delivery (won't lose the event)
3. **Automatic Retry**: EventBridge automatically retries if postprocessing Lambda fails temporarily
4. **Extensibility**: Easy to add more handlers (e.g., send email notification, update dashboard) without changing the state machine
5. **Error Isolation**: If postprocessing fails, it doesn't affect the main execution's success status

**How it works**:
- Step Functions emits an event when execution finishes (status: SUCCEEDED, FAILED, TIMED_OUT, ABORTED)
- EventBridge rule listens for these events and triggers PostprocessingLambda
- Postprocessing reads full execution details and saves to DynamoDB

### Why S3 for Static Files?

Instead of serving static files through the FastAPI Lambda function, the React UI is hosted in S3 and served via API Gateway integration.

**Benefits**:
1. **Performance**: S3 serves static files faster than Lambda without cold start delays
2. **Cost**: S3 + API Gateway is cheaper than Lambda invocations for static content
3. **Scalability**: S3 handles high traffic automatically without Lambda concurrency limits
4. **Caching**: CloudFront-style cache headers work better with direct S3 integration
5. **Separation of Concerns**: Static UI separated from dynamic API logic

**Implementation**:
- API Gateway defines three route patterns:
  - `/api/{proxy+}` → Routes to AppLambda for API calls
  - `/` → Serves index.html from S3 (root path)
  - `/{proxy+}` → Serves files from S3, falls back to index.html for SPA routing
- S3 bucket is private; API Gateway uses IAM role (ApiGatewayS3Role) to access files
- Cache headers: Static assets cached for 1 year, index.html not cached for updates

---

## Monitoring and Observability

### CloudWatch Logs

**Log Groups**:
- `/aws/lambda/{StackName}-{Environment}-api-{suffix}` - API Lambda logs
- `/aws/lambda/{StackName}-{Environment}-executor-preprocessing-{suffix}` - Preprocessing logs
- `/aws/lambda/{StackName}-{Environment}-executor-lambda-helper-{suffix}` - Lambda helper logs
- `/aws/lambda/{StackName}-{Environment}-executor-postprocessing-{suffix}` - Postprocessing logs

**Log Retention**:
- All Lambda log groups configured with 14-day retention
- Reduces storage costs while maintaining recent history for debugging

**Target Lambda Logs**:
- Each target Lambda/ECS task logs to its own log group
- Lambda Execution Helper captures log stream URL for easy navigation

### X-Ray Tracing

All Lambda functions and the Step Functions state machine have X-Ray tracing enabled.

**Trace Flow**:
1. API Gateway request
2. AppLambda invocation
3. ExecutorStateMachine start
4. Preprocessing, execution helper, and postprocessing Lambda invocations
5. Target service invocation

**Service Map**: Shows dependencies between API Gateway, Lambda, Step Functions, DynamoDB, and target services.

### Execution History

**DynamoDB Executions Table**:
- Queryable by tenant and schedule (PK: `tenant_id#schedule_id`)
- Queryable by tenant and target via GSI (PK: `tenant_id#target_alias`)
- Chronologically sorted by timestamp
- Includes full result payload and error details
- Direct links to CloudWatch Logs

**Step Functions Execution History**:
- Full state transition history
- Input/output of each state
- Error details with stack traces
- Execution timeline visualization

---

## Cost Optimization

### DynamoDB On-Demand Billing
- No capacity planning required
- Pay only for actual reads/writes performed
- Automatic scaling for traffic spikes
- Ideal for unpredictable workload patterns

### Lambda Memory Optimization
- API Lambda: 512 MB (handles API logic with good performance)
- Helper Lambdas: 256 MB (lightweight processing tasks)
- Memory settings tuned for balance between cost and performance
- Right-sizing reduces cost without sacrificing speed

### S3 Static File Hosting
- S3 storage costs significantly less than bundling files in Lambda packages
- Reduced Lambda package size improves cold start times
- No Lambda invocation costs for serving static content
- Efficient serving of images, CSS, and JavaScript without compute charges

### Execution History TTL
- TargetExecutionsTable has TTL enabled on `ttl` attribute
- Automatic deletion of old executions (e.g., after 30/60/90 days)
- Reduces long-term storage costs
- Configurable per schedule or globally

### Step Functions Express vs Standard
- Currently uses STANDARD for full execution history and long-running support
- Consider EXPRESS for high-volume, short-duration executions (< 5 minutes)
- EXPRESS is significantly cheaper but lacks detailed execution history

---

## Future Enhancements

### Potential Improvements
1. **CloudFront CDN**: Add CloudFront in front of API Gateway for global edge caching and lower latency
2. **API Gateway HTTP API**: Migrate from REST API to HTTP API for lower cost and simpler configuration
3. **Multi-Region Support**: Deploy to multiple regions with Route 53 failover for high availability
4. **Enhanced Monitoring**: CloudWatch dashboards, alarms, and SNS notifications for execution failures
5. **Execution History Archival**: Archive old executions to S3 before TTL deletion for long-term storage
6. **Advanced Scheduling**: Support for schedule dependencies and conditional execution workflows
7. **Webhook Targets**: Add support for HTTP webhook targets (invoke external APIs)
8. **Batch Execution**: Execute multiple targets in parallel or sequence with coordination
9. **Execution Approval Workflow**: Require manual approval before executing high-risk targets

---

## Conclusion

The Serverless Task Scheduler is a production-ready, multi-tenant execution platform that leverages AWS serverless services for scalability, reliability, and security. The modular design separates concerns between API management, execution orchestration, and data storage, making the system both maintainable and extensible.

**Key Strengths**:
- **Multi-tenant isolation**: Data separated at the database level for security
- **Centralized execution**: All task execution flows through Step Functions for consistent security controls and observability
- **Comprehensive IAM separation**: Follows least privilege principle with distinct roles for API, scheduler, and executor
- **Automated deployment**: Single-command deployment with infrastructure as code
- **Built-in execution history**: Complete audit trail stored automatically in DynamoDB
- **Multiple target types**: Supports Lambda functions, ECS containers, and Step Functions workflows
- **Optimized architecture**: S3 for static files, on-demand DynamoDB, and efficient Lambda sizing reduce costs

**Operational Simplicity**:
- Single command deployment via `quickdeploy.sh` script
- Automatic resource naming and tagging for easy management
- Environment-based configuration (dev, staging, prod)
- No servers to manage - fully serverless
- Pay-per-use pricing model keeps costs aligned with usage

**Modern Web Architecture**:
- React UI served from S3 for optimal performance
- API Gateway integrates both static files and dynamic API
- FastAPI backend with automatic OpenAPI documentation
- JWT-based authentication via AWS Cognito
