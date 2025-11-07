# Serverless Task Scheduler (STS)

A serverless task scheduler and execution platform that lets you manage, schedule, and execute AWS Lambda functions across multiple tenants with authentication, authorization, and flexible scheduling capabilities.

## What Does This Service Do?

Imagine you have multiple teams (tenants) who need to run various AWS Lambda functions on a schedule or on-demand. This service acts as a central hub that:

1. **Manages Function Definitions** - Keeps track of what Lambda functions are available to execute
2. **Controls Access** - Ensures only authorized users can access specific tenants' resources
3. **Schedules Executions** - Runs Lambda functions automatically on schedules (like cron jobs)
4. **Executes On-Demand** - Allows immediate function execution through a REST API
5. **Provides Multi-Tenancy** - Isolates different organizations' functions and schedules

Think of it like a smart, multi-tenant task scheduler for AWS Lambda functions with built-in security and access control.

## Core Concepts

### Targets (Lambda Functions)

A **target** is a Lambda function that you want to make available for execution. Each target includes:
- A unique identifier
- The AWS ARN (Amazon Resource Name) of the Lambda function
- A schema describing what parameters it accepts
- A schema describing what it returns

**Example:** You might have a target called `send-email-v1` that points to a Lambda function that sends emails.

### Tenants (Organizations)

A **tenant** represents an organization or team using the service. Each tenant is isolated from others - they can't see or execute each other's functions.

**Example:** `acme-corp` and `globex-inc` are two different tenants, each with their own set of users and functions.

### Tenant Mappings (Function Aliases)

A **tenant mapping** connects a target to a tenant with a friendly name (alias). This allows:
- Each tenant to have their own names for functions
- Different tenants to use different versions of the same function
- Easy function upgrades without changing how tenants call them

**Example:** Both `acme-corp` and `globex-inc` might have a mapping called `email-sender`, but they could point to different versions of the email Lambda function.

### Schedules (Automated Execution)

A **schedule** automatically executes a tenant mapping at specified times using AWS EventBridge Scheduler. You can create schedules using:
- **Rate expressions**: `rate(5 minutes)` - runs every 5 minutes
- **Cron expressions**: `cron(0 12 * * ? *)` - runs daily at noon UTC
- **One-time execution**: `at(2024-12-31T23:59:59)` - runs once at a specific time

## Architecture Overview

```mermaid
graph TB
    subgraph "Users & Authentication"
        User[User]
        Cognito[AWS Cognito<br/>User Authentication]
    end

    subgraph "API Layer"
        APIGW[API Gateway]
        Lambda[FastAPI Lambda<br/>Python]
    end

    subgraph "Data Storage"
        Targets[(Targets Table<br/>Available Functions)]
        Tenants[(Tenants Table<br/>Organizations)]
        Mappings[(Mappings Table<br/>Tenant → Target)]
        Schedules[(Schedules Table<br/>Scheduled Jobs)]
        Users[(User Mappings<br/>User → Tenant Access)]
    end

    subgraph "Execution"
        EventBridge[EventBridge Scheduler<br/>Cron/Rate Triggers]
        TargetLambda[Target Lambda Functions<br/>Business Logic]
    end

    User -->|1. Authenticate| Cognito
    Cognito -->|2. JWT Token| User
    User -->|3. API Request + JWT| APIGW
    APIGW -->|4. Invoke| Lambda
    Lambda -->|5. Check Access| Users
    Lambda -->|6. Query| Targets
    Lambda -->|7. Query| Mappings
    Lambda -->|8. Execute| TargetLambda
    Lambda -->|9. Create/Update| EventBridge
    EventBridge -->|10. Trigger on Schedule| Lambda
    Lambda -->|11. Execute Scheduled Function| TargetLambda
```

## How Authentication and Authorization Work

### Authentication (Who are you?)

Users authenticate through **AWS Cognito**, which provides JWT (JSON Web Token) tokens. When you make an API request, you include this token in the `Authorization` header:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Authorization (What can you do?)

The service uses a **role-based access control** system:

1. **Admin Users**: Members of the special `admin` tenant can:
   - Manage all targets (create, update, delete Lambda function definitions)
   - Access all tenants' resources
   - Manage user-tenant assignments

2. **Regular Users**: Can only access tenants they've been explicitly granted access to:
   - View tenant mappings they have access to
   - Execute functions for their tenants
   - Create/manage schedules for their tenants

**Authorization Check Flow:**
```mermaid
sequenceDiagram
    participant User
    participant API
    participant UserMappings

    User->>API: Request with JWT Token
    API->>API: Verify JWT (Authentication)
    API->>API: Extract user email from JWT
    API->>UserMappings: Get tenants for user email
    UserMappings-->>API: List of tenant IDs
    API->>API: Check if requested tenant in list
    alt User has access
        API-->>User: Allow request
    else User lacks access
        API-->>User: 403 Forbidden
    end
```

## API Workflow Examples

### Example 1: Setting Up a Scheduled Email Report

Let's walk through creating a scheduled task that sends a daily email report.

#### Step 1: Admin Creates a Target (Lambda Function Definition)

```bash
POST /targets
Authorization: Bearer {admin-jwt-token}
Content-Type: application/json

{
  "target_id": "email-report-v1",
  "target_description": "Sends daily sales report via email",
  "target_arn": "arn:aws:lambda:us-east-1:123456789:function:send-sales-report",
  "target_parameter_schema": {
    "type": "object",
    "properties": {
      "recipient_email": {
        "type": "string",
        "format": "email"
      },
      "report_type": {
        "type": "string",
        "enum": ["daily", "weekly", "monthly"]
      }
    },
    "required": ["recipient_email", "report_type"]
  }
}
```

#### Step 2: Create a Tenant Mapping

```bash
POST /tenants/acme-corp/mappings
Authorization: Bearer {user-jwt-token}
Content-Type: application/json

{
  "tenant_id": "acme-corp",
  "target_alias": "daily-sales-report",
  "target_id": "email-report-v1"
}
```

Now `acme-corp` can execute this function using the alias `daily-sales-report`.

#### Step 3: Create a Schedule

```bash
POST /tenants/acme-corp/mappings/daily-sales-report/schedules
Authorization: Bearer {user-jwt-token}
Content-Type: application/json

{
  "schedule_expression": "cron(0 9 * * ? *)",
  "description": "Send daily sales report at 9 AM UTC",
  "timezone": "America/New_York",
  "state": "ENABLED",
  "target_input": {
    "recipient_email": "sales@acme-corp.com",
    "report_type": "daily"
  }
}
```

This creates an AWS EventBridge schedule that executes the function every day at 9 AM Eastern Time.

### Example 2: On-Demand Function Execution

You can also execute functions immediately without a schedule:

```bash
POST /tenants/acme-corp/mappings/daily-sales-report/_execute
Authorization: Bearer {user-jwt-token}
Content-Type: application/json

{
  "recipient_email": "sales@acme-corp.com",
  "report_type": "daily"
}
```

For long-running functions, use asynchronous execution:

```bash
POST /tenants/acme-corp/mappings/daily-sales-report/_execute?async=true
Authorization: Bearer {user-jwt-token}
Content-Type: application/json

{
  "recipient_email": "sales@acme-corp.com",
  "report_type": "daily"
}
```

## Schedule Expression Examples

### Rate Expressions (Simple Intervals)

- `rate(5 minutes)` - Every 5 minutes
- `rate(1 hour)` - Every hour
- `rate(7 days)` - Every 7 days

### Cron Expressions (Specific Times)

Format: `cron(minutes hours day-of-month month day-of-week year)`

- `cron(0 12 * * ? *)` - Every day at noon UTC
- `cron(15 10 ? * MON-FRI *)` - Weekdays at 10:15 AM UTC
- `cron(0 0 1 * ? *)` - First day of every month at midnight UTC
- `cron(0 18 ? * MON *)` - Every Monday at 6 PM UTC

### One-Time Execution

- `at(2024-12-31T23:59:59)` - Execute once on New Year's Eve 2024

## Variable Injection (Dependency Injection)

When you create a schedule, you specify the `target_input` - the parameters that will be passed to the Lambda function. This acts as **dependency injection** for your serverless functions.

**Example:**
```json
{
  "schedule_expression": "rate(1 hour)",
  "target_input": {
    "database_url": "${SECRET:prod-db-connection}",
    "api_key": "${SECRET:external-api-key}",
    "environment": "production"
  }
}
```

The Lambda function receives these parameters every time it executes, allowing you to:
- Configure different environments (dev, staging, prod)
- Inject credentials from AWS Secrets Manager
- Pass different parameters to different tenants

## Complete API Reference

### Authentication Required for All Endpoints

All endpoints (except `/health` and `/`) require a valid JWT token from AWS Cognito.

### Target Management (Admin Only)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /targets` | GET | List all available targets |
| `POST /targets` | POST | Create a new target (Lambda function) |
| `PUT /targets/{target_id}` | PUT | Update target definition |
| `DELETE /targets/{target_id}` | DELETE | Delete a target |

### Tenant Management (Admin Only)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /tenants` | GET | List all tenants |
| `POST /tenants` | POST | Create a new tenant |
| `PUT /tenants/{tenant_id}` | PUT | Update tenant details |
| `DELETE /tenants/{tenant_id}` | DELETE | Delete a tenant |
| `GET /tenants/{tenant_id}/users` | GET | List users with access to tenant |

### Tenant Mappings (Requires Tenant Access)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /tenants/{tenant_id}/mappings` | GET | List all mappings for a tenant |
| `POST /tenants/{tenant_id}/mappings` | POST | Create a new tenant mapping |
| `GET /tenants/{tenant_id}/mappings/{target_alias}` | GET | Get specific mapping |
| `PUT /tenants/{tenant_id}/mappings/{target_alias}` | PUT | Update a mapping |
| `DELETE /tenants/{tenant_id}/mappings/{target_alias}` | DELETE | Delete a mapping |

### Function Execution (Requires Tenant Access)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /tenants/{tenant_id}/mappings/{target_alias}/_execute` | POST | Execute a function (sync or async) |

Query Parameters:
- `async=true` - Execute asynchronously (default: false)

### Schedule Management (Requires Tenant Access)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /tenants/{tenant_id}/mappings/{target_alias}/schedules` | POST | Create a schedule |
| `PUT /tenants/{tenant_id}/mappings/{target_alias}/schedules/{schedule_id}` | PUT | Update a schedule |
| `DELETE /tenants/{tenant_id}/mappings/{target_alias}/schedules/{schedule_id}` | DELETE | Delete a schedule |
| `GET /tenants/{tenant_id}/mappings/{target_alias}/schedules` | GET | List schedules for a mapping |
| `GET /tenants/{tenant_id}/schedules` | GET | List all schedules for a tenant |

### User Management (Admin Only)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /users` | GET | List all users |
| `POST /users` | POST | Create user and send invitation |
| `DELETE /users/{user_id}` | DELETE | Delete a user |
| `POST /users/{user_id}/tenants/{tenant_id}` | POST | Grant user access to tenant |
| `DELETE /users/{user_id}/tenants/{tenant_id}` | DELETE | Revoke user access to tenant |

### Utility Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /` | GET | API root information |
| `GET /health` | GET | Health check (no auth required) |
| `GET /openapi.json` | GET | OpenAPI specification |

## Deployment

This service is deployed using AWS SAM (Serverless Application Model). The infrastructure includes:

- **API Gateway**: HTTP entry point
- **Lambda Function**: FastAPI application running the business logic
- **DynamoDB Tables**: Five tables for targets, tenants, mappings, schedules, and user mappings
- **Cognito User Pool**: User authentication and JWT token issuance
- **EventBridge Scheduler**: Automated schedule execution
- **IAM Roles**: Permissions for Lambda execution and AWS service access

### Deploy to AWS

```bash
# Build the application
sam build

# Deploy (first time)
sam deploy --guided

# Deploy updates
sam deploy
```

### Environment Variables

The Lambda function automatically receives:
- `DYNAMODB_TABLE` - Targets table name
- `DYNAMODB_TENANTS_TABLE` - Tenants table name
- `DYNAMODB_TENANT_TABLE` - Mappings table name
- `DYNAMODB_SCHEDULES_TABLE` - Schedules table name
- `DYNAMODB_USER_MAPPINGS_TABLE` - User mappings table name
- `COGNITO_USER_POOL_ID` - User pool ID
- `COGNITO_CLIENT_ID` - App client ID
- `SCHEDULER_ROLE_ARN` - IAM role for EventBridge
- `SCHEDULER_GROUP_NAME` - EventBridge schedule group
- `ADMIN_USER_EMAIL` - Bootstrap admin user email

## Testing with Bruno

The `ExecutionAPI/bruno` directory contains a complete Bruno API collection for testing all endpoints.

1. Open the collection in Bruno
2. Set the `authToken` variable with your JWT token
3. Update path parameters for your tenant IDs
4. Execute requests to test functionality

## Security Best Practices

1. **Always use HTTPS** - Never send JWT tokens over unencrypted connections
2. **Rotate tokens regularly** - JWT tokens should have reasonable expiration times
3. **Principle of least privilege** - Only grant tenant access to users who need it
4. **Monitor execution logs** - Review CloudWatch logs for suspicious activity
5. **Validate input parameters** - Target schemas enforce parameter validation
6. **Use AWS Secrets Manager** - Store sensitive configuration in secrets, not code

## Common Use Cases

### 1. Multi-Tenant SaaS Application
Different customers (tenants) run their own automated workflows on schedules without interfering with each other.

### 2. Report Generation
Schedule daily, weekly, or monthly report generation and distribution via email or S3.

### 3. Data Processing Pipelines
Execute ETL (Extract, Transform, Load) jobs on a schedule with different configurations per tenant.

### 4. API Orchestration
Chain multiple Lambda functions together, scheduled to run in sequence for complex workflows.

### 5. Monitoring and Alerting
Run health checks and send alerts when thresholds are exceeded.

## Troubleshooting

### "Access denied" errors
- Verify your JWT token is valid and not expired
- Check that your user has been granted access to the tenant
- Admin operations require membership in the `admin` tenant

### Schedules not executing
- Verify the schedule state is `ENABLED`
- Check CloudWatch logs for the execution Lambda
- Confirm the EventBridge schedule was created successfully

### Function execution failures
- Verify the target Lambda function ARN is correct
- Check Lambda execution role has necessary permissions
- Review CloudWatch logs for the target Lambda function

## Architecture Decisions

### Why DynamoDB?
- Serverless and auto-scaling
- Fast key-value lookups for tenant mappings
- No infrastructure management required

### Why EventBridge Scheduler?
- Native AWS service for scheduled events
- Supports complex cron expressions
- Automatically handles retries and error handling
- Timezone support built-in

### Why FastAPI?
- Modern Python web framework with automatic API documentation
- Type hints for better code quality
- Async support for better performance
- Easy integration with Pydantic for data validation

## Future Enhancements

- **Service Accounts**: API keys for machine-to-machine authentication
- **Execution History**: Detailed logs of all function executions
- **Retry Policies**: Configurable retry logic for failed executions
- **Rate Limiting**: Prevent abuse with per-tenant rate limits
- **Webhook Notifications**: Send execution results to external endpoints
- **Function Chaining**: Execute multiple functions in sequence

## Contributing

This project uses:
- Python 3.13
- FastAPI for the web framework
- AWS SAM for infrastructure as code
- Bruno for API testing

## License

[Your license here]
