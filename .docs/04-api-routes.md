# Part 4: API Routes

---

## Overview

The API is built with **FastAPI** (Python) and served via **API Gateway + Lambda**. All routes are prefixed with `/api` by API Gateway.

- **Authentication**: All routes require a Cognito JWT (`Authorization: Bearer <token>`) unless noted otherwise
- **Authorization**: Tenant-scoped routes verify the user has access to the requested tenant via `UserMappingsTable`
- **Documentation**: Interactive Swagger UI is available at `/swagger`, ReDoc at `/redoc`

---

## Route Map

```
/api
├── /auth
│   ├── POST /login
│   ├── POST /signup
│   ├── POST /confirm-signup
│   ├── POST /resend-confirmation
│   ├── POST /logout
│   ├── POST /forgot-password
│   └── POST /confirm-forgot-password
│
├── /targets                          (Admin only)
│   ├── GET    /targets
│   ├── POST   /targets
│   ├── PUT    /targets/{target_id}
│   └── DELETE /targets/{target_id}
│
├── /tenants
│   ├── GET    /tenants
│   ├── GET    /tenants/{tenant_id}
│   ├── POST   /tenants               (Admin only)
│   ├── PUT    /tenants/{tenant_id}    (Admin only)
│   ├── DELETE /tenants/{tenant_id}    (Admin only)
│   ├── GET    /tenants/{tenant_id}/users
│   │
│   ├── /mappings (Target Aliases)
│   │   ├── GET    /tenants/{tid}/mappings
│   │   ├── POST   /tenants/{tid}/mappings
│   │   ├── GET    /tenants/{tid}/mappings/{alias}
│   │   ├── PUT    /tenants/{tid}/mappings/{alias}
│   │   ├── DELETE /tenants/{tid}/mappings/{alias}
│   │   └── POST   /tenants/{tid}/mappings/{alias}/_execute
│   │
│   ├── /schedules
│   │   ├── GET    /tenants/{tid}/schedules
│   │   ├── GET    /tenants/{tid}/mappings/{alias}/schedules
│   │   ├── POST   /tenants/{tid}/mappings/{alias}/schedules
│   │   ├── PUT    /tenants/{tid}/mappings/{alias}/schedules/{sid}
│   │   └── DELETE /tenants/{tid}/mappings/{alias}/schedules/{sid}
│   │
│   └── /executions
│       ├── GET    /tenants/{tid}/mappings/{alias}/schedules/{sid}/executions
│       ├── GET    /tenants/{tid}/mappings/{alias}/executions
│       ├── GET    /tenants/{tid}/mappings/{alias}/executions/{eid}
│       └── POST   /tenants/{tid}/mappings/{alias}/executions/{eid}/redrive
│
├── /user
│   ├── GET    /user/info
│   ├── GET    /users
│   ├── GET    /users/{user_id}/tenants
│   ├── POST   /users/{user_id}/tenants/{tenant_id}
│   ├── DELETE /users/{user_id}/tenants/{tenant_id}
│   ├── GET    /user/management
│   ├── PUT    /user/management/{user_id}
│   ├── DELETE /user/management/{user_id}
│   ├── POST   /user/management/invite
│   └── POST   /user/management/sync
│
├── GET /swagger                      (No auth)
├── GET /docs                         (No auth)
├── GET /health                       (No auth)
├── GET /config/cognito               (No auth)
└── GET /logout                       (No auth)
```

---

## Authentication Routes (`/auth`)

These routes handle user authentication via Cognito. **No JWT required.**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/auth/login` | Authenticate with email/password, returns JWT tokens |
| `POST` | `/auth/signup` | Register a new user account |
| `POST` | `/auth/confirm-signup` | Confirm registration with verification code |
| `POST` | `/auth/resend-confirmation` | Resend the confirmation code |
| `POST` | `/auth/logout` | Invalidate the current session |
| `POST` | `/auth/forgot-password` | Initiate password reset flow |
| `POST` | `/auth/confirm-forgot-password` | Complete password reset with code + new password |

---

## Target Routes (`/targets`) -- Admin Only

Targets define the AWS services that can be executed. Only admins can manage targets.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/targets` | List all target definitions |
| `POST` | `/targets` | Create a new target (Lambda, ECS, or Step Functions) |
| `PUT` | `/targets/{target_id}` | Update a target's configuration |
| `DELETE` | `/targets/{target_id}` | Delete a target definition |

**Target creation example:**
```json
POST /targets
{
  "target_id": "email-sender-v2",
  "target_name": "Email Sender",
  "target_description": "Sends emails via SES",
  "target_arn": "arn:aws:lambda:us-east-1:123:function:email-sender-v2",
  "target_type": "lambda",
  "target_parameter_schema": { "type": "object", "properties": { "to": { "type": "string" } } }
}
```

---

## Tenant Routes (`/tenants`)

### Tenant CRUD

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/tenants` | User | List tenants the user has access to |
| `GET` | `/tenants/{tenant_id}` | User | Get tenant details |
| `POST` | `/tenants` | Admin | Create a new tenant |
| `PUT` | `/tenants/{tenant_id}` | Admin | Update tenant details |
| `DELETE` | `/tenants/{tenant_id}` | Admin | Delete a tenant |
| `GET` | `/tenants/{tenant_id}/users` | User | List users with access to this tenant |

### Target Mapping Routes (Aliases)

Mappings connect tenants to targets via friendly aliases. This is the core of the multi-tenant architecture.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/tenants/{tid}/mappings` | List all mappings for a tenant |
| `POST` | `/tenants/{tid}/mappings` | Create a new mapping (alias → target) |
| `GET` | `/tenants/{tid}/mappings/{alias}` | Get a specific mapping |
| `PUT` | `/tenants/{tid}/mappings/{alias}` | Update a mapping (change target or defaults) |
| `DELETE` | `/tenants/{tid}/mappings/{alias}` | Delete a mapping |
| `POST` | `/tenants/{tid}/mappings/{alias}/_execute` | **Execute the target on-demand** |

**Mapping creation example:**
```json
POST /tenants/acme-corp/mappings
{
  "target_alias": "send-email",
  "target_id": "email-sender-v2",
  "default_payload": {
    "from": "noreply@acme.com",
    "template": "acme-branded"
  }
}
```

**On-demand execution:**
```json
POST /tenants/acme-corp/mappings/send-email/_execute
{
  "to": "customer@example.com",
  "subject": "Hello!"
}
```

This triggers an immediate execution that goes through the same Step Functions orchestration as scheduled runs (internally, it provisions a one-time EventBridge schedule to ensure consistent processing).

### Schedule Routes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/tenants/{tid}/schedules` | List all schedules for a tenant |
| `GET` | `/tenants/{tid}/mappings/{alias}/schedules` | List schedules for a specific mapping |
| `POST` | `/tenants/{tid}/mappings/{alias}/schedules` | Create a new schedule |
| `PUT` | `/tenants/{tid}/mappings/{alias}/schedules/{sid}` | Update a schedule |
| `DELETE` | `/tenants/{tid}/mappings/{alias}/schedules/{sid}` | Delete a schedule |

**Schedule creation example:**
```json
POST /tenants/acme-corp/mappings/send-email/schedules
{
  "schedule_id": "daily-9am",
  "schedule_expression": "cron(0 9 * * ? *)",
  "timezone": "America/New_York",
  "state": "ENABLED",
  "target_input": { "to": "sales@acme.com" },
  "description": "Daily sales report at 9 AM Eastern"
}
```

### Execution History & Redrive Routes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/tenants/{tid}/mappings/{alias}/schedules/{sid}/executions` | List executions for a schedule |
| `GET` | `/tenants/{tid}/mappings/{alias}/executions` | List all executions for a mapping |
| `GET` | `/tenants/{tid}/mappings/{alias}/executions/{eid}` | Get details of a specific execution |
| `POST` | `/tenants/{tid}/mappings/{alias}/executions/{eid}/redrive` | **Redrive a failed execution** |

**Execution response example:**
```json
{
  "execution_id": "2026-02-04T09:00:00Z#abc-123",
  "status": "SUCCEEDED",
  "result": { "message_id": "xyz-789" },
  "cloudwatch_logs_url": "https://console.aws.amazon.com/cloudwatch/...",
  "timestamp": "2026-02-04T09:00:00Z",
  "redrive_info": null
}
```

**Failed execution with redrive info:**
```json
{
  "execution_id": "2026-02-04T09:00:00Z#def-456",
  "status": "FAILED",
  "result": { "Error": "Lambda.ServiceException", "Cause": "Rate exceeded" },
  "redrive_info": {
    "can_redrive": true,
    "redrive_from_state": "ExecuteTargetWithErrorHandling",
    "failed_state": "ExecuteLambdaTarget"
  }
}
```

---

## User Management Routes (`/user`)

### Self-Service

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/user/info` | Get current user's profile and tenant access list |
| `GET` | `/users` | List all user-tenant mappings (for accessible tenants) |

### Admin User Management

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/user/management` | Admin | List all users with full detail |
| `PUT` | `/user/management/{user_id}` | Admin | Update user's tenant assignments (bulk) |
| `DELETE` | `/user/management/{user_id}` | Admin | Delete a user from Cognito and all mappings |
| `POST` | `/user/management/invite` | Admin | Invite a new user (creates Cognito account + tenant mappings) |
| `POST` | `/user/management/sync` | Admin | Sync Cognito users with DynamoDB mappings |

### User-Tenant Access

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/users/{user_id}/tenants` | Admin | List tenants a user has access to |
| `POST` | `/users/{user_id}/tenants/{tenant_id}` | Admin | Grant a user access to a tenant |
| `DELETE` | `/users/{user_id}/tenants/{tenant_id}` | Admin | Revoke a user's tenant access |

---

## Utility Routes

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/swagger` | None | Swagger UI (interactive API docs) |
| `GET` | `/docs` | None | Alias for Swagger UI |
| `GET` | `/health` | None | Health check endpoint |
| `GET` | `/config/cognito` | None | Returns Cognito configuration for the UI |
| `GET` | `/logout` | None | Handles Cognito logout redirect |

---

## API Gateway Routing

API Gateway handles two types of traffic through a single endpoint:

| Pattern | Destination | Purpose |
|---------|------------|---------|
| `/api/{proxy+}` | AppLambda (FastAPI) | All API requests |
| `/` | S3 Bucket | React UI index.html |
| `/{proxy+}` | S3 Bucket | React UI static files (JS, CSS, images) |

**SPA routing**: 404s from S3 return `index.html` to support client-side routing.

**Cache headers**: Static assets cached for 1 year; `index.html` set to no-cache for instant updates.

---

*Previous: [Part 3 - Security Model](03-security-model.md) | Next: [Part 5 - DR Failover Process](05-dr-failover.md)*
