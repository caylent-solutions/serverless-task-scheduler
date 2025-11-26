# Serverless Task Scheduler - Architecture Documentation

## Overview

The Serverless Task Scheduler (STS) is a multi-tenant AWS serverless application that manages and executes scheduled tasks across Lambda, ECS, and Step Functions. The application uses a modular architecture with clear separation between the API layer, execution orchestration, and data storage.

---

## Top-Level Artifacts

### 1. **ExecutionAPI/** - REST API Service

The FastAPI-based REST API that provides the management interface for the entire platform.

#### Purpose
- User authentication and authorization via AWS Cognito
- CRUD operations for targets, tenants, mappings, schedules, and users
- Direct execution endpoint for on-demand task execution
- Serves the React web UI for browser-based management
- Dynamic OpenAPI schema generation based on available targets

#### Key Files
- [app/main.py](ExecutionAPI/app/main.py) - FastAPI application with middleware, routing, and authentication
- [app/lambda_handler.py](ExecutionAPI/app/lambda_handler.py) - AWS Lambda handler using Mangum adapter
- [app/routers/](ExecutionAPI/app/routers/) - API route handlers (targets, tenants, schedules, auth, user)
- [app/models/](ExecutionAPI/app/models/) - Pydantic models for request/response validation
- [app/awssdk/](ExecutionAPI/app/awssdk/) - AWS SDK wrappers (DynamoDB, Cognito, EventBridge)
- [app/wwwroot/](ExecutionAPI/app/wwwroot/) - Built React UI static files (populated during deployment)
- [requirements.txt](ExecutionAPI/requirements.txt) - Python dependencies

#### Related AWS Resources (from template.yaml)

**API Gateway (Lines 360-377)**
- **Resource**: `ApiGateway` - AWS::Serverless::Api
- **Configuration**:
  - REST API with stage name from `Environment` parameter
  - Routes `/{proxy+}` and `/` to AppLambda
  - Binary media type support for images
  - X-Ray tracing enabled
- **Purpose**: HTTP entry point that routes all requests to the FastAPI Lambda

**App Lambda Function (Lines 387-413)**
- **Resource**: `AppLambda` - AWS::Serverless::Function
- **Configuration**:
  - Handler: `app/lambda_handler.handler`
  - Runtime: Python 3.13
  - CodeUri: `ExecutionAPI/`
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
1. **TargetsTable (Lines 75-94)**: Stores target definitions
   - PK: `target_id` (string)
   - Stores: ARN, type (lambda/ecs/stepfunctions), config, parameter schema

2. **TenantsTable (Lines 100-119)**: Stores tenant (organization) definitions
   - PK: `tenant_id` (string)
   - Stores: Tenant name, description, metadata

3. **TenantMappingsTable (Lines 125-148)**: Maps tenant aliases to targets
   - PK: `tenant_id` (string)
   - SK: `target_alias` (string)
   - Stores: Mapping between friendly names and actual target IDs

4. **TargetExecutionsTable (Lines 158-197)**: Execution history
   - PK: `tenant_schedule` (composite: `tenant_id#schedule_id`)
   - SK: `execution_id` (string)
   - GSI: `tenant-target-index` (tenant_target + timestamp) for listing by tenant/target
   - TTL enabled on `ttl` attribute for automatic cleanup
   - Stores: Execution status, response payload, CloudWatch logs URL, Lambda request ID

5. **SchedulesTable (Lines 199-233)**: Schedule definitions
   - PK: `tenant_id` (string)
   - SK: `schedule_id` (string)
   - GSI: `tenant-target-index` (tenant_id + target_alias)
   - Stores: Cron expression, schedule state, target input payload

6. **UserMappingsTable (Lines 241-273)**: User-to-tenant access control
   - PK: `user_id` (email address, string)
   - SK: `tenant_id` (string)
   - GSI: `tenant-index` (tenant_id + user_id) for reverse lookup
   - Stores: Which users can access which tenants

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

---

### 2. **ExecutorStepFunction/** - Execution Orchestration Engine

The Step Functions-based execution engine that handles all target invocations with proper error handling and logging.

#### Purpose
- Orchestrates execution of Lambda, ECS, and Step Functions targets
- Centralizes execution logic for security (single point of invocation)
- Resolves tenant mappings to actual targets
- Merges schedule payloads with target defaults
- Captures execution results and CloudWatch logs
- Records execution history to DynamoDB

#### Key Files
- [state_machine.json](ExecutorStepFunction/state_machine.json) - Step Functions ASL definition
- [preprocessing.py](ExecutorStepFunction/preprocessing.py) - Resolves targets and merges payloads
- [lambda_execution_helper.py](ExecutorStepFunction/lambda_execution_helper.py) - Invokes Lambda targets and captures logs
- [postprocessing.py](ExecutorStepFunction/postprocessing.py) - Records execution results to DynamoDB

#### Related AWS Resources (from template.yaml)

**Executor State Machine (Lines 651-668)**
- **Resource**: `ExecutorStateMachine` - AWS::Serverless::StateMachine
- **Configuration**:
  - Type: STANDARD (long-running, full history)
  - DefinitionUri: `ExecutorStepFunction/state_machine.json`
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
  - CodeUri: `ExecutorStepFunction/`
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
  - CodeUri: `ExecutorStepFunction/`
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
  - CodeUri: `ExecutorStepFunction/`
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

### 3. **ui/** - React Web Application

The React-based single-page application for browser-based management.

#### Purpose
- User-friendly web interface for all API operations
- Visual schedule and execution management
- User authentication via Cognito Hosted UI
- Real-time execution history viewing

#### Build Process
- Built using `npm run build` (see [quickdeploy.ps1](quickdeploy.ps1) lines 8-21)
- Output from `ui/build/*` copied to `ExecutionAPI/app/wwwroot/` (lines 23-39)
- Static files served by AppLambda via custom file handler (main.py lines 189-254)

#### Deployment Integration
- Build artifacts bundled with AppLambda deployment package
- Served from `/app/*` route with SPA routing support
- Index.html served for all non-existent paths (client-side routing)

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

#### Stack Outputs (Lines 903-973)
- API URL with environment stage
- Lambda function name
- DynamoDB table names
- Cognito User Pool details
- Cognito Hosted UI URL
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

#### Deployment Flow (Lines 1-115)
1. **Build UI** (Lines 8-21): `npm run build` in ui/
2. **Copy Assets** (Lines 23-39): `ui/build/*` → `ExecutionAPI/app/wwwroot/`
3. **SAM Validate** (Lines 41-48): `sam validate --lint`
4. **SAM Build** (Lines 50-57): `sam build`
5. **SAM Deploy** (Lines 59-66): `sam deploy --no-confirm-changeset`
6. **Configure Cognito** (Lines 82-109): Update logout/callback URLs using AWS CLI

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
           │ Route to AppLambda
           ▼
┌─────────────────────┐
│ AppLambda           │
│ (FastAPI)           │
└──────────┬──────────┘
           │ 1. Verify JWT token (Cognito)
           │ 2. Check UserMappingsTable (user has access to tenant?)
           │ 3. Prepare execution input (tenant_id, target_alias, payload)
           │ 4. StartExecution on ExecutorStateMachine
           │ 5. If async=true: Return immediately with execution_id
           │    If async=false: Wait for completion and return result
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

1. **AppLambdaRole** - API Layer (Lines 794-898)
   - **Can**: Manage DynamoDB tables, EventBridge schedules, Cognito users, Secrets Manager
   - **Can**: Invoke ExecutorStateMachine (start executions)
   - **Cannot**: Directly invoke target Lambda functions, run ECS tasks, or start Step Functions
   - **Rationale**: API should manage schedules but not execute targets directly

2. **EventBridgeSchedulerRole** - Scheduler (Lines 423-454)
   - **Can**: ONLY start ExecutorStateMachine executions
   - **Cannot**: Do anything else
   - **Rationale**: Principle of least privilege - scheduler doesn't need broad permissions

3. **ExecutorStateMachineRole** - Execution Engine (Lines 670-744)
   - **Can**: Invoke any Lambda, run any ECS task, start any Step Functions execution
   - **Can**: PassRole to ECS tasks
   - **Rationale**: Centralized execution authority - single point for broad invocation permissions

4. **Helper Lambda Roles** - Preprocessing/Execution/Postprocessing
   - **PreprocessingLambdaRole** (Lines 485-518): Read TargetsTable and TenantMappingsTable
   - **LambdaExecutionHelperRole** (Lines 543-581): Invoke Lambdas, read CloudWatch Logs
   - **PostprocessingLambdaRole** (Lines 607-646): Write TargetExecutionsTable, describe Step Functions executions

### Multi-Tenancy Isolation

**Data Isolation**:
- All DynamoDB tables use `tenant_id` as partition key or part of composite key
- User access controlled via UserMappingsTable (user_id → tenant_id mappings)
- Admin tenant has special privileges for cross-tenant management

**Access Control Flow**:
1. User authenticates with Cognito (JWT token)
2. JWT contains user email (sub claim)
3. API queries UserMappingsTable with user email
4. Returns list of tenant IDs user can access
5. API verifies requested tenant_id is in user's allowed list
6. If not: HTTP 403 Forbidden

**Admin Privileges**:
- Members of `admin` tenant (created at startup, Lines 321-395 in main.py)
- Can manage targets (add/update/delete Lambda/ECS/Step Functions definitions)
- Can access all tenants' data
- Can manage user-tenant mappings

---

## Deployment Architecture

### Resource Naming Strategy

All resources use a consistent naming pattern:
```
${StackName}-${Environment}-${ResourceType}-${StackIdSuffix}
```

Example: `sts-dev-api-a1b2c3d4`

- `StackName`: Parameter (default: "sts")
- `Environment`: Parameter (e.g., "dev", "prod")
- `ResourceType`: Descriptive name (e.g., "api", "targets", "executor-sfn")
- `StackIdSuffix`: 8-character suffix from CloudFormation stack ID (ensures uniqueness)

**Benefits**:
- Easy to identify resources by environment
- No naming conflicts when deploying multiple stacks
- Clear ownership and purpose in AWS console
- Consistent tagging for cost allocation

### Environment Variables Flow

**Global Variables** (Lines 39-64 in template.yaml):
- Applied to all Lambda functions automatically
- Includes DB_TARGET, table names, Cognito config, scheduler config

**Function-Specific Variables**:
- AppLambda also receives: `STEP_FUNCTIONS_EXECUTOR_ARN`
- Preprocessing: `DYNAMODB_TABLE`, `DYNAMODB_TENANT_TABLE`
- Postprocessing: `DYNAMODB_EXECUTIONS_TABLE`

### API Gateway Stage Routing

- API Gateway creates a single stage named after `Environment` parameter
- Base path: `https://{api-id}.execute-api.{region}.amazonaws.com/{environment}/`
- Example: `https://xyz123.execute-api.us-east-1.amazonaws.com/dev/`
- FastAPI's `root_path` set to `/{environment}` for correct URL generation

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

**Previous Architecture**: Single Lambda Executor function handled all execution logic.

**Current Architecture**: Step Functions state machine orchestrates execution flow.

**Benefits**:
1. **Visual Workflow**: State machine provides graphical representation of execution flow
2. **Built-in Error Handling**: Parallel state with centralized catch/finally
3. **Native Integration**: Direct ECS and nested Step Functions support without custom code
4. **Execution History**: Full execution history in Step Functions console
5. **Retry Logic**: Declarative retry configuration without custom code
6. **Long-Running Support**: ECS tasks can run longer than Lambda's 15-minute limit
7. **Scalability**: Step Functions handles concurrency automatically

**Trade-offs**:
- Slightly higher cost per execution (Step Functions vs Lambda)
- More complex initial setup
- Additional Lambda functions for pre/post processing

### Why EventBridge for Postprocessing?

Instead of calling postprocessing directly from the state machine, we use an EventBridge rule that triggers on execution status changes.

**Benefits**:
1. **Decoupling**: State machine doesn't need to know about postprocessing
2. **Reliability**: EventBridge guarantees at-least-once delivery
3. **Retry**: EventBridge automatically retries failed invocations
4. **Extensibility**: Easy to add additional handlers (e.g., SNS notifications)
5. **Error Handling**: Postprocessing failures don't affect execution status

### Why Custom Static File Handler?

Instead of using FastAPI's StaticFiles, the application uses a custom file handler (main.py lines 189-254).

**Reason**: API Gateway REST APIs always strip the stage name (e.g., `/dev`) before passing requests to Lambda. This causes path mismatches with StaticFiles mounted at `/app` when accessed via `/dev/app`.

**Custom Handler Features**:
- Multiple layers of path traversal protection
- SPA routing support (serves index.html for non-existent paths)
- Proper MIME type detection
- Security validations using `os.path.normpath()` and `os.path.realpath()`

**Note**: Snyk security scanner flags this as a potential path traversal vulnerability because it uses `FileResponse` with user input. The code includes comprehensive security measures, but static analysis tools cannot verify custom validation logic.

---

## Monitoring and Observability

### CloudWatch Logs

**Log Groups**:
- `/aws/lambda/{StackName}-{Environment}-api-{suffix}` - API Lambda logs
- `/aws/lambda/{StackName}-{Environment}-executor-preprocessing-{suffix}` - Preprocessing logs
- `/aws/lambda/{StackName}-{Environment}-executor-lambda-helper-{suffix}` - Lambda helper logs
- `/aws/lambda/{StackName}-{Environment}-executor-postprocessing-{suffix}` - Postprocessing logs

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
- Pay only for reads/writes
- Automatic scaling for traffic spikes

### Lambda Memory Optimization
- API Lambda: 512 MB (handles web UI serving and API logic)
- Helper Lambdas: 256 MB (lightweight processing)
- Tuned for balance between cost and performance

### Execution History TTL
- TargetExecutionsTable has TTL enabled on `ttl` attribute
- Automatic deletion of old executions (e.g., after 30/60/90 days)
- Reduces storage costs
- Configurable per schedule or globally

### Step Functions Express vs Standard
- Currently uses STANDARD for full execution history and long-running support
- Consider EXPRESS for high-volume, short-duration executions (< 5 minutes)
- EXPRESS is cheaper but lacks detailed history

---

## Future Enhancements

### Potential Improvements
1. **S3 + CloudFront for Static Files**: Move React UI to S3 with CloudFront for better performance and Snyk compliance
2. **API Gateway HTTP API**: Migrate from REST API to HTTP API for lower cost and better stage path handling
3. **Multi-Region Support**: Deploy to multiple regions with Route 53 failover
4. **Enhanced Monitoring**: CloudWatch dashboards, alarms, and SNS notifications for execution failures
5. **Execution History Archival**: Archive old executions to S3 before TTL deletion
6. **Advanced Scheduling**: Support for schedule dependencies and conditional execution
7. **Webhook Targets**: Add support for HTTP webhook targets
8. **Batch Execution**: Execute multiple targets in parallel or sequence
9. **Execution Approval Workflow**: Require manual approval before executing high-risk targets

---

## Conclusion

The Serverless Task Scheduler is a well-architected multi-tenant execution platform that leverages AWS serverless services for scalability, reliability, and security. The modular design separates concerns between API management, execution orchestration, and data storage, making the system maintainable and extensible.

**Key Strengths**:
- Multi-tenant isolation at the database level
- Centralized execution through Step Functions for security and observability
- Comprehensive IAM role separation following least privilege
- Automated deployment with infrastructure as code
- Built-in execution history and audit trail
- Support for multiple target types (Lambda, ECS, Step Functions)

**Operational Simplicity**:
- Single command deployment (`quickdeploy.ps1`)
- Automatic resource naming and tagging
- Environment-based configuration
- No servers to manage
- Pay-per-use pricing model
